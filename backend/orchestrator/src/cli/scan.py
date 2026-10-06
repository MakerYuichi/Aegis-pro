"""AEGIS PRO CLI — `aegis scan <repo>`.

Runs a proactive scan against a local repo path and prints the
gated findings. Does not call the HTTP API — constructs
IncidentService directly, the same way Slack handlers and webhook
handlers do.

Usage:

    python -m src.cli.scan /path/to/repo
    python -m src.cli.scan /path/to/repo --top-n 50 --since-days 7

Exit codes:
    0  scan completed successfully (findings may or may not exist)
    1  scan failed (repo not found, config error)
    2  scan ran but SCANNER_MODE was set to an unsupported value
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="aegis scan",
        description=(
            "Run a proactive scan against a local repo path. Prints "
            "the two gated output streams: findings ready for review "
            "and candidates queued for the Investigator."
        ),
    )
    parser.add_argument(
        "repo",
        type=str,
        help="Path to the repo root.",
    )
    parser.add_argument(
        "--service-name",
        type=str,
        default=None,
        help="Service name for the incident. Defaults to the repo basename.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=None,
        help="Override SCANNER_TOP_N.",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=None,
        help="Override SCANNER_SINCE_DAYS.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full ScanResult as JSON instead of a summary.",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    from src.services.incident_service import IncidentService

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"error: not a directory: {repo}", file=sys.stderr)
        return 1

    service = IncidentService()
    try:
        result = await service.scan_repo(
            repo_path=str(repo),
            service_name=args.service_name,
            top_n=args.top_n,
            since_days=args.since_days,
        )
    except NotImplementedError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0

    counts = result["counts"]
    print(f"Scanned {result['files_scanned']} files in {result['repo']}")
    print(f"  report:        {counts['report']:3d}")
    print(f"  investigator:  {counts['investigator']:3d}")
    print(f"  dropped:       {counts['dropped_total']:3d}")
    print()

    if not result["scan_result"]["report"]:
        print("No confirmed findings.")
    else:
        print("=== Report ===")
        for o in result["scan_result"]["report"]:
            c = o["candidate"]
            print(f"  {o['score']:.3f}  {c['root_file']}:{c['root_line']}  "
                  f"{c['pattern']}  {c['symbol']!r}")
            print(f"           {o['reasoning']}")

    if result["scan_result"]["investigator_queue"]:
        print()
        print("=== Investigator queue ===")
        for o in result["scan_result"]["investigator_queue"][:10]:
            c = o["candidate"]
            print(f"  {o['score']:.3f}  {c['root_file']}:{c['root_line']}  "
                  f"{c['pattern']}  {c['symbol']!r}")

    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
