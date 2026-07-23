from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os
import shutil

from simple_backup.archive import build_archive_name, create_final_archive
from simple_backup.config import AppConfig
from simple_backup.jobs import JobDefinition, JobExecutionResult, discover_job_scripts, execute_job_script
from simple_backup.notifications import NotificationError, send_failure_email
from simple_backup.retention import ArchiveEntry, RetentionOutcome, apply_retention


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RunResult:
    """Result of a completed backup run.

    artifacts_dir points to the per-run staging artifacts directory that existed during
    the run. The parent run directory is cleaned up before the result is returned when
    cleanup succeeds, so this path may no longer exist by the time callers inspect it.
    """

    archive_path: Path
    log_file: Path
    artifacts_dir: Path
    job_results: list[JobExecutionResult]
    retention: RetentionOutcome


def run_backup(config: AppConfig) -> RunResult:
    timestamp = datetime.now(timezone.utc)
    run_id = timestamp.strftime("%Y%m%dT%H%M%SZ")
    log_file = config.runtime.log_dir / f"{run_id}.log"
    run_dir: Path | None = None
    artifacts_dir = config.runtime.work_dir / run_id / "artifacts"
    discovered_jobs: list[JobDefinition] = []
    job_results: list[JobExecutionResult] = []
    current_job: JobDefinition | None = None
    retention = RetentionOutcome(kept=[], deleted=[])
    archive_path = config.storage.target_root / build_archive_name(config.device.name, timestamp)
    result: RunResult | None = None
    backup_error: Exception | None = None
    cleanup_error: Exception | None = None

    try:
        _ensure_storage_ready(config.storage.target_root, config.storage.require_mount)
        config.runtime.work_dir.mkdir(parents=True, exist_ok=True)
        config.runtime.log_dir.mkdir(parents=True, exist_ok=True)

        run_dir = config.runtime.work_dir / run_id
        artifacts_dir = run_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        discovered_jobs = discover_job_scripts(config.runtime.jobs_dir)
        for job in discovered_jobs:
            current_job = job
            job_result = execute_job_script(
                job,
                device_name=config.device.name,
                timestamp=timestamp,
                target_root=config.storage.target_root,
                timeout_seconds=config.runtime.job_timeout_seconds,
                job_work_dir=artifacts_dir / job.name,
            )
            job_results.append(job_result)
            if not job_result.success:
                break

        overall_success = all(result.success for result in job_results) if job_results else True
        retention = apply_retention(
            config.storage.target_root,
            config.device.name,
            config.retention,
            protected_paths={archive_path.resolve()},
            pending_entries=[ArchiveEntry(path=archive_path, timestamp=timestamp)],
        )
        log_file.write_text(
            _render_run_log(config, run_id, discovered_jobs, job_results, overall_success, retention),
            encoding="utf-8",
        )

        archive_path = create_final_archive(
            artifacts_dir=artifacts_dir,
            log_file=log_file,
            archive_path=archive_path,
        )

        if not overall_success:
            failed_job = next((result for result in reversed(job_results) if not result.success), None)
            failed_script = failed_job.job.script_path.name if failed_job is not None else "unknown.sh"
            raise BackupError(
                f"Backup failed for script {failed_script} on {config.device.name} with log {log_file}"
            )

        result = RunResult(
            archive_path=archive_path,
            log_file=log_file,
            artifacts_dir=artifacts_dir,
            job_results=job_results,
            retention=retention,
        )
    except Exception as error:
        backup_error = error
    finally:
        if run_dir is not None and run_dir.exists():
            try:
                _cleanup_run_dir(config, run_dir)
            except Exception as error:
                cleanup_error = error

    if backup_error is not None:
        _record_run_failure(config, log_file, run_id, discovered_jobs, job_results, backup_error, cleanup_error)
        _send_failure_notification(config, timestamp, current_job, job_results, backup_error, cleanup_error)
        raise backup_error

    if cleanup_error is not None:
        cleanup_failure = BackupError(
            f"Backup cleanup failed for run {run_id} on {config.device.name}: {cleanup_error}"
        )
        _append_failure_details(log_file, cleanup_failure)
        _send_failure_notification(config, timestamp, current_job, job_results, cleanup_failure)
        raise cleanup_failure from cleanup_error

    if result is None:
        raise BackupError(f"Backup run {run_id} did not produce a result")

    return result


def _render_run_log(
    config: AppConfig,
    run_id: str,
    discovered_jobs: list,
    job_results: list[JobExecutionResult],
    overall_success: bool,
    retention: RetentionOutcome,
) -> str:
    lines = [
        f"timestamp={run_id}",
        f"device={config.device.name}",
        f"jobs_dir={config.runtime.jobs_dir}",
        f"target_root={config.storage.target_root}",
        f"discovered_jobs={len(discovered_jobs)}",
        f"successful_jobs={sum(1 for result in job_results if result.success)}",
        f"status={'success' if overall_success else 'failure'}",
        "",
    ]

    lines.append("retention_deleted:")
    if retention.deleted:
        for deleted_path in retention.deleted:
            lines.append(f"- {deleted_path.name}")
    else:
        lines.append("- none")
    lines.append("")

    if not job_results:
        lines.append("No jobs discovered.")
        return "\n".join(lines) + "\n"

    for result in job_results:
        lines.extend(
            [
                f"[job:{result.job.name}]",
                f"script={result.job.script_path}",
                f"success={str(result.success).lower()}",
                f"exit_code={result.exit_code}",
                "output_files:",
            ]
        )
        if result.output_files:
            for file_path in result.output_files:
                lines.append(f"- {file_path.name} ({file_path.stat().st_size} bytes)")
        else:
            lines.append("- none")

        lines.append("stdout:")
        lines.extend(_indent_block(result.stdout))
        lines.append("stderr:")
        lines.extend(_indent_block(result.stderr))
        lines.append("")

    return "\n".join(lines) + "\n"


def _indent_block(value: str) -> list[str]:
    if not value:
        return ["  <empty>"]
    return [f"  {line}" for line in value.rstrip().splitlines()]


def _record_run_failure(
    config: AppConfig,
    log_file: Path,
    run_id: str,
    discovered_jobs: list[JobDefinition],
    job_results: list[JobExecutionResult],
    error: Exception,
    cleanup_error: Exception | None = None,
) -> None:
    if log_file.exists():
        _append_failure_details(log_file, error, cleanup_error)
        return

    config.runtime.log_dir.mkdir(parents=True, exist_ok=True)
    log_lines = _render_run_log(
        config, run_id, discovered_jobs, job_results, overall_success=False, retention=RetentionOutcome(kept=[], deleted=[])
    ).rstrip().splitlines()
    log_lines.extend(["", "exception:", f"  {type(error).__name__}: {error}"])
    if cleanup_error is not None:
        log_lines.extend(["cleanup_exception:", f"  {type(cleanup_error).__name__}: {cleanup_error}"])
    log_file.write_text("\n".join(log_lines) + "\n", encoding="utf-8")


def _append_failure_details(log_file: Path, error: Exception, cleanup_error: Exception | None = None) -> None:
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write("\nexception:\n")
        handle.write(f"  {type(error).__name__}: {error}\n")
        if cleanup_error is not None:
            handle.write("cleanup_exception:\n")
            handle.write(f"  {type(cleanup_error).__name__}: {cleanup_error}\n")


def _send_failure_notification(
    config: AppConfig,
    timestamp: datetime,
    current_job: JobDefinition | None,
    job_results: list[JobExecutionResult],
    error: Exception,
    cleanup_error: Exception | None = None,
) -> None:
    failed_script = "unknown.sh"
    failed_result = next((result for result in reversed(job_results) if not result.success), None)
    if failed_result is not None:
        failed_script = failed_result.job.script_path.name
    elif current_job is not None:
        failed_script = current_job.script_path.name

    try:
        send_failure_email(
            config.notifications.email,
            device_name=config.device.name,
            timestamp=timestamp,
            script_name=failed_script,
            error_message=_format_failure_message(error, cleanup_error),
        )
    except NotificationError as notification_error:
        raise BackupError(f"{error} | Notification sending failed: {notification_error}") from error


def _format_failure_message(error: Exception, cleanup_error: Exception | None = None) -> str:
    message = str(error)
    if cleanup_error is not None:
        return f"{message} | Cleanup failed: {cleanup_error}"
    return message


def _cleanup_run_dir(config: AppConfig, run_dir: Path) -> None:
    if not run_dir.exists():
        return

    if not run_dir.is_dir():
        raise BackupError(f"Refusing to remove non-directory run path: {run_dir}")
    if run_dir.is_symlink():
        raise BackupError(f"Refusing to remove symlinked run directory: {run_dir}")

    runtime_root = config.runtime.work_dir.resolve(strict=True)
    run_parent = run_dir.parent.resolve(strict=True)
    resolved_run_dir = run_dir.resolve(strict=True)

    if _is_filesystem_root(resolved_run_dir):
        raise BackupError(f"Refusing to remove filesystem root: {resolved_run_dir}")
    if run_parent != runtime_root:
        raise BackupError(f"Refusing to remove path outside runtime.work_dir: {run_dir}")
    if resolved_run_dir.parent != runtime_root:
        raise BackupError(f"Refusing to remove unexpected resolved run path: {resolved_run_dir}")

    protected_paths = {
        runtime_root,
        config.storage.target_root.resolve(strict=False),
        config.runtime.jobs_dir.resolve(strict=False),
        config.runtime.log_dir.resolve(strict=False),
    }
    if resolved_run_dir in protected_paths:
        raise BackupError(f"Refusing to remove protected path: {resolved_run_dir}")

    shutil.rmtree(resolved_run_dir)


def _is_filesystem_root(path: Path) -> bool:
    return path == Path(path.anchor)


def _ensure_storage_ready(target_root: Path, require_mount: bool) -> None:
    if not require_mount:
        target_root.mkdir(parents=True, exist_ok=True)
        return

    mount_point = _find_non_root_mount(target_root)
    if mount_point is None:
        raise BackupError(f"Storage path is not on a mounted filesystem: {target_root}")

    target_root.mkdir(parents=True, exist_ok=True)


def _find_non_root_mount(path: Path) -> Path | None:
    candidate = path.resolve()
    for current in [candidate, *candidate.parents]:
        if not current.exists():
            continue
        if os.path.ismount(current) and str(current) != current.anchor:
            return current
    return None