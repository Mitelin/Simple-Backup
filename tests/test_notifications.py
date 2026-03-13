from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from simple_backup.config import EmailNotificationConfig
from simple_backup.notifications import send_failure_email


class NotificationTests(unittest.TestCase):
    def test_send_failure_email_uses_smtp_settings(self) -> None:
        email_config = EmailNotificationConfig(
            enabled=True,
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="backup@example.com",
            smtp_password="secret",
            smtp_from="backup@example.com",
            smtp_to=["ops@example.com"],
            use_starttls=True,
            use_ssl=False,
            subject_prefix="[Simple Backup]",
        )

        with patch("simple_backup.notifications.smtplib.SMTP") as smtp_mock:
            client = smtp_mock.return_value.__enter__.return_value
            send_failure_email(
                email_config,
                device_name="server-a",
                timestamp=datetime(2026, 3, 13, 21, 15, 0, tzinfo=timezone.utc),
                script_name="db.sh",
                error_message="exit code 12",
            )

        smtp_mock.assert_called_once_with("smtp.example.com", 587, timeout=30)
        client.starttls.assert_called_once()
        client.login.assert_called_once_with("backup@example.com", "secret")
        client.send_message.assert_called_once()
        message = client.send_message.call_args.args[0]
        self.assertIn("Selhalo db.sh na stroji server-a", message["Subject"])


if __name__ == "__main__":
    unittest.main()