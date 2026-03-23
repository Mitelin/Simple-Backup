from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
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
    target_root: Path,
    device_name: str,
    retention: RetentionConfig,
    protected_paths: set[Path] | None = None,
    pending_entries: list[ArchiveEntry] | None = None,
) -> RetentionOutcome:
    archives = _load_archives(target_root, device_name)
    selection_archives = sorted([*archives, *(pending_entries or [])], key=lambda item: item.timestamp, reverse=True)
    keep_paths = _select_keep_paths(selection_archives, retention)
    if protected_paths:
        keep_paths.update(path.resolve() for path in protected_paths)

    deleted: list[Path] = []
    for entry in archives:
        if entry.path in keep_paths:
            continue
        entry.path.unlink(missing_ok=True)
        deleted.append(entry.path)

    kept = [entry.path for entry in selection_archives if entry.path in keep_paths]
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
    boundary: datetime | None = None

    daily_keep, boundary = _keep_by_bucket(
        archives,
        retention.daily,
        boundary,
        lambda entry: entry.timestamp.date().isoformat(),
        lambda entry: _day_bucket_start(entry.timestamp),
    )
    keep.update(daily_keep)

    weekly_keep, boundary = _keep_by_bucket(
        archives,
        retention.weekly,
        boundary,
        lambda entry: _week_bucket(entry.timestamp),
        lambda entry: _week_bucket_start(entry.timestamp),
    )
    keep.update(weekly_keep)

    monthly_keep, boundary = _keep_by_bucket(
        archives,
        retention.monthly,
        boundary,
        lambda entry: entry.timestamp.strftime("%Y-%m"),
        lambda entry: _month_bucket_start(entry.timestamp),
    )
    keep.update(monthly_keep)

    if retention.yearly > 0:
        yearly_keep, _ = _keep_by_bucket(
            archives,
            retention.yearly,
            boundary,
            lambda entry: entry.timestamp.strftime("%Y"),
            lambda entry: _year_bucket_start(entry.timestamp),
        )
        keep.update(yearly_keep)
    return keep


def _keep_by_bucket(
    archives: list[ArchiveEntry],
    limit: int,
    boundary: datetime | None,
    bucket_key: Callable[[ArchiveEntry], str],
    bucket_start: Callable[[ArchiveEntry], datetime],
) -> tuple[set[Path], datetime | None]:
    if limit <= 0:
        return set(), boundary

    kept: set[Path] = set()
    seen: set[str] = set()
    next_boundary = boundary
    for entry in archives:
        if boundary is not None and entry.timestamp >= boundary:
            continue
        key = bucket_key(entry)
        if key in seen:
            continue
        seen.add(key)
        kept.add(entry.path)
        next_boundary = bucket_start(entry)
        if len(seen) >= limit:
            break
    return kept, next_boundary


def _day_bucket_start(timestamp: datetime) -> datetime:
    return datetime(timestamp.year, timestamp.month, timestamp.day, tzinfo=timezone.utc)


def _week_bucket(timestamp: datetime) -> str:
    iso_year, iso_week, _ = timestamp.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _week_bucket_start(timestamp: datetime) -> datetime:
    iso_year, iso_week, _ = timestamp.isocalendar()
    bucket_date = date.fromisocalendar(iso_year, iso_week, 1)
    return datetime(bucket_date.year, bucket_date.month, bucket_date.day, tzinfo=timezone.utc)


def _month_bucket_start(timestamp: datetime) -> datetime:
    return datetime(timestamp.year, timestamp.month, 1, tzinfo=timezone.utc)


def _year_bucket_start(timestamp: datetime) -> datetime:
    return datetime(timestamp.year, 1, 1, tzinfo=timezone.utc)