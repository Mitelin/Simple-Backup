from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tarfile


def build_archive_name(device_name: str, timestamp: datetime) -> str:
    utc_timestamp = timestamp.astimezone(timezone.utc)
    return f"{device_name}-{utc_timestamp.strftime('%Y%m%dT%H%M%SZ')}.tar.gz"


def create_final_archive(
    *,
    artifacts_dir: Path,
    log_file: Path,
    target_root: Path | None = None,
    device_name: str | None = None,
    timestamp: datetime | None = None,
    archive_path: Path | None = None,
) -> Path:
    resolved_archive_path = archive_path
    if resolved_archive_path is None:
        if target_root is None or device_name is None or timestamp is None:
            raise ValueError("target_root, device_name and timestamp are required when archive_path is not provided")
        target_root.mkdir(parents=True, exist_ok=True)
        resolved_archive_path = target_root / build_archive_name(device_name, timestamp)
    else:
        resolved_archive_path.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(resolved_archive_path, mode="w:gz") as archive:
        if log_file.exists():
            archive.add(log_file, arcname="log.txt")

        if artifacts_dir.exists():
            for path in sorted(artifacts_dir.rglob("*")):
                if path.is_file():
                    archive.add(path, arcname=Path("artifacts") / path.relative_to(artifacts_dir))

    return resolved_archive_path