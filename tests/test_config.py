from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from simple_backup.config import load_config, sanitize_device_name


class ConfigTests(unittest.TestCase):
    def test_sanitize_device_name_normalizes_value(self) -> None:
        self.assertEqual(sanitize_device_name(" My Server 01 "), "my-server-01")

    def test_load_config_reads_overrides(self) -> None:
        config_payload = """
device:
  name: App Node
storage:
  target_root: ./backups
runtime:
  job_timeout_seconds: 90
notifications:
  email:
    enabled: true
    smtp_host: smtp.example.com
    smtp_to:
      - ops@example.com
      - admin@example.com
"""

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(config_payload, encoding="utf-8")

            config = load_config(config_path)

        self.assertEqual(config.device.name, "app-node")
        self.assertEqual(config.storage.target_root, (config_path.parent / "backups").resolve())
        self.assertEqual(config.runtime.job_timeout_seconds, 90)
        self.assertTrue(config.notifications.email.enabled)
        self.assertEqual(config.notifications.email.smtp_host, "smtp.example.com")
        self.assertEqual(config.notifications.email.smtp_to, ["ops@example.com", "admin@example.com"])


if __name__ == "__main__":
    unittest.main()