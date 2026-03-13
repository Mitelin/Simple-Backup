from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import os
import subprocess


@dataclass(frozen=True, slots=True)
class JobDefinition:
    name: str
    script_path: Path


@dataclass(frozen=True, slots=True)
class JobExecutionResult:
    job: JobDefinition
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    output_files: list[Path]


def discover_job_scripts(jobs_dir: Path) -> list[JobDefinition]:
    if not jobs_dir.exists():
        return []

    discovered: list[JobDefinition] = []
    for path in sorted(jobs_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if path.name.endswith(".disabled"):
            continue
        if path.suffix != ".sh":
            continue
        if not _is_executable(path):
            continue
        discovered.append(JobDefinition(name=path.stem, script_path=path.resolve()))

    return discovered


def execute_job_script(
    job: JobDefinition,
    *,
    device_name: str,
    timestamp: datetime,
    target_root: Path,
    timeout_seconds: int,
    job_work_dir: Path,
) -> JobExecutionResult:
    job_work_dir.mkdir(parents=True, exist_ok=True)
    before = _snapshot_files(job_work_dir)

    environment = os.environ.copy()
    environment.update(
        {
            "BACKUP_WORKDIR": str(job_work_dir),
            "BACKUP_TIMESTAMP": timestamp.strftime("%Y%m%dT%H%M%SZ"),
            "BACKUP_NAME": job.name,
            "BACKUP_DEVICE_NAME": device_name,
            "BACKUP_TARGET_ROOT": str(target_root),
            "BACKUP_SCRIPT_PATH": str(job.script_path),
        }
    )

    completed = subprocess.run(
        [str(job.script_path)],
        cwd=str(job.script_path.parent),
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    after = _snapshot_files(job_work_dir)

    return JobExecutionResult(
        job=job,
        success=completed.returncode == 0,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        output_files=sorted(after - before),
    )


def _snapshot_files(root: Path) -> set[Path]:
    if not root.exists():
        return set()
    return {path.resolve() for path in root.rglob("*") if path.is_file()}


def _is_executable(path: Path) -> bool:
    if os.name == "nt":
        return True
    return os.access(path, os.X_OK)