from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from simple_backup.archive import build_archive_name
from simple_backup.config import default_config
from simple_backup.jobs import JobDefinition, JobExecutionResult
from simple_backup.orchestrator import BackupError, run_backup


class OrchestratorTests(unittest.TestCase):
    def test_run_backup_builds_archive_and_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = default_config()
            config = replace(
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
            config.runtime.jobs_dir.mkdir(parents=True, exist_ok=True)
            (config.runtime.jobs_dir / "db.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")

            job = JobDefinition(name="db", script_path=(config.runtime.jobs_dir / "db.sh").resolve())

            def fake_execute(job_definition: JobDefinition, **kwargs: object) -> JobExecutionResult:
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

            with patch("simple_backup.orchestrator.discover_job_scripts", return_value=[job]), patch(
                "simple_backup.orchestrator.execute_job_script", side_effect=fake_execute
            ):
                result = run_backup(config)

            self.assertTrue(result.archive_path.exists())
            self.assertTrue(result.log_file.exists())
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
            config = default_config()
            config = replace(
                config,
                storage=replace(config.storage, target_root=root / "output", require_mount=False),
                runtime=replace(config.runtime, jobs_dir=root / "jobs", work_dir=root / "tmp", log_dir=root / "logs"),
                notifications=replace(
                    config.notifications,
                    email=replace(config.notifications.email, enabled=True, smtp_to=["ops@example.com"]),
                ),
            )
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

    def test_run_backup_sends_notification_for_non_job_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = default_config()
            config = replace(
                config,
                storage=replace(config.storage, target_root=root / "output", require_mount=False),
                runtime=replace(config.runtime, jobs_dir=root / "jobs", work_dir=root / "tmp", log_dir=root / "logs"),
                notifications=replace(
                    config.notifications,
                    email=replace(config.notifications.email, enabled=True, smtp_to=["ops@example.com"]),
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