from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch

from simple_backup.archive import build_archive_name
from simple_backup.config import default_config
from simple_backup.jobs import JobDefinition, JobExecutionResult
from simple_backup.orchestrator import BackupError, _WORK_DIR_LOCK_FILE_NAME, _cleanup_run_dir, run_backup


class OrchestratorTests(unittest.TestCase):
    def _work_dir_entries_without_lock(self, config) -> list[Path]:
        if not config.runtime.work_dir.exists():
            return []
        return sorted(
            (path for path in config.runtime.work_dir.iterdir() if path.name != _WORK_DIR_LOCK_FILE_NAME),
            key=lambda path: path.name,
        )

    def _make_config(self, root: Path):
        config = default_config()
        return replace(
            config,
            storage=replace(config.storage, target_root=root / "output", require_mount=False),
            runtime=replace(
                config.runtime,
                jobs_dir=root / "jobs",
                work_dir=root / "tmp",
                log_dir=root / "logs",
                job_timeout_seconds=60,
            ),
        )

    def _successful_job(self, config) -> JobDefinition:
        config.runtime.jobs_dir.mkdir(parents=True, exist_ok=True)
        script_path = config.runtime.jobs_dir / "db.sh"
        script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        return JobDefinition(name="db", script_path=script_path.resolve())

    def _successful_job_result(self, job_definition: JobDefinition, **kwargs: object) -> JobExecutionResult:
        job_work_dir = Path(kwargs["job_work_dir"])
        artifact_path = job_work_dir / "dump.sql"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text("select 1;", encoding="utf-8")
        return JobExecutionResult(
            job=job_definition,
            success=True,
            exit_code=0,
            stdout="dump created\n",
            stderr="",
            output_files=[artifact_path],
        )

    def test_run_backup_builds_archive_and_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._make_config(root)
            job = self._successful_job(config)

            with patch("simple_backup.orchestrator.discover_job_scripts", return_value=[job]), patch(
                "simple_backup.orchestrator.execute_job_script", side_effect=self._successful_job_result
            ):
                result = run_backup(config)

            self.assertTrue(result.archive_path.exists())
            self.assertTrue(result.log_file.exists())
            self.assertFalse(result.artifacts_dir.exists())
            self.assertFalse(result.artifacts_dir.parent.exists())
            self.assertTrue(config.runtime.work_dir.exists())
            self.assertEqual(len(result.job_results), 1)
            log_content = result.log_file.read_text(encoding="utf-8")
            self.assertIn("retention_deleted:", log_content)
            self.assertIn("[job:db]", log_content)
            self.assertIn("dump.sql", log_content)
            with tarfile.open(result.archive_path, mode="r:gz") as archive:
                archive_names = archive.getnames()
            self.assertIn("artifacts/db/dump.sql", archive_names)

    def test_run_backup_raises_when_job_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = replace(
                self._make_config(root),
                notifications=replace(
                    self._make_config(root).notifications,
                    email=replace(default_config().notifications.email, enabled=True, smtp_to=["ops@example.com"]),
                ),
            )
            job = self._successful_job(config)
            job = JobDefinition(name="db", script_path=(root / "jobs" / "db.sh").resolve())

            failed = JobExecutionResult(
                job=job,
                success=False,
                exit_code=12,
                stdout="",
                stderr="boom\n",
                output_files=[],
            )

            with patch("simple_backup.orchestrator.discover_job_scripts", return_value=[job]), patch(
                "simple_backup.orchestrator.execute_job_script", return_value=failed
            ), patch("simple_backup.orchestrator.send_failure_email") as send_failure_email_mock:
                with self.assertRaises(BackupError):
                    run_backup(config)

            send_failure_email_mock.assert_called_once()
            self.assertEqual(send_failure_email_mock.call_args.kwargs["script_name"], "db.sh")
            self.assertIn("Backup failed for script db.sh", send_failure_email_mock.call_args.kwargs["error_message"])
            self.assertTrue(config.runtime.work_dir.exists())
            self.assertEqual(self._work_dir_entries_without_lock(config), [])

    def test_run_backup_removes_only_current_run_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._make_config(root)
            sibling_run_dir = config.runtime.work_dir / "keep-me"
            sibling_run_dir.mkdir(parents=True, exist_ok=True)
            (sibling_run_dir / "note.txt").write_text("keep", encoding="utf-8")
            job = self._successful_job(config)

            with patch("simple_backup.orchestrator.discover_job_scripts", return_value=[job]), patch(
                "simple_backup.orchestrator.execute_job_script", side_effect=self._successful_job_result
            ):
                result = run_backup(config)

            self.assertFalse(result.artifacts_dir.parent.exists())
            self.assertTrue(sibling_run_dir.exists())
            self.assertTrue((sibling_run_dir / "note.txt").exists())

    def test_run_backup_preserves_workdir_when_mount_check_fails_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = replace(
                self._make_config(root),
                notifications=replace(
                    self._make_config(root).notifications,
                    email=replace(default_config().notifications.email, enabled=True, smtp_to=["ops@example.com"]),
                ),
            )
            sentinel_dir = config.runtime.work_dir / "existing-run"
            sentinel_dir.mkdir(parents=True, exist_ok=True)
            (sentinel_dir / "sentinel.txt").write_text("keep", encoding="utf-8")

            with patch("simple_backup.orchestrator._ensure_storage_ready", side_effect=BackupError("mount failed")), patch(
                "simple_backup.orchestrator.send_failure_email"
            ):
                with self.assertRaises(BackupError):
                    run_backup(config)

            self.assertTrue((sentinel_dir / "sentinel.txt").exists())

    def test_run_backup_removes_staging_when_archive_creation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._make_config(root)
            job = self._successful_job(config)

            with patch("simple_backup.orchestrator.discover_job_scripts", return_value=[job]), patch(
                "simple_backup.orchestrator.execute_job_script", side_effect=self._successful_job_result
            ), patch("simple_backup.orchestrator.create_final_archive", side_effect=RuntimeError("archive boom")):
                with self.assertRaisesRegex(RuntimeError, "archive boom"):
                    run_backup(config)

            self.assertTrue(config.runtime.work_dir.exists())
            self.assertEqual(self._work_dir_entries_without_lock(config), [])

    def test_run_backup_rejects_concurrent_run_for_same_work_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._make_config(root)
            job = self._successful_job(config)
            first_run_ready = threading.Event()
            release_first_run = threading.Event()
            first_run_result: dict[str, object] = {}

            def holding_execute(job_definition: JobDefinition, **kwargs: object) -> JobExecutionResult:
                result = self._successful_job_result(job_definition, **kwargs)
                first_run_ready.set()
                self.assertTrue(release_first_run.wait(timeout=5))
                return result

            def run_first_backup() -> None:
                try:
                    first_run_result["result"] = run_backup(config)
                except Exception as error:  # pragma: no cover - assertion path
                    first_run_result["error"] = error

            with patch("simple_backup.orchestrator.discover_job_scripts", return_value=[job]), patch(
                "simple_backup.orchestrator.execute_job_script", side_effect=holding_execute
            ):
                first_thread = threading.Thread(target=run_first_backup)
                first_thread.start()
                self.assertTrue(first_run_ready.wait(timeout=5))

                active_entries = self._work_dir_entries_without_lock(config)
                self.assertEqual(len(active_entries), 1)
                first_run_dir = active_entries[0]
                staged_file = first_run_dir / "artifacts" / "db" / "dump.sql"
                self.assertTrue(staged_file.exists())
                staged_content = staged_file.read_text(encoding="utf-8")

                with self.assertRaisesRegex(BackupError, "Another backup run is already active"):
                    run_backup(config)

                self.assertTrue(staged_file.exists())
                self.assertEqual(staged_file.read_text(encoding="utf-8"), staged_content)
                self.assertEqual(self._work_dir_entries_without_lock(config), [first_run_dir])

                release_first_run.set()
                first_thread.join(timeout=5)

            self.assertFalse(first_thread.is_alive())
            self.assertNotIn("error", first_run_result)
            self.assertIn("result", first_run_result)

    def test_run_backup_releases_lock_after_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._make_config(root)
            job = self._successful_job(config)

            with patch("simple_backup.orchestrator.discover_job_scripts", return_value=[job]), patch(
                "simple_backup.orchestrator.execute_job_script", side_effect=RuntimeError("job boom")
            ):
                with self.assertRaisesRegex(RuntimeError, "job boom"):
                    run_backup(config)

            with patch("simple_backup.orchestrator.discover_job_scripts", return_value=[job]), patch(
                "simple_backup.orchestrator.execute_job_script", side_effect=self._successful_job_result
            ):
                result = run_backup(config)

            self.assertTrue(result.archive_path.exists())
            self.assertEqual(self._work_dir_entries_without_lock(config), [])

    def test_cleanup_rejects_symlinked_run_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._make_config(root)
            config.runtime.work_dir.mkdir(parents=True, exist_ok=True)
            outside_dir = root / "outside-run"
            outside_dir.mkdir(parents=True, exist_ok=True)
            (outside_dir / "outside.txt").write_text("keep", encoding="utf-8")
            run_dir = config.runtime.work_dir / "20260723T033001Z"
            run_dir.mkdir(parents=True, exist_ok=True)

            with patch.object(type(run_dir), "is_symlink", return_value=True):
                with self.assertRaisesRegex(BackupError, "symlinked run directory"):
                    _cleanup_run_dir(config, run_dir)

            self.assertTrue(run_dir.exists())
            self.assertTrue((outside_dir / "outside.txt").exists())

    def test_run_backup_reports_cleanup_failure_without_masking_backup_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_config = self._make_config(root)
            config = replace(
                base_config,
                notifications=replace(
                    base_config.notifications,
                    email=replace(base_config.notifications.email, enabled=True, smtp_to=["ops@example.com"]),
                ),
            )
            job = self._successful_job(config)
            failed = JobExecutionResult(
                job=job,
                success=False,
                exit_code=12,
                stdout="",
                stderr="boom\n",
                output_files=[],
            )

            with patch("simple_backup.orchestrator.discover_job_scripts", return_value=[job]), patch(
                "simple_backup.orchestrator.execute_job_script", return_value=failed
            ), patch("simple_backup.orchestrator.shutil.rmtree", side_effect=OSError("cleanup boom")), patch(
                "simple_backup.orchestrator.send_failure_email"
            ) as send_failure_email_mock:
                with self.assertRaisesRegex(BackupError, "Backup failed for script db.sh"):
                    run_backup(config)

            log_files = list(config.runtime.log_dir.glob("*.log"))
            self.assertEqual(len(log_files), 1)
            log_content = log_files[0].read_text(encoding="utf-8")
            self.assertIn("cleanup_exception:", log_content)
            self.assertIn("cleanup boom", log_content)
            self.assertIn("Cleanup failed: cleanup boom", send_failure_email_mock.call_args.kwargs["error_message"])

    def test_run_backup_reports_cleanup_failure_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_config = self._make_config(root)
            config = replace(
                base_config,
                notifications=replace(
                    base_config.notifications,
                    email=replace(base_config.notifications.email, enabled=True, smtp_to=["ops@example.com"]),
                ),
            )
            job = self._successful_job(config)

            with patch("simple_backup.orchestrator.discover_job_scripts", return_value=[job]), patch(
                "simple_backup.orchestrator.execute_job_script", side_effect=self._successful_job_result
            ), patch("simple_backup.orchestrator.shutil.rmtree", side_effect=OSError("cleanup boom")), patch(
                "simple_backup.orchestrator.send_failure_email"
            ) as send_failure_email_mock:
                with self.assertRaisesRegex(BackupError, "Backup cleanup failed"):
                    run_backup(config)

            archives = list(config.storage.target_root.glob("*.tar.gz"))
            self.assertEqual(len(archives), 1)
            log_files = list(config.runtime.log_dir.glob("*.log"))
            self.assertEqual(len(log_files), 1)
            self.assertIn("cleanup boom", log_files[0].read_text(encoding="utf-8"))
            self.assertIn("cleanup boom", send_failure_email_mock.call_args.kwargs["error_message"])
            self.assertEqual(len(self._work_dir_entries_without_lock(config)), 1)

    def test_run_backup_sends_notification_for_non_job_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_config = self._make_config(root)
            config = replace(
                base_config,
                notifications=replace(
                    base_config.notifications,
                    email=replace(base_config.notifications.email, enabled=True, smtp_to=["ops@example.com"]),
                ),
            )

            with patch("simple_backup.orchestrator._ensure_storage_ready", side_effect=BackupError("mount failed")), patch(
                "simple_backup.orchestrator.send_failure_email"
            ) as send_failure_email_mock:
                with self.assertRaises(BackupError):
                    run_backup(config)

            send_failure_email_mock.assert_called_once()
            self.assertEqual(send_failure_email_mock.call_args.kwargs["script_name"], "unknown.sh")
            self.assertEqual(send_failure_email_mock.call_args.kwargs["error_message"], "mount failed")


class RetentionTests(unittest.TestCase):
    def test_retention_keeps_expected_number_of_archives(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = default_config()
            config = replace(
                config,
                device=replace(config.device, name="server-a"),
                storage=replace(config.storage, target_root=root / "output", require_mount=False),
                retention=replace(config.retention, daily=2, weekly=1, monthly=1, yearly=1),
            )
            config.storage.target_root.mkdir(parents=True, exist_ok=True)

            base = datetime(2026, 3, 13, 21, 15, 0, tzinfo=timezone.utc)
            for offset in range(6):
                stamp = base - timedelta(days=offset)
                archive = config.storage.target_root / build_archive_name(config.device.name, stamp)
                archive.write_bytes(b"archive")

            with patch("simple_backup.orchestrator.discover_job_scripts", return_value=[]):
                result = run_backup(config)

            remaining = sorted(path.name for path in config.storage.target_root.glob("*.tar.gz"))
            self.assertEqual(len(remaining), 4)
            self.assertIn(result.archive_path.name, remaining)
            log_content = result.log_file.read_text(encoding="utf-8")
            self.assertIn("retention_deleted:", log_content)


if __name__ == "__main__":
    unittest.main()