from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from simple_backup.archive import build_archive_name
from simple_backup.config import RetentionConfig
from simple_backup.retention import ArchiveEntry, apply_retention


class RetentionModuleTests(unittest.TestCase):
    def test_retention_layers_weekly_and_monthly_after_daily_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target_root = Path(temp_dir)
            device_name = "server-a"
            retention = RetentionConfig(daily=7, weekly=2, monthly=2, yearly=0)
            timestamps = [
                datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 28, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 27, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 26, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 24, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 2, 15, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc),
            ]

            for timestamp in timestamps:
                archive_path = target_root / build_archive_name(device_name, timestamp)
                archive_path.write_bytes(b"archive")

            outcome = apply_retention(target_root, device_name, retention)
            kept_names = {path.name for path in outcome.kept}

            self.assertEqual(len(kept_names), 11)
            self.assertIn("server-a-20260324T100000Z.tar.gz", kept_names)
            self.assertIn("server-a-20260318T100000Z.tar.gz", kept_names)
            self.assertIn("server-a-20260311T100000Z.tar.gz", kept_names)
            self.assertIn("server-a-20260215T100000Z.tar.gz", kept_names)
            self.assertNotIn("server-a-20260110T100000Z.tar.gz", kept_names)

    def test_retention_can_count_pending_archive_in_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target_root = Path(temp_dir)
            device_name = "server-a"
            retention = RetentionConfig(daily=1, weekly=0, monthly=0, yearly=0)
            old_timestamp = datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc)
            old_archive = target_root / build_archive_name(device_name, old_timestamp)
            old_archive.write_bytes(b"archive")

            pending_timestamp = datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc)
            pending_archive = target_root / build_archive_name(device_name, pending_timestamp)

            outcome = apply_retention(
                target_root,
                device_name,
                retention,
                protected_paths={pending_archive.resolve()},
                pending_entries=[ArchiveEntry(path=pending_archive, timestamp=pending_timestamp)],
            )

            self.assertFalse(old_archive.exists())
            self.assertEqual(outcome.deleted, [old_archive])
            self.assertEqual(outcome.kept, [pending_archive])


if __name__ == "__main__":
    unittest.main()