from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
import smtplib

from simple_backup.config import EmailNotificationConfig


class NotificationError(RuntimeError):
    pass


def send_failure_email(
    email_config: EmailNotificationConfig,
    *,
    device_name: str,
    timestamp: datetime,
    script_name: str,
    error_message: str,
) -> None:
    if not email_config.enabled or not email_config.smtp_to:
        return

    message = EmailMessage()
    formatted_date = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    message["From"] = email_config.smtp_from
    message["To"] = ", ".join(email_config.smtp_to)
    message["Subject"] = (
        f"{email_config.subject_prefix} Selhalo {script_name} na stroji {device_name} {formatted_date}"
    )
    message.set_content(
        "\n".join(
            [
                "Backup run failed.",
                f"Script: {script_name}",
                f"Machine: {device_name}",
                f"Date: {formatted_date}",
                f"Error: {error_message}",
            ]
        )
    )

    try:
        if email_config.use_ssl:
            smtp_client = smtplib.SMTP_SSL(email_config.smtp_host, email_config.smtp_port, timeout=30)
        else:
            smtp_client = smtplib.SMTP(email_config.smtp_host, email_config.smtp_port, timeout=30)

        with smtp_client as client:
            if email_config.use_starttls and not email_config.use_ssl:
                client.starttls()
            if email_config.smtp_username:
                client.login(email_config.smtp_username, email_config.smtp_password)
            client.send_message(message)
    except Exception as error:
        raise NotificationError(f"Failed to send failure email: {error}") from error