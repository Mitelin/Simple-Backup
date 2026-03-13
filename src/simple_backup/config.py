from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import socket
from typing import Any

import yaml


def _default_device_name() -> str:
    return sanitize_device_name(socket.gethostname())


def sanitize_device_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._")
    return normalized.lower() or "backup-node"


@dataclass(slots=True)
class DeviceConfig:
    name: str


@dataclass(slots=True)
class StorageConfig:
    target_root: Path
    require_mount: bool


@dataclass(slots=True)
class RetentionConfig:
    daily: int
    weekly: int
    monthly: int
    yearly: int


@dataclass(slots=True)
class RuntimeConfig:
    jobs_dir: Path
    work_dir: Path
    log_dir: Path
    job_timeout_seconds: int


@dataclass(slots=True)
class EmailNotificationConfig:
    enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from: str
    smtp_to: list[str]
    use_starttls: bool
    use_ssl: bool
    subject_prefix: str


@dataclass(slots=True)
class NotificationsConfig:
    email: EmailNotificationConfig


@dataclass(slots=True)
class AppConfig:
    device: DeviceConfig
    storage: StorageConfig
    retention: RetentionConfig
    runtime: RuntimeConfig
    notifications: NotificationsConfig


def default_config() -> AppConfig:
    return AppConfig(
        device=DeviceConfig(name=_default_device_name()),
        storage=StorageConfig(target_root=Path("./output"), require_mount=False),
        retention=RetentionConfig(daily=7, weekly=4, monthly=12, yearly=10),
        runtime=RuntimeConfig(
            jobs_dir=Path("./jobs"),
            work_dir=Path("./tmp"),
            log_dir=Path("./logs"),
            job_timeout_seconds=3600,
        ),
        notifications=NotificationsConfig(
            email=EmailNotificationConfig(
                enabled=False,
                smtp_host="localhost",
                smtp_port=25,
                smtp_username="",
                smtp_password="",
                smtp_from="simple-backup@localhost",
                smtp_to=[],
                use_starttls=False,
                use_ssl=False,
                subject_prefix="[Simple Backup]",
            )
        ),
    )


def load_config(config_path: Path) -> AppConfig:
    config = default_config()
    if not config_path.exists():
        return config

    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("Configuration root must be a mapping.")

    base_dir = config_path.parent.resolve()

    return AppConfig(
        device=DeviceConfig(name=sanitize_device_name(_get_nested(payload, "device", "name", default=config.device.name))),
        storage=StorageConfig(
            target_root=_resolve_config_path(
                base_dir, _get_nested(payload, "storage", "target_root", default=str(config.storage.target_root))
            ),
            require_mount=bool(_get_nested(payload, "storage", "require_mount", default=config.storage.require_mount)),
        ),
        retention=RetentionConfig(
            daily=int(_get_nested(payload, "retention", "daily", default=config.retention.daily)),
            weekly=int(_get_nested(payload, "retention", "weekly", default=config.retention.weekly)),
            monthly=int(_get_nested(payload, "retention", "monthly", default=config.retention.monthly)),
            yearly=int(_get_nested(payload, "retention", "yearly", default=config.retention.yearly)),
        ),
        runtime=RuntimeConfig(
            jobs_dir=_resolve_config_path(base_dir, _get_nested(payload, "runtime", "jobs_dir", default=str(config.runtime.jobs_dir))),
            work_dir=_resolve_config_path(base_dir, _get_nested(payload, "runtime", "work_dir", default=str(config.runtime.work_dir))),
            log_dir=_resolve_config_path(base_dir, _get_nested(payload, "runtime", "log_dir", default=str(config.runtime.log_dir))),
            job_timeout_seconds=int(
                _get_nested(payload, "runtime", "job_timeout_seconds", default=config.runtime.job_timeout_seconds)
            ),
        ),
        notifications=NotificationsConfig(
            email=EmailNotificationConfig(
                enabled=bool(_get_nested_email(payload, "enabled", default=config.notifications.email.enabled)),
                smtp_host=str(_get_nested_email(payload, "smtp_host", default=config.notifications.email.smtp_host)),
                smtp_port=int(_get_nested_email(payload, "smtp_port", default=config.notifications.email.smtp_port)),
                smtp_username=str(
                    _get_nested_email(payload, "smtp_username", default=config.notifications.email.smtp_username)
                ),
                smtp_password=str(
                    _get_nested_email(payload, "smtp_password", default=config.notifications.email.smtp_password)
                ),
                smtp_from=str(_get_nested_email(payload, "smtp_from", default=config.notifications.email.smtp_from)),
                smtp_to=_normalize_email_recipients(
                    _get_nested_email(payload, "smtp_to", default=config.notifications.email.smtp_to)
                ),
                use_starttls=bool(
                    _get_nested_email(payload, "use_starttls", default=config.notifications.email.use_starttls)
                ),
                use_ssl=bool(_get_nested_email(payload, "use_ssl", default=config.notifications.email.use_ssl)),
                subject_prefix=str(
                    _get_nested_email(payload, "subject_prefix", default=config.notifications.email.subject_prefix)
                ),
            )
        ),
    )


def _get_nested(payload: dict[str, Any], section: str, key: str, default: Any) -> Any:
    section_payload = payload.get(section, {})
    if not isinstance(section_payload, dict):
        return default
    return section_payload.get(key, default)


def _resolve_config_path(base_dir: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def _get_nested_email(payload: dict[str, Any], key: str, default: Any) -> Any:
    notifications_payload = payload.get("notifications", {})
    if not isinstance(notifications_payload, dict):
        return default
    email_payload = notifications_payload.get("email", {})
    if not isinstance(email_payload, dict):
        return default
    return email_payload.get(key, default)


def _normalize_email_recipients(raw_value: Any) -> list[str]:
    if isinstance(raw_value, str):
        return [item.strip() for item in raw_value.split(",") if item.strip()]
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    return []