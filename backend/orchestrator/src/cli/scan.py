"""AEGIS PRO CLI — `aegis scan`.

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
        help=(
            "GitHub repo identifier. Accepts 'owner/repo', "
            "'https://github.com/owner/repo', or "
            "'git@github.com:owner/repo.git'."
        ),
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

    service = IncidentService()
    try:
        result = await service.scan_repo(
            repo_input=args.repo,
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

    verified = []
    verification_failed = []
    unverified = []
    refused = []
    for iid in result.get("incident_ids", []):
        incident = await service.get_incident(iid)
        if not incident:
            continue
        meta = incident.get("extra_metadata") or {}
        if isinstance(meta, str):
            import json as _json
            try:
                meta = _json.loads(meta)
            except Exception:
                meta = {}

        investigation = meta.get("investigation") or {}
        auto_fix = meta.get("auto_fix") or {}
        verification = meta.get("verification") or {}

        if auto_fix.get("diff") and verification.get("passed") is True:
            verified.append((iid, incident, auto_fix))
        elif auto_fix.get("diff"):
            # A fix was generated but the Verifier did not confirm it.
            # Common reasons: clone_failed, prefetch_failed_*,
            # diff_does_not_apply, tests_failed, no_verification_surface.
            verification_failed.append((iid, incident, auto_fix, verification))
        elif meta.get("unverified_finding"):
            unverified.append((iid, incident, meta["unverified_finding"]))
        elif investigation.get("status") == "refused":
            refused.append((iid, incident, investigation))

    if not verified and not verification_failed and not unverified:
        print("No findings.")
    else:
        if verified:
            print("=== Verified Findings ===")
            for iid, incident, auto_fix in verified:
                print(f"  {iid}  {incident.get('file_path')}:"
                      f"{incident.get('line_number')}  "
                      f"{incident.get('title')}")
                print(f"           Fix generated and verified.")
            print()

        if verification_failed:
            print("=== Verification Failed (fix generated, not confirmed) ===")
            for iid, incident, auto_fix, verification in verification_failed:
                print(f"  {iid}  {incident.get('file_path')}:"
                      f"{incident.get('line_number')}  "
                      f"{incident.get('title')}")
                print(f"           reason={verification.get('reason', 'unknown')}")
            print()

        if unverified:
            print("=== Needs Review (unverified) ===")
            for iid, incident, finding in unverified:
                print(f"  {iid}  {incident.get('file_path')}:"
                      f"{incident.get('line_number')}  "
                      f"{incident.get('title')}")
                # Two kinds of unverified findings:
                #   1. confirmed+reasoned_only — the Fixer gate wrote
                #      failure_mode; the finding was nearly proven
                #   2. could_not_determine — the Investigator refused
                #      without concluding false_positive; there's no
                #      failure_mode, only a reason
                failure_mode = finding.get("failure_mode")
                if failure_mode:
                    print(f"           {failure_mode}")
                    print(f"           No fix generated — probe did not "
                          f"reproduce. Recommend human review.")
                else:
                    reason = finding.get("reason") or "unknown"
                    print(f"           Investigator could not determine "
                          f"({reason})")
                    print(f"           No fix generated. Recommend "
                          f"human review.")
            print()

    if refused:
        print("=== Refused (not bugs) ===")
        for iid, incident, investigation in refused:
            reason = investigation.get("reason") or "unspecified"
            print(f"  {iid}  {incident.get('file_path')}:"
                  f"{incident.get('line_number')}  "
                  f"reason={reason}")

    if result["scan_result"]["investigator_queue"]:
        print()
        print("=== Investigator queue (not yet processed) ===")
        for o in result["scan_result"]["investigator_queue"][:10]:
            c = o["candidate"]
            print(f"  {o['score']:.3f}  {c['root_file']}:{c['root_line']}  "
                  f"{c['pattern']}  {c['symbol']!r}")
            
    incident_ids = result.get("incident_ids", [])
    if incident_ids:
        print()
        print(f"=== Incidents ({len(incident_ids)}) ===")
        for iid in incident_ids:
            print(f"  {iid}")

    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
