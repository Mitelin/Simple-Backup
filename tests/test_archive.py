from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tarfile
import tempfile
import unittest

from simple_backup.archive import build_archive_name, create_final_archive


class ArchiveTests(unittest.TestCase):
    def test_archive_name_contains_device_and_utc_timestamp(self) -> None:
        timestamp = datetime(2026, 3, 13, 21, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(build_archive_name("server-a", timestamp), "server-a-20260313T211500Z.tar.gz")

    def test_final_archive_contains_log_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts_dir = root / "artifacts"
            artifacts_dir.mkdir()
            nested_dir = artifacts_dir / "sql"
            nested_dir.mkdir()
            (nested_dir / "dump.sql").write_text("select 1;", encoding="utf-8")

            log_file = root / "run.log"
            log_file.write_text("backup log", encoding="utf-8")

            archive_path = create_final_archive(
                artifacts_dir=artifacts_dir,
                log_file=log_file,
                archive_path=root / "output" / "server-a-20260313T211500Z.tar.gz",
            )

            self.assertTrue(archive_path.exists())
            with tarfile.open(archive_path, mode="r:gz") as archive:
                names = archive.getnames()

            self.assertIn("log.txt", names)
            self.assertIn("artifacts/sql/dump.sql", names)


if __name__ == "__main__":
    unittest.main()