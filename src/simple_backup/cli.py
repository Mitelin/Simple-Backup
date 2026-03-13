from __future__ import annotations

import argparse
from pathlib import Path

from simple_backup.config import load_config
from simple_backup.orchestrator import BackupError, run_backup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple Backup CLI")
    parser.add_argument("--config", default="config.yaml", help="Path to YAML configuration file")

    subparsers = parser.add_subparsers(dest="command")
    run_parser = subparsers.add_parser("run", help="Create the final backup archive from the current run workspace")
    run_parser.add_argument("--config", dest="config", help="Path to YAML configuration file")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    command = args.command or "run"

    config = load_config(Path(args.config))

    if command == "run":
        try:
            result = run_backup(config)
        except Exception as error:
            print(str(error))
            return 1

        print(f"Final archive created: {result.archive_path}")
        print(f"Run log created: {result.log_file}")
        print(f"Jobs processed: {len(result.job_results)}")
        print(f"Archives deleted by retention: {len(result.retention.deleted)}")
        return 0

    parser.error(f"Unsupported command: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())