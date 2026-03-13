from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

from simple_backup.config import RetentionConfig


ARCHIVE_PATTERN = re.compile(r"^(?P<device>.+)-(?P<timestamp>\d{8}T\d{6}Z)\.tar\.gz$")


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    path: Path
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class RetentionOutcome:
    kept: list[Path]
    deleted: list[Path]


def apply_retention(
    target_root: Path, device_name: str, retention: RetentionConfig, protected_paths: set[Path] | None = None
) -> RetentionOutcome:
    archives = _load_archives(target_root, device_name)
    keep_paths = _select_keep_paths(archives, retention)
    if protected_paths:
        keep_paths.update(path.resolve() for path in protected_paths)

    deleted: list[Path] = []
    for entry in archives:
        if entry.path in keep_paths:
            continue
        entry.path.unlink(missing_ok=True)
        deleted.append(entry.path)

    kept = [entry.path for entry in archives if entry.path in keep_paths]
    return RetentionOutcome(kept=kept, deleted=deleted)


def _load_archives(target_root: Path, device_name: str) -> list[ArchiveEntry]:
    entries: list[ArchiveEntry] = []
    if not target_root.exists():
        return entries

    for path in target_root.glob(f"{device_name}-*.tar.gz"):
        match = ARCHIVE_PATTERN.match(path.name)
        if match is None or match.group("device") != device_name:
            continue
        timestamp = datetime.strptime(match.group("timestamp"), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        entries.append(ArchiveEntry(path=path, timestamp=timestamp))

    entries.sort(key=lambda item: item.timestamp, reverse=True)
    return entries


def _select_keep_paths(archives: list[ArchiveEntry], retention: RetentionConfig) -> set[Path]:
    if not archives:
        return set()

    keep: set[Path] = {archives[0].path}
    keep.update(_keep_by_bucket(archives, retention.daily, lambda entry: entry.timestamp.date().isoformat()))
    keep.update(_keep_by_bucket(archives, retention.weekly, lambda entry: _week_bucket(entry.timestamp)))
    keep.update(_keep_by_bucket(archives, retention.monthly, lambda entry: entry.timestamp.strftime("%Y-%m")))
    if retention.yearly > 0:
        keep.update(_keep_by_bucket(archives, retention.yearly, lambda entry: entry.timestamp.strftime("%Y")))
    return keep


def _keep_by_bucket(
    archives: list[ArchiveEntry], limit: int, bucket_key: Callable[[ArchiveEntry], str]
) -> set[Path]:
    if limit <= 0:
        return set()

    kept: set[Path] = set()
    seen: set[str] = set()
    for entry in archives:
        key = bucket_key(entry)
        if key in seen:
            continue
        seen.add(key)
        kept.add(entry.path)
        if len(seen) >= limit:
            break
    return kept


def _week_bucket(timestamp: datetime) -> str:
    iso_year, iso_week, _ = timestamp.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"