from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from simple_backup.jobs import JobDefinition, discover_job_scripts, execute_job_script


class JobDiscoveryTests(unittest.TestCase):
    def test_discovery_filters_hidden_disabled_and_non_shell_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            jobs_dir = Path(temp_dir)
            (jobs_dir / "db.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (jobs_dir / ".hidden.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (jobs_dir / "skip.sh.disabled").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (jobs_dir / "notes.txt").write_text("ignored\n", encoding="utf-8")

            with patch("simple_backup.jobs._is_executable", side_effect=lambda path: path.name == "db.sh"):
                discovered = discover_job_scripts(jobs_dir)

        self.assertEqual([path.name for path in discovered], ["db"])

    def test_discovery_returns_empty_list_for_missing_directory(self) -> None:
        self.assertEqual(discover_job_scripts(Path("./missing-jobs")), [])


class JobExecutionTests(unittest.TestCase):
    def test_execute_job_collects_output_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script_path = root / "job.sh"
            script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            job = JobDefinition(name="job", script_path=script_path)
            job_work_dir = root / "work"

            def fake_run(command: list[str], **kwargs: object):
                del command
                environment = kwargs["env"]
                workdir = Path(str(environment["BACKUP_WORKDIR"]))
                self.assertEqual(environment["SB_WORK_DIR"], environment["BACKUP_WORKDIR"])
                (workdir / "backup.sql").write_text("select 1;", encoding="utf-8")

                class Completed:
                    returncode = 0
                    stdout = "ok\n"
                    stderr = ""

                return Completed()

            with patch("simple_backup.jobs.subprocess.run", side_effect=fake_run):
                result = execute_job_script(
                    job,
                    device_name="server-a",
                    timestamp=datetime(2026, 3, 13, 21, 15, 0, tzinfo=timezone.utc),
                    target_root=root / "output",
                    timeout_seconds=30,
                    job_work_dir=job_work_dir,
                )

        self.assertTrue(result.success)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout, "ok\n")
        self.assertEqual([path.name for path in result.output_files], ["backup.sql"])


if __name__ == "__main__":
    unittest.main()