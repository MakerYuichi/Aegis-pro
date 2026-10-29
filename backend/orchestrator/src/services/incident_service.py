from sqlalchemy import text
from datetime import datetime
from pathlib import Path
import re
import uuid
import json
from loguru import logger

from src.database import get_db_session
from src.services.llm_service import LLMService
from src.services.rag_service import get_rag_service
from src.services.autofix_service import AutoFixService
from src.services.oncall_service import OnCallService
from src.services.kubernetes_service import KubernetesService
from src.services.factory import get_github_service
from src.services.alert_service import AlertService
from src.config import settings
from src.websocket import manager


def _read_git_origin(local_path: str) -> str | None:
    """
    Read `git config --get remote.origin.url` from a local checkout
    and normalize it to "owner/repo".

    Returns None when:
      - the path has no .git directory
      - git config fails (no remote configured, git not installed)
      - the URL is not a GitHub URL (self-hosted git, etc.)

    Used by the Provisioner to learn the GitHub identity of a
    local-path scan. The directory name ("requests-buggy") is not
    the GitHub identity — the .git/config tells the truth.
    """
    import subprocess

    p = Path(local_path)
    if not (p / ".git").exists():
        return None

    try:
        result = subprocess.run(
            ["git", "-C", str(p), "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None

    if result.returncode != 0:
        return None

    url = result.stdout.strip()
    if not url:
        return None

    # Normalize the four common shapes:
    #   https://github.com/psf/requests.git
    #   https://github.com/psf/requests
    #   git@github.com:psf/requests.git
    #   ssh://git@github.com/psf/requests.git
    url = re.sub(r"^git@github\.com:", "https://github.com/", url)
    url = re.sub(r"^ssh://git@github\.com/", "https://github.com/", url)
    url = re.sub(r"^https?://github\.com/", "", url)
    url = re.sub(r"^github\.com/", "", url)
    url = re.sub(r"\.git$", "", url)

    parts = url.split("/")
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if not owner or not repo:
        return None
    return f"{owner}/{repo}"



def merge_incident_metadata(existing_json, key: str, value) -> str:
    if not existing_json:
        metadata = {}
    else:
        if isinstance(existing_json, dict):
            metadata = existing_json
        else:
            try:
                metadata = json.loads(existing_json)
            except (TypeError, json.JSONDecodeError):
                metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}

    metadata[key] = value
    return json.dumps(metadata)

def _chain_links_to_dicts(chain_result) -> list[dict]:
    """Convert a ChainResult's links to the agent's dict shape.

    None-safe: a None chain_result (e.g. an outcome without a chain)
    returns an empty list. The agent handles an empty chain honestly.
    """
    if chain_result is None:
        return []
    links = getattr(chain_result, "chain", None) or []
    return [
        {
            "file": link.file,
            "line": link.line,
            "symbol": link.symbol,
            "reason": link.reason,
            "terminal_kind": getattr(link, "terminal_kind", "Unknown"),
            "branch_id": getattr(link, "branch_id", 0),
            "snippet": getattr(link, "snippet", ""),
        }
        for link in links
    ]

class IncidentService:
    def __init__(self):
        self.llm = LLMService()
        self.rag = get_rag_service()
        logger.info("✅ IncidentService initialized with RAG (singleton)")
    
    async def declare_incident(
        self,
        service_name: str,
        message: str,
        stack_trace: str = None,
        reported_by: str = None,
    ) -> dict:
        """Declare an incident from a stack trace or alert.

        Runs the Watcher, then hands the context to
        _run_pipeline_from_watcher, which owns the rest of the
        pipeline (Provisioner through Curator).

        Splitting the coordinator this way lets scan_repo feed a
        synthetic stack trace into the same pipeline without
        duplicating the post-Watcher body.
        """
        context = {
            "mode": "incident",
            "service_name": service_name,
            "message": message,
            "stack_trace": stack_trace,
            "reported_by": reported_by,
        }

        # Stage 1 — Watcher (Perceive)
        context.update(await self._stage_watcher(context))
        if context.get("error"):
            return context

        return await self._run_pipeline_from_watcher(context)

    async def _run_pipeline_from_watcher(self, context: dict) -> dict:
        """Run the incident pipeline from the Provisioner onward.

        Owns stages 2 through 6:

            Provisioner  → clone the repo
            Investigator → reason about the incident
            (persist)
            Fixer        → generate a diff
            Verifier     → sandbox the diff
            Communicator → report
            Curator      → learn

        Also owns the enrichment writes (github_context,
        related_prs, investigation, code_context, auto_fix,
        verification) and the clone cleanup.

        The caller is responsible for running the Watcher and for
        guaranteeing that context contains no error. `declare_incident`
        and `scan_single_candidate` both satisfy this — the Watcher
        runs first, and its error check happens before this method
        is called.

        Returns the public response dict from _build_response.
        """
        # Stage 2 — Provisioner (Clone once)
        #
        # The Provisioner creates one clone per incident when the
        # incident will need filesystem access (repo_name + file_path
        # both set). Every later stage that needs the clone reads
        # context["repo_workdir"]; none of them create or remove it.
        # The finally block below calls the Provisioner's cleanup to
        # remove the clone after all stages are done.
        context.update(await self._stage_provisioner(context))
        
        # Stage 2.5 — Prefetch (deps for Investigator's probe)
        context.update(await self._stage_prefetch(context))
        
        # Stage 3 — Investigator (Reason)
        context.update(await self._stage_investigator(context))

        # Persist the diagnosed incident before any enrichment. This is
        # the invariant that makes every record_* call below safe: the
        # row exists, so a downstream failure leaves a durable record of
        # what we knew at diagnosis time, not silence.
        await self._persist_diagnosed_incident(context["incident_data"])

        # --- Writes owned by the coordinator, sourced from each stage ---

        if context.get("investigation"):
            await self.record_investigation(
                context["incident_id"], context["investigation"]
            )

        # GitHub enrichment writes (github_context, related_prs) are
        # NOT here. They run at report time, gated on finding
        # status — see enrich_finding_for_report() below.

        # From here on, the pipeline may hold a cloned checkout in
        # context["repo_workdir"] (populated by the Investigator agent
        # when INVESTIGATOR_MODE=agent). Cleanup is deferred so the
        # Verifier can reuse the same checkout instead of cloning
        # again. One clone per incident, total.
        try:
            # Stage 3 — Fixer (Act)
            context.update(await self._stage_fixer(context))

            if context.get("code_context"):
                await self.record_code_context(
                    context["incident_id"], context["code_context"]
                )

            if context.get("auto_fix"):
                await self.record_auto_fix(
                    context["incident_id"], context["auto_fix"]
                )

            if context.get("unverified_finding"):
                await self.record_unverified_finding(
                    context["incident_id"], context["unverified_finding"]
                )

            # Stage 4 — Verifier (Verify). Gated by VERIFY_BEFORE_REPORT.
            context.update(await self._stage_verifier(context))

            if context.get("verification"):
                await self.record_verification(
                    context["incident_id"], context["verification"]
                )

            # Stage 5 — Communicator (Report). Side effects only.
            await self._stage_communicator(context)

            # Stage 6 — Curator (Learn). Side effects only.
            await self._stage_curator(context)

            return self._build_response(context)
        finally:
            from src.agents.provisioner import cleanup_repo
            # Skip cleanup for local-path scans. The caller handed us
            # a directory (context["scan_repo_path"] is set), we didn't
            # clone it, and we don't own it. cleanup_repo correctly
            # refuses to delete a non-sentinel path, but the refusal
            # logs a WARNING per incident. Skipping the call entirely
            # avoids the warning without hiding anything — the path
            # was never ours to clean up.
            if not context.get("scan_repo_path"):
                cleanup_repo(context.get("repo_workdir"))

    # ------------------------------------------------------------------
    # Scanner entry point — v1.0 Phase 2
    # ------------------------------------------------------------------

    async def scan_repo(
        self,
        repo_input: str,
        *,
        top_n: int | None = None,
        since_days: int | None = None,
        max_candidates: int | None = None,
        service_name: str | None = None,
    ) -> dict:
        """Run a proactive scan and feed candidates into the pipeline.

        This is the CLI's entry point. It is not an HTTP endpoint by
        design — the service layer is the shared code path, and
        declare_incident is already called directly by Slack handlers,
        webhook handlers, and AutoFixService callbacks. The CLI joins
        that list.

        Args:
            repo_input:    a GitHub repo identifier. Accepts any
                           shape parse_repo_input understands:
                           "owner/repo", "https://github.com/owner/repo",
                           "git@github.com:owner/repo.git", etc.
                           Normalized to "owner/repo" internally.
            top_n:         override SCANNER_TOP_N.
            since_days:    override SCANNER_SINCE_DAYS.
            max_candidates: override SCANNER_MAX_CANDIDATES.
            service_name:  explicit service name. When omitted,
                           resolved via resolve_scan_service —
                           existing services that already map to
                           this repo are reused; otherwise a new
                           service named "owner/repo" is created.

        Returns:
            {
              "repo": str,                 "owner/repo"
              "files_scanned": int,
              "counts": {"report": int, "investigator": int, ...},
              "scan_result": <ScanResult.to_dict()>,
              "incident_ids": [str, ...],
            }
        """
        from src.scanner.scan_runner import run_scan
        from src.config import settings
        from src.demo.repo_parser import parse_repo_input

        # Normalize the input. parse_repo_input is the single
        # source of truth for what a valid repo identifier is —
        # the demo path uses it, the scanner now uses it, and any
        # future caller should too. Writing a second parser would
        # drift from this one.
        parsed = parse_repo_input(repo_input)
        if not parsed.ok:
            raise ValueError(
                f"Unparseable repo input: {parsed.reason} — "
                f"{parsed.detail}. Supported formats include "
                f"'owner/repo' and 'https://github.com/owner/repo'."
            )
        owner_repo = f"{parsed.org}/{parsed.repo}"

        top_n = top_n if top_n is not None else settings.SCANNER_TOP_N
        since_days = since_days if since_days is not None else settings.SCANNER_SINCE_DAYS
        max_candidates = (
            max_candidates if max_candidates is not None
            else settings.SCANNER_MAX_CANDIDATES
        )

        if settings.SCANNER_MODE == "scheduled":
            # Deliberate fail-at-selection. Same discipline as
            # get_verifier(has_runner=True) raising instead of
            # returning a stub. A silent scheduled mode would look
            # like a working setting that does nothing.
            raise NotImplementedError(
                "SCANNER_MODE=scheduled is not implemented. Real scheduling "
                "(cron, worker queue, overlap handling) is v1.0 Phase 6. "
                "Set SCANNER_MODE=manual to run scans explicitly."
            )

        # Determine the working tree. Two paths:
        #
        #   (a) repo_input is a directory on disk. Scan it in place.
        #       Service name defaults to the directory basename.
        #
        #   (b) repo_input is a repo identifier. Clone it, scan the
        #       clone, clean up after. Service name defaults to
        #       owner/repo.
        #
        # The service resolution is inside each branch, not before
        # the branch. Before this fix, a local-path scan called
        # resolve_scan_service twice: once with the parsed
        # 'owner/repo' form of the path, once with the directory
        # basename. Two DB lookups, two service rows, one of them
        # named after the pytest tmpdir.
        from pathlib import Path
        from src.agents.repo_clone import clone_repo, cleanup_repo

        local_candidate = Path(repo_input).resolve()
        if local_candidate.is_dir():
            scan_workdir = str(local_candidate)
            needs_cleanup = False
            # Read .git/config to learn the true GitHub origin.
            # The directory basename ("requests-buggy") is not a
            # GitHub identifier; .git/config says "psf/requests".
            local_origin = _read_git_origin(scan_workdir)
            if service_name is None:
                effective_service = local_candidate.name
                await self.resolve_scan_service(
                    effective_service,
                    repo_name=local_origin,
                )
            else:
                effective_service = service_name
            if local_origin:
                logger.info(
                    f"scan_repo: scanning local path {scan_workdir} "
                    f"(service={effective_service}, origin={local_origin})"
                )
            else:
                logger.info(
                    f"scan_repo: scanning local path {scan_workdir} "
                    f"(service={effective_service}, no GitHub origin)"
                )
        else:
            if service_name is None:
                effective_service = await self.resolve_scan_service(
                    owner_repo,
                    repo_name=owner_repo,
                )
            else:
                effective_service = service_name
            scan_workdir, clone_error = await clone_repo(owner_repo)
            if not scan_workdir:
                raise RuntimeError(
                    f"Could not clone {owner_repo} for scanning: {clone_error}"
                )
            needs_cleanup = True


        try:
            result = run_scan(
                scan_workdir,
                top_n=top_n,
                since_days=since_days,
                max_candidates=max_candidates,
            )

            # Feed each report candidate through the pipeline. One
            # candidate → one incident, per the Phase 2 spec. The
            # synthetic stack trace carries the candidate's file
            # path *as it exists in the clone* (e.g.
            # backend/orchestrator/src/services/foo.py), which is
            # what the downstream Provisioner and Investigator
            # resolve against.
            incident_ids: list[str] = []

            budget = getattr(settings, "SCANNER_MAX_INCIDENTS", 10)
            processed = 0
            tiers = [("report", result.report),
                     ("queue", result.investigator_queue or [])]

            for tier_name, tier_candidates in tiers:
                for outcome in tier_candidates:
                    if processed >= budget:
                        logger.info(
                            f"scan_repo: reached SCANNER_MAX_INCIDENTS="
                            f"{budget}; {len(tier_candidates) - processed} "
                            f"candidates left unprocessed"
                        )
                        break
                    try:
                        incident = await self.scan_single_candidate(
                            outcome=outcome,
                            repo_path=scan_workdir,
                            service_name=effective_service,
                        )
                        if incident and incident.get("incident_id"):
                            incident_ids.append(incident["incident_id"])
                            processed += 1
                    except Exception as e:
                        logger.error(
                            f"scan_repo: pipeline failed for "
                            f"{outcome.candidate.root_file}:"
                            f"{outcome.candidate.root_line} "
                            f"(tier={tier_name}): {e}"
                        )

            # Already-fixed entries skip the pipeline entirely. No
            # Investigation, no Fixer, no Verifier — the prior
            # verification is the trust anchor. Just persist a report
            # row so the CLI and dashboard can show "we fixed this
            # and it's still fixed."
            #
            # Not counted against SCANNER_MAX_INCIDENTS because they
            # don't consume an LLM budget or a Docker run.
            already_fixed_ids: list[str] = []
            for outcome in (result.already_fixed or []):
                try:
                    incident_id = await self._declare_already_fixed_incident(
                        outcome=outcome,
                        repo_path=scan_workdir,
                        service_name=effective_service,
                    )
                    if incident_id:
                        already_fixed_ids.append(incident_id)
                        incident_ids.append(incident_id)
                except Exception as e:
                    logger.error(
                        f"scan_repo: failed to declare already_fixed "
                        f"for {outcome.candidate.root_file}:"
                        f"{outcome.candidate.root_line}: {e}"
                    )

            return {
                "repo": owner_repo,
                "files_scanned": result.files_scanned,
                "counts": result.to_dict()["counts"],
                "scan_result": result.to_dict(),
                "incident_ids": incident_ids,
                "already_fixed_ids": already_fixed_ids,
            }

        finally:
            if needs_cleanup:
                cleanup_repo(scan_workdir)

    async def scan_single_candidate(
        self,
        *,
        outcome,
        repo_path: str,
        service_name: str,
    ) -> dict:
        """Feed one scan candidate into the pipeline.

        Generates a synthetic stack trace from the candidate's root
        location, then runs the normal declare_incident pipeline
        starting at _stage_scanner. The synthetic trace is shaped
        to parse cleanly through _parse_stack_trace — the same
        format a real trace would take.

        The pipeline uses the candidate's repo_path as the incident's
        repo, so the Provisioner clones it, the Investigator reads
        from the clone, and the Fixer generates a diff against it.
        """
        candidate = outcome.candidate
        synthetic_trace = self._synthesize_stack_trace(candidate)

        # scan_repo calls scan_single_candidate, which calls
        # declare_incident with a flag that routes through
        # _stage_scanner. The scanner stage records the original
        # candidate in the context, and _build_response surfaces it.
        # The Provisioner sets repo_origin when it runs. Seed it here
        # so a hand-driven single-incident run (bypassing the
        # Provisioner) still gets enrichment. scan_repo passes the
        # same value it passes to resolve_scan_service.
        from pathlib import Path as _Path
        _local = _Path(repo_path).resolve()
        _seeded_origin = _read_git_origin(str(_local)) if _local.is_dir() else None

        context = {
            "mode": "scan",
            "service_name": service_name,
            "message": (
                f"Proactive scan finding: {candidate.pattern} at "
                f"{candidate.root_file}:{candidate.root_line}"
            ),
            "stack_trace": synthetic_trace,
            "reported_by": None,
            "scan_candidate": candidate.to_dict(),
            "scan_repo_path": repo_path,
            "repo_origin": _seeded_origin,
            "scan_outcome": {
                "destination": outcome.destination,
                "score": outcome.score,
                "reasoning": outcome.reasoning,
            },
            "chain": _chain_links_to_dicts(getattr(outcome, "chain", None)),
        }


        # Route through _stage_scanner, then the full pipeline.
        #
        # _stage_scanner calls _stage_watcher, which does service
        # lookup, stack-trace parsing, blast-radius computation, and
        # incident ID assignment — exactly as it does for a real
        # stack trace. Once _stage_scanner returns, the context has
        # the same shape declare_incident's context has after its
        # Watcher stage, so the same _run_pipeline_from_watcher runs
        # the rest.
        context.update(await self._stage_scanner(context))
        if context.get("error"):
            return context

        # Run the rest of the pipeline: Provisioner → Investigator →
        # Fixer → Verifier → Communicator → Curator.
        return await self._run_pipeline_from_watcher(context)
    
    async def _declare_already_fixed_incident(
        self,
        *,
        outcome,
        repo_path: str,
        service_name: str,
    ) -> str | None:
        """Persist a report-only incident for an already-fixed bug.

        Called from scan_repo for every ScanOutcome with
        destination="already_fixed". The pipeline skips investigation
        for these — the .aegis/fixes.json record (written when the fix
        was originally verified) is the trust anchor.

        Returns the incident_id on success, or None on failure.
        Failure is logged but does not break the scan — one bad
        already-fixed record shouldn't kill the report.
        """
        fix = outcome.previous_fix or {}
        candidate = outcome.candidate
        provenance = (candidate.metadata or {}).get("aegis_provenance") or {}
        original_id = provenance.get("original_incident_id") or fix.get("incident_id") or "unknown"

        incident_id = f"INC-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        extra_metadata = json.dumps({
            "already_fixed": True,
            "aegis_provenance": {
                "original_incident_id": original_id,
                "verified_at": provenance.get("verified_at") or fix.get("verified_at"),
                "verification_reason": provenance.get("verification_reason") or fix.get("verification_reason"),
                "base_commit": provenance.get("base_commit") or fix.get("base_commit"),
                "probe_code": provenance.get("probe_code") or fix.get("probe_code"),
                "probe_flags": provenance.get("probe_flags") or fix.get("probe_flags") or [],
            },
        })

        try:
            async with get_db_session() as session:
                # Fetch service dependencies for blast-radius parity
                # with normal incidents. Light — one query.
                svc = await self.get_service(service_name)
                affected = json.dumps([service_name])

                await session.execute(
                    text("""
                        INSERT INTO incidents (
                            incident_id, service_name, severity, status, title, description,
                            stack_trace, exception_type, file_path, line_number,
                            root_cause, suggested_fix, rollback_command, confidence_score,
                            declared_at, extra_metadata, affected_services
                        ) VALUES (
                            :incident_id, :service_name, :severity, :status, :title, :description,
                            :stack_trace, :exception_type, :file_path, :line_number,
                            :root_cause, :suggested_fix, :rollback_command, :confidence_score,
                            :declared_at, :extra_metadata, :affected_services
                        )
                    """),
                    {
                        "incident_id": incident_id,
                        "service_name": service_name,
                        "severity": "P3",
                        "status": "already_fixed",
                        "title": f"Previously fixed: {candidate.pattern} at {candidate.root_file}:{candidate.root_line}",
                        "description": (
                            f"AEGIS PRO previously found and fixed this bug "
                            f"(incident {original_id}, verified "
                            f"{provenance.get('verified_at') or 'unknown'}). "
                            f"The fix is still applied to the working tree."
                        ),
                        "stack_trace": (
                            f"Prior verification: {provenance.get('verification_reason') or 'unknown'}"
                        ),
                        "exception_type": None,
                        "file_path": candidate.root_file,
                        "line_number": candidate.root_line,
                        "root_cause": "Previously diagnosed and fixed by AEGIS PRO",
                        "suggested_fix": fix.get("fix_diff") or "",
                        "rollback_command": "",
                        "confidence_score": 1.0,
                        "declared_at": datetime.utcnow(),
                        "extra_metadata": extra_metadata,
                        "affected_services": affected,
                    },
                )
                await session.commit()
                logger.info(
                    f"✅ Already-fixed incident {incident_id} persisted "
                    f"(from {original_id} at "
                    f"{candidate.root_file}:{candidate.root_line})"
                )
                return incident_id
        except Exception as e:
            logger.error(
                f"Error persisting already_fixed incident for "
                f"{candidate.root_file}:{candidate.root_line}: {e}"
            )
            return None

    @staticmethod
    def _synthesize_stack_trace(candidate) -> str:
        """Build a synthetic stack trace from a scan candidate.

        The format is deliberately shaped to parse cleanly through
        the existing _parse_stack_trace regexes. It mimics a real
        Python traceback:

            Traceback (most recent call last):
              File "path/to/file.py", line N, in <module>
            <exception_type>: <synthetic message>

        The exception type is chosen based on the pattern:
            unchecked_optional_attr / unchecked_dict_access
                → AttributeError (or KeyError for subscript)
            bare_except / mutable_default_arg
                → ValueError
            comparison_with_none_identity
                → TypeError

        The line number comes from the candidate's root_line. The
        file path is the candidate's root_file. The message names
        the symbol so the Fixer's diagnosis block has something to
        work with.
        """
        exception_map = {
            "unchecked_optional_attr": "AttributeError",
            "unchecked_dict_access": "KeyError",
            "bare_except": "ValueError",
            "mutable_default_arg": "ValueError",
            "comparison_with_none_identity": "TypeError",
        }
        exc = exception_map.get(candidate.pattern, "RuntimeError")

        return (
            f"Traceback (most recent call last):\n"
            f'  File "{candidate.root_file}", line {candidate.root_line}, '
            f"in <module>\n"
            f"{exc}: scan candidate '{candidate.symbol}' "
            f"({candidate.pattern})"
        )

    # ------------------------------------------------------------------
    # Stage 0 — Scanner (Proactive)
    # ------------------------------------------------------------------

    async def _stage_scanner(self, context: dict) -> dict:
        """Scanner stage. Turns a scan candidate into pipeline input.

        This stage runs *instead of* the initial call site in
        declare_incident when the context contains a scan_candidate.
        It does one thing: ensure the context has a synthetic
        stack_trace and a scan_repo_path, then hands the context to
        _stage_watcher.

        _stage_watcher is unchanged. It parses the synthetic trace
        exactly as it parses a real one. The scan stage only exists
        to produce the input _stage_watcher already consumes.
        """
        candidate = context.get("scan_candidate")
        if not candidate:
            return context

        # Ensure the stack trace is present. scan_single_candidate
        # already built it, but the guard is cheap and covers a caller
        # that only sets the candidate.
        if not context.get("stack_trace"):
            from src.scanner.candidate import ScanCandidate
            c = ScanCandidate(
                root_file=candidate["root_file"],
                root_line=candidate["root_line"],
                symbol=candidate["symbol"],
                pattern=candidate["pattern"],
            )
            context["stack_trace"] = self._synthesize_stack_trace(c)

        # Now hand off to the existing Watcher. Everything downstream
        # sees a normal incident.
        return await self._stage_watcher(context)
    
    # ------------------------------------------------------------------
    # Stage 1 — Watcher (Perceive)
    # ------------------------------------------------------------------

    async def _stage_watcher(self, context: dict) -> dict:
        """
        Perceive. Look up the service, parse the stack trace, compute
        blast radius, assign an incident ID.

        Returns:
            On success: {incident_id, service, stack_analysis, blast_radius}
            On service-not-found: {error, available_services}
        """
        service_name = context["service_name"]
        stack_trace = context.get("stack_trace")
        incident_id = f"INC-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        logger.info(f"🚨 Declaring incident: {incident_id} for service: {service_name}")

        service = await self.get_service(service_name)
        if not service:
            return {
                "error": f"Service '{service_name}' not found",
                "available_services": await self.list_services(),
            }

        stack_analysis = None
        if stack_trace:
            stack_analysis = self._parse_stack_trace(stack_trace)

        blast_radius = await self.calculate_blast_radius(
            service_name=service_name,
            dependencies=service.get("dependencies", []),
        )

        return {
            "incident_id": incident_id,
            "service": service,
            "stack_analysis": stack_analysis,
            "blast_radius": blast_radius,
        }
        
    # ------------------------------------------------------------------
    # Stage 2 — Provisioner (Clone once)
    # ------------------------------------------------------------------

    async def _stage_provisioner(self, context: dict) -> dict:
        """
        Provision. Clone the incident's repo into
        context["repo_workdir"] when the incident will need filesystem
        access.

        Two paths:

        1. Local-path scan (context["scan_repo_path"] is set and
           points at a directory). The working tree is already on
           disk. There is nothing to clone. Set repo_workdir to the
           scan path directly. The cleanup is a no-op — the path
           belongs to the caller.

        2. Remote repo (no scan_repo_path, or it's not a directory).
           Clone via the Provisioner as before.

        The distinction matters because scan_repo for local paths
        sets service_name to the directory basename (e.g.
        "requests-buggy"), which is not a valid GitHub repo name.
        Without this branch, provision_clone tries to clone it as a
        GitHub URL, fails with invalid_repo_name, and every
        downstream stage that needs filesystem access degrades —
        including the Investigator, whose read_file tool falls back
        to basename search and reads the wrong file entirely.

        Returns:
            {"repo_workdir": "<path>"} on success.
            {} when no clone is needed (no repo, no stack-trace file
            path, or the clone failed). An empty return is not an
            error — downstream stages detect the missing clone and
            degrade honestly.
        """
        from pathlib import Path

        # Local-path scan: reuse the working tree the caller
        # already handed us. Read .git/config to learn the GitHub
        # origin so downstream enrichment can target the right
        # repo — the directory basename ("requests-buggy") is not
        # a GitHub identity.
        scan_path = context.get("scan_repo_path")
        if scan_path:
            resolved = Path(scan_path)
            if resolved.is_dir():
                origin = _read_git_origin(str(resolved))
                if origin:
                    logger.info(
                        f"📦 Provisioner: using local scan path "
                        f"{resolved} (no clone; origin={origin})"
                    )
                else:
                    logger.info(
                        f"📦 Provisioner: using local scan path "
                        f"{resolved} (no clone; no GitHub origin in .git/config)"
                    )
                return {
                    "repo_workdir": str(resolved),
                    "repo_origin": origin,
                }

        # Remote repo: clone as before. The clone succeeding IS the
        # verification that the repo exists — if it doesn't, we get
        # here with no workdir and downstream stages degrade
        # honestly. repo_origin is the owner/repo we cloned.
        from src.agents.provisioner import provision_clone

        result = await provision_clone(context)
        if result.get("repo_workdir"):
            service = context.get("service") or {}
            origin = service.get("repo_name")
            result["repo_origin"] = origin
        return result
    
    # ------------------------------------------------------------------
    # Stage 2.5 — Prefetch (dependencies for probe + verifier)
    # ------------------------------------------------------------------

    async def _stage_prefetch(self, context: dict) -> dict:
        """
        Prefetch the repo's dependencies into a cache before the
        Investigator runs. The Investigator's probe tool needs the
        cache to install real deps; without it, `import <module>`
        probes fail on ModuleNotFoundError and the agent falls back
        to toy reproductions that don't test the tree's code.

        The Verifier reuses this same cache — no second prefetch.

        Returns:
            {
              "prefetch_cache_host_path": "<host path>",
              "prefetch_manifest_relative": "<manifest rel path>",
            }
            or {} when no manifest exists or prefetch fails. Downstream
            stages degrade honestly (probe tool runs without deps;
            verifier does the same).
        """
        from pathlib import Path
        from src.agents.prefetch.manifest_finder import find_manifest
        from src.agents.prefetch.runner import (
            run_prefetch,
            run_prefetch_with_build_on_miss,
            PrefetchError,
        )

        tree_root_str = context.get("repo_workdir")
        if not tree_root_str:
            return {}

        tree_root = Path(tree_root_str)
        if not tree_root.is_dir():
            return {}

        language = (
            context.get("language")
            or self._infer_language(
                context.get("stack_analysis") or {},
                context["service_name"],
            )
        )

        manifest_ref = find_manifest(tree_root, language)
        if manifest_ref is None:
            logger.info(
                f"Prefetch: no dependency manifest in "
                f"{context['service_name']}; skipping"
            )
            return {}

        manifest_path = tree_root / manifest_ref.path

        try:
            if settings.BUILD_ON_MISS_ENABLED:
                result = await run_prefetch_with_build_on_miss(
                    manifest_container_path=manifest_path,
                    entrypoint_container_path=Path(
                        "/app/scripts/prefetch_entrypoint.py"
                    ),
                    cache_container_path=Path(
                        settings.VERIFIER_PIP_CACHE_CONTAINER_DIR
                    ),
                    cache_host_path=Path(
                        settings.VERIFIER_PIP_CACHE_HOST_DIR
                    ),
                    mirror_container_path=Path(settings.MIRROR_CONTAINER_DIR),
                    mirror_host_path=Path(settings.MIRROR_HOST_DIR),
                    build_entrypoint_container_path=Path(
                        "/app/scripts/build_entrypoint.py"
                    ),
                    manifest_kind=manifest_ref.kind,
                )
            else:
                result = await run_prefetch(
                    manifest_container_path=manifest_path,
                    entrypoint_container_path=Path(
                        "/app/scripts/prefetch_entrypoint.py"
                    ),
                    cache_container_path=Path(
                        settings.VERIFIER_PIP_CACHE_CONTAINER_DIR
                    ),
                    cache_host_path=Path(
                        settings.VERIFIER_PIP_CACHE_HOST_DIR
                    ),
                    manifest_kind=manifest_ref.kind,
                )

            logger.info(
                f"Prefetch: cache ready for "
                f"{context['service_name']} at {result.cache_host_path}"
            )
            return {
                "prefetch_cache_host_path": str(result.cache_host_path),
                "prefetch_manifest_relative": manifest_ref.path.as_posix(),
            }
        except PrefetchError as e:
            logger.warning(
                f"Prefetch: failed for {context['service_name']}: "
                f"{e.reason}: {e.detail}"
            )
            return {"prefetch_error": f"{e.reason}: {e.detail}"}

    # ------------------------------------------------------------------
    # Stage 3 — Investigator (Reason)
    # ------------------------------------------------------------------

    async def _stage_investigator(self, context: dict) -> dict:
        """
        Reason. Pull RAG context, run the LLM analysis, fetch GitHub
        context (recent PRs, blame) and related PRs. Does not write
        anything — the coordinator persists what this stage returns.

        Returns:
            {analysis, rag_used, incident_data, github_context, related_prs}
        """
        service_name = context["service_name"]
        message = context["message"]
        reported_by = context.get("reported_by")
        service = context["service"]
        stack_analysis = context.get("stack_analysis")
        blast_radius = context["blast_radius"]
        incident_id = context["incident_id"]

        rag_context = await self.rag.generate_context_prompt(message)
        rag_used = bool(rag_context)
        if rag_used:
            logger.info("📚 Found similar past incidents for context!")
        else:
            logger.info("📚 No similar past incidents found yet")
            
        # Curator few-shot: retrieve past fix outcomes for the same
        # service (falling back to same repo) and inject them as
        # examples. Gated by CURATOR_FEW_SHOT until the loop has been
        # proven in production.
        fix_outcomes_context = ""
        if settings.CURATOR_FEW_SHOT:
            try:
                outcomes = await self.rag.search_similar_outcomes(
                    query=message,
                    service_name=service_name,
                    repo_name=service.get("repo_name"),
                    limit=settings.CURATOR_MAX_OUTCOMES,
                )
                if outcomes:
                    fix_outcomes_context = self.rag.format_outcomes_for_prompt(
                        outcomes
                    )
                    logger.info(
                        f"🎯 Curator: injecting {len(outcomes)} past "
                        f"outcomes as few-shot examples"
                    )
            except Exception as e:
                # Log and continue — a retrieval failure must not break
                # the incident pipeline.
                logger.error(f"Curator few-shot retrieval failed: {e}")
        
        analysis = await self.llm.analyze_incident(
            service_name=service_name,
            message=message,
            stack_analysis=stack_analysis,
            blast_radius=blast_radius,
            rag_context=rag_context,
            fix_outcomes_context=fix_outcomes_context,
        )

        incident_data = {
            "incident_id": incident_id,
            "service_name": service_name,
            "severity": analysis.get("severity", "P1"),
            "status": "active",
            "title": analysis.get("title", f"{service_name} incident"),
            "description": message,
            "stack_trace": context.get("stack_trace"),
            "exception_type": stack_analysis.get("exception_type") if stack_analysis else None,
            "file_path": stack_analysis.get("file_path") if stack_analysis else None,
            "line_number": stack_analysis.get("line_number") if stack_analysis else None,
            "root_cause": analysis.get("root_cause", ""),
            "suggested_fix": analysis.get("suggested_fix", ""),
            "rollback_command": analysis.get("rollback_command", ""),
            "confidence_score": analysis.get("confidence", 0.7),
            "declared_at": datetime.utcnow(),
            "extra_metadata": json.dumps({
                "rag_context_used": rag_used,
                "reported_by": reported_by if reported_by else None,
            }),
            "affected_services": json.dumps(blast_radius.get("affected", [])),
        }

        # GitHub enrichment (blame, recent PRs, related PRs) has
        # moved to Fix B — it runs at report time, only for
        # findings a human will actually read (Verified,
        # Verification Failed, Needs Review). Refused and
        # already-fixed findings don't pay the cost. See
        # enrich_finding_for_report() below.
        result: dict = {
            "analysis": analysis,
            "rag_used": rag_used,
            "incident_data": incident_data,
        }
        
        if settings.INVESTIGATOR_MODE == "agent":
            # Pull the scan candidate's symbol and Pyright message
            # out of the pipeline context, if present. In incident
            # mode these are absent (empty defaults). In scan mode
            # the pipeline sets context["scan_candidate"] with the
            # candidate dict, and the top-level context carries the
            # chain.
            scan_candidate = context.get("scan_candidate") or {}
            symbol = scan_candidate.get("symbol") or ""
            pyright_message = ""
            # The PatternMatch metadata lives on the ScanCandidate
            # the scanner produced. For Pyright findings this carries
            # the analyzer message. Fetch it defensively — older
            # candidates may not have metadata.
            scan_meta = scan_candidate.get("metadata") or {}
            if isinstance(scan_meta, dict):
                pyright_message = scan_meta.get("pyright_message") or ""

            investigation = await self._run_investigator_agent(
                context=context,
                service_name=service_name,
                message=message,
                repo=service.get("repo_name") or service_name,
                stack_trace=context.get("stack_trace"),
                stack_analysis=stack_analysis,
                github_context=None,
                related_prs=None,
                rag_context=rag_context,
                fix_outcomes=fix_outcomes_context,
                blast_radius=blast_radius,
                mode=context.get("mode", "incident"),
                chain=context.get("chain"),
                symbol=symbol,
                pyright_message=pyright_message,
            )

            result["investigation"] = investigation.to_dict()

            if investigation.status == "diagnosed":
                result["null_source"] = investigation.null_source
                logger.info(
                    f"🔬 Investigator diagnosed null source: "
                    f"{investigation.null_source} "
                    f"(confidence {investigation.confidence:.2f}, "
                    f"{investigation.iterations} iterations)"
                )
            elif investigation.status == "confirmed":
                result["fix_location"] = investigation.fix_location
                result["failure_mode"] = investigation.failure_mode
                logger.info(
                    f"🔬 Investigator confirmed finding: "
                    f"{investigation.failure_mode} "
                    f"(fix_location={investigation.fix_location}, "
                    f"confirmation={investigation.confirmation}, "
                    f"confidence {investigation.confidence:.2f})"
                )
            elif investigation.status == "unverified":
                # The Investigator looked, couldn't decide, and
                # isn't claiming the finding is false positive.
                # Route it to the unverified bucket so the CLI and
                # dashboard show it under "Needs Review" — not
                # alongside the confident false positives.
                result["unverified_finding"] = investigation.to_dict()
                result["auto_fix_skipped_reason"] = (
                    "investigator_unverified"
                )
                logger.info(
                    f"🔬 Investigator returned unverified "
                    f"(reason={investigation.reason!r}); "
                    f"no auto-fix, needs human review"
                )
            else:
                result["auto_fix_skipped_reason"] = investigation.status
                logger.info(
                    f"🔬 Investigator returned {investigation.status}; "
                    f"auto-fix will be skipped"
                )


        return result
        
    async def _run_investigator_agent(
        self,
        *,
        context: dict,
        service_name: str,
        message: str,
        repo: str,
        stack_trace: str | None,
        stack_analysis: dict | None,
        github_context: dict | None,
        related_prs: list | None,
        rag_context: str,
        fix_outcomes: str,
        blast_radius: dict,
        mode: str = "incident",
        chain: list[dict] | None = None,
        symbol: str = "",
        pyright_message: str = "",
    ):
        """
        Build an InvestigatorContext, run the agent, return the
        InvestigationResult.

        The clone is created by the Provisioner stage and removed by
        the coordinator's finally. This method reads
        context["repo_workdir"] but never creates or removes it.

        When the clone is absent (no repo, no file path, or the clone
        failed), the agent's repo_root is the empty string and every
        tool returns repo_not_found. The agent refuses. That's the
        honest outcome — better than inventing a path.

        Never raises — any exception inside the agent becomes a
        result with status="decision_failed" and the exception is
        logged. The pipeline must not be broken by the agent.
        """
        from src.agents.investigator import InvestigatorAgent
        from src.agents.investigator_context import build_investigator_context
        from src.agents.investigator_models import (
            STATUS_DECISION_FAILED,
            InvestigationResult,
        )

        try:
            repo_workdir = context.get("repo_workdir")

            ctx = build_investigator_context(
                mode=mode,
                service_name=service_name,
                message=message,
                repo=repo,
                stack_trace=stack_trace,
                stack_analysis=stack_analysis,
                github_context=github_context,
                related_prs=related_prs,
                rag_context=rag_context,
                fix_outcomes=fix_outcomes,
                blast_radius=blast_radius,
                chain=chain,
                symbol=symbol,
                pyright_message=pyright_message,
            )
            agent = InvestigatorAgent(
                llm_service=self.llm,
                repo_root=repo_workdir or "",
                cache_host_path=context.get("prefetch_cache_host_path"),
                manifest_relative_path=context.get("prefetch_manifest_relative"),
            )
            return await agent.investigate(
                ctx,
                max_iterations=settings.INVESTIGATOR_MAX_ITERATIONS,
                time_budget_seconds=settings.INVESTIGATOR_TIME_BUDGET_SECONDS,
            )
        except Exception as e:
            logger.error(f"Investigator agent error: {e}")
            return InvestigationResult(
                status=STATUS_DECISION_FAILED,
                thought=f"agent_exception: {e}",
            )
            
    def _read_code_context_from_clone(
        self,
        repo_workdir: str,
        file_path: str,
        line_number: int,
        context_lines: int = 30,
    ) -> dict | None:
        """
        Read the code around the failing line from a local clone.

        Used by the Fixer when the Investigator has already cloned the
        repo. Returns the same shape GitHubService.get_file_content
        returns, so downstream consumers (the Fixer prompt) don't care
        where the content came from.

        Path resolution: the stack trace's file_path is often relative
        to a build directory (e.g. backend/orchestrator/) rather than
        the repo root. If the exact path doesn't exist, search for a
        file with the same basename elsewhere in the clone. That's the
        same logic the Investigator's read_file tool uses.

        Returns None when the clone is missing, the file isn't found,
        or reading fails. The caller treats None as "no code context"
        and falls back to the GitHub API.
        """
        from pathlib import Path

        if not repo_workdir:
            return None

        repo_path = Path(repo_workdir)
        if not repo_path.is_dir():
            return None

        candidate = (repo_path / file_path).resolve()
        try:
            candidate.relative_to(repo_path.resolve())
        except ValueError:
            return None

        if not candidate.is_file():
            # Search by basename for the monorepo case.
            basename = Path(file_path).name
            match = None
            for found in repo_path.rglob(basename):
                if found.is_file() and any(
                    part not in {
                        ".git", "node_modules", "venv", ".venv",
                        "dist", "build", "__pycache__",
                    }
                    for part in found.parts
                ):
                    match = found
                    break
            if match is None:
                return None
            candidate = match

        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning(f"Fixer: could not read {candidate}: {e}")
            return None

        lines = text.splitlines()
        total = len(lines)

        start = max(0, line_number - context_lines - 1)
        end = min(total, line_number + context_lines)

        code_snippet = []
        raw_snippet = []
        for i in range(start, end):
            line_num = i + 1
            marker = ">>> " if i == line_number - 1 else "    "
            code_snippet.append(f"{line_num:4d} {marker}{lines[i]}")
            raw_snippet.append(lines[i])

        return {
            "file_path": file_path,
            "line_number": line_number,
            "total_lines": total,
            "code_snippet": "\n".join(code_snippet),
            "raw_snippet": "\n".join(raw_snippet),
            "full_file": "\n".join(lines) if total < 100 else None,
        }
        
        
    def _build_diagnosis_block(self, context: dict) -> str:
        """
        Render the Investigator's diagnosis as a prompt fragment for
        the Fixer.

        Two diagnosis kinds, matching the two pipeline modes:

          - incident mode: `null_source` is set. The block describes
            the null-dereference expression the diff must address.
          - scan mode: `failure_mode` is set (and often
            `fix_location`). The block describes the failure mode
            the diff must resolve, without naming a specific symbol
            unless the failure mode itself names one.

        Returns an empty string when there is no diagnosis (stage
        mode, or the agent refused). An empty block leaves the
        Fixer's prompt unchanged.

        The block is deliberately prose, not JSON. The Fixer is an
        LLM; prose is what it reasons over. Structured output from
        the Investigator was already used at the pipeline level —
        by the time we're building the fix prompt, the structured
        part is done.
        """
        null_source = context.get("null_source")
        failure_mode = context.get("failure_mode")

        if null_source:
            return (
                f"\nThe exception is a null dereference. The Investigator "
                f"has identified the null source as:\n\n"
                f"    {null_source}\n\n"
                f"Your diff MUST address this exact expression. Either "
                f"guard its use, add a null check where it's assigned, or "
                f"replace it with a safe alternative. Do NOT modify any "
                f"other line in the file — a diff that touches unrelated "
                f"code will fail verification.\n\n"
                f"Note: the stack trace's line number may be stale. The "
                f"line that failed when the alert fired may not be the "
                f"line that contains the null source now. Fix the code "
                f"where {null_source} is assigned or used, not where the "
                f"stack trace points.\n\n"
                f"## Making the fix COMPLETE and APPLICABLE\n\n"
                f"Two rules for a diff that will be accepted:\n\n"
                f"  1. COMPLETENESS. If the value {null_source} can be "
                f"None, check every use of it within the same function. "
                f"A diff that guards only the line the stack trace names "
                f"will pass the immediate check and FAIL the verifier's "
                f"re-run if the same value is used elsewhere. Guard every "
                f"unguarded use in one diff.\n\n"
                f"  2. APPLICABILITY. The '-' lines and ' ' (context) "
                f"lines in your diff MUST be copied byte-for-byte from "
                f"the 'Current Code' block. Do not retype from memory. "
                f"Do not re-indent. Do not strip trailing whitespace. "
                f"Copy the exact characters, then prefix each copied "
                f"line with '-' (for removed) or ' ' (for context). If "
                f"your hunk's context does not match the file, git apply "
                f"will reject the entire patch and the fix will fail "
                f"with reason=diff_does_not_apply — no tests will run, "
                f"the pipeline will mark it as unverifiable, and a "
                f"human has to fix it. This is the single most common "
                f"reason LLM-generated diffs fail.\n\n"
                f"   For each hunk in your diff:\n"
                f"     - Copy 2-3 lines of context before the change "
                f"       from the Current Code block, verbatim.\n"
                f"     - Copy the line being changed, verbatim, prefix "
                f"       with '-'.\n"
                f"     - Write the new line, prefix with '+'.\n"
                f"     - Copy 2-3 lines of context after the change, "
                f"       verbatim.\n"
                f"     - Use the correct hunk header: "
                f"@@ -<old_start>,<old_count> +<new_start>,<new_count> @@\n"
                f"       with the actual line numbers from the Current "
                f"Code block (the file has line numbers on the left)."
            )

        if failure_mode:
            return (
                f"\nThe Investigator has confirmed the following "
                f"failure mode:\n\n"
                f"    {failure_mode}\n\n"
                f"Your diff MUST fix this exact failure mode. "
                f"Identify the specific line in the code below that "
                f"produces it, and patch only that line. Do NOT add "
                f"defensive checks to unrelated lines — a nearby "
                f"`if X:` or `if not X.startswith(...)` pattern is "
                f"NOT the bug unless the failure mode above names it. "
                f"The code window shows ±30 lines around the crash "
                f"site; only one line in that window is the actual "
                f"defect. Choose it from the failure mode, not from "
                f"what looks like it needs a guard.\n\n"
                f"If the failure mode names a specific symbol (e.g. "
                f"`__doc__`), the fix MUST target the line that uses "
                f"or assigns that symbol — not a line that merely "
                f"appears in the same window.\n\n"
                f"## Making the fix COMPLETE, not just local\n\n"
                f"After you identify the crash line, check whether "
                f"the SAME value is used without a guard on any other "
                f"line within the same function. If the failure mode "
                f"is 'attribute access on a possibly-None value X', "
                f"and X is dereferenced at line 470 AND at line 480, "
                f"you must guard BOTH uses. A diff that fixes only the "
                f"line the probe crashed on will pass the immediate "
                f"check and FAIL the verifier's re-run — because the "
                f"second use still crashes. The verifier re-runs the "
                f"same probe that reproduced the bug; if that probe "
                f"exercises any unguarded use of X, it will fail "
                f"after your fix and the fix is rejected.\n\n"
                f"Two rules for COMPLETE fixes:\n\n"
                f"  1. If the failure mode names a specific symbol X "
                f"and the crash is `X.attr`, look for every other "
                f"`X.attr` or `X[i]` or `X()` or `X + ...` in the "
                f"same function body. Guard all of them. A common "
                f"case: `result['domain'].startswith('.')` crashes "
                f"and `result['domain'].lower()` two lines down "
                f"crashes next. Fix both in one diff.\n\n"
                f"  2. If the function accepts a parameter that can be "
                f"None (per the failure mode), the fix can be a guard "
                f"at the top of the function that early-returns or "
                f"substitutes a default. That is often the smallest "
                f"correct diff. Example:\n\n"
                f"       def create_cookie(..., domain=None, ...):\n"
                f"           if domain is None:\n"
                f"               domain = ''\n"
                f"           ...\n\n"
                f"   A guard at function entry is a COMPLETE fix. "
                f"Guarding one crash site is not.\n\n"
                f"Your diff will be re-run against the probe. If the "
                f"probe exercises any unguarded use of the value that "
                f"your failure mode identifies, the fix will be "
                f"rejected. Make the fix complete the first time."
            )

        return ""

    # ------------------------------------------------------------------
    # Stage 3 — Fixer (Act)
    # ------------------------------------------------------------------

    async def _stage_fixer(self, context: dict) -> dict:
        """
        Act. Fetch code context (once) and generate the auto-fix diff.
        Both writes are performed by the coordinator; this stage just
        produces the data.

        Returns:
            {code_context, auto_fix} — either key may be absent.
        """
        service = context["service"]
        service_name = context["service_name"]
        stack_analysis = context.get("stack_analysis")
        analysis = context["analysis"]
        incident_id = context["incident_id"]

        result = {}

        skip_reason = context.get("auto_fix_skipped_reason")
        if skip_reason:
            logger.info(
                f"⏭️  Skipping auto-fix for {incident_id}: "
                f"investigator returned {skip_reason}"
            )
            return result

        # Confirmation gate. The Investigator produces findings at
        # three levels of certainty:
        #
        #   refused              — determined not a bug. Skip silently.
        #   confirmed+probe      — proven by a reproducing probe.
        #                          Generate a fix.
        #   confirmed+reasoned   — suspicious but unproven. Do NOT
        #                          generate a fix; surface as an
        #                          unverified finding for human review.
        #
        # Before this gate existed, the pipeline generated diffs for
        # "reasoned_only" findings, which the Verifier could not
        # distinguish from real fixes. See incident INC-20261021-2445CA
        # for the acceptance case that motivated this change.
        investigation = context.get("investigation") or {}
        inv_status = investigation.get("status")
        inv_confirmation = investigation.get("confirmation")

        if inv_status == "confirmed" and inv_confirmation not in (
            "probe_reproduced", "probe_reproduced_realigned",
        ):
            # NEW: reasoned_only findings that document an interpreter-flag
            # or external-state dependency are allowed through the Fixer.
            # Rationale: the pipeline's whole point is that the Verifier is
            # the trust anchor — a diff that doesn't fix the bug fails the
            # Verifier. Blocking reasoned_only findings from the Fixer
            # prevents the pipeline from ever producing a fix for a class
            # of findings that are inherently un-probe-able (interpreter-
            # flag-dependent, network-dependent, time-dependent). Those
            # findings are not "unverified"; they're "un-probe-able but
            # still real."
            evidence = (investigation.get("evidence") or "").lower()
            # Match _validate_scan_confirmation's marker list in
            # investigator.py. The validator already decided this evidence
            # is a valid reason to skip the probe; the Fixer should trust
            # that verdict. The Verifier is the actual trust anchor — a
            # wrong diff fails the tests regardless of the evidence.
            #
            # Keep this tuple in sync with the one in investigator.py.
            un_probeable_markers = (
                "probe", "sandbox", "network", "external",
                "cannot construct", "cannot reproduce",
                "environment", "time-dependent",
            )
            if inv_confirmation == "reasoned_only" and any(
                marker in evidence for marker in un_probeable_markers
            ):
                logger.info(
                    f"⚙️  Fixer: proceeding with reasoned_only finding "
                    f"{incident_id} — evidence documents an un-probe-able "
                    f"external factor; Verifier will be the trust anchor"
                )
                # fall through to the fix generation below
            else:
                logger.info(
                    f"⏭️  Skipping auto-fix for {incident_id}: "
                    f"investigator confirmed but unverified "
                    f"(confirmation={inv_confirmation!r})"
                )
                return {
                    "auto_fix_skipped_reason": "investigator_unverified",
                    "unverified_finding": {
                        "status": inv_status,
                        "confirmation": inv_confirmation,
                        "failure_mode": investigation.get("failure_mode"),
                        "fix_location": investigation.get("fix_location"),
                        "confidence": investigation.get("confidence"),
                        "reason": (
                            "Investigator confirmed this pattern but could "
                            "not reproduce it with a probe. No fix was "
                            "generated. Recommend human review."
                        ),
                    },
                }

        if inv_status == "confirmed" and inv_confirmation is None:
            # Defensive: this shouldn't happen. If it does, it's a bug
            # in the Investigator's output contract. Treat as
            # unverified rather than silently fixing.
            logger.error(
                f"Fixer: confirmed investigation for {incident_id} has "
                f"no confirmation field. Refusing to generate a fix."
            )
            return {
                "auto_fix_skipped_reason": "invalid_confirmation",
                "unverified_finding": {
                    "status": inv_status,
                    "confirmation": None,
                    "failure_mode": investigation.get("failure_mode"),
                    "fix_location": investigation.get("fix_location"),
                    "reason": (
                        "Investigator returned confirmed without a "
                        "confirmation field. This is an Investigator "
                        "output contract violation."
                    ),
                },
            }

        if not (stack_analysis and stack_analysis.get("file_path")):
            return result

        # Fetch code context once. Prefer reading from the clone the
        # Investigator created — it's on disk, it's not rate-limited,
        # and it handles the monorepo path mismatch the GitHub API
        # does not (the stack trace says src/services/foo.py; the repo
        # has backend/orchestrator/src/services/foo.py). Fall back to
        # the GitHub API only when there is no clone.
        
        trace_line = stack_analysis.get("line_number", 1)
        target_line = trace_line
        null_source = context.get("null_source")

        if null_source and context.get("investigation"):
            # Normalize the null source for matching. The Investigator
            # sometimes emits "self.rag", sometimes "get_rag_service()",
            # and sometimes "get_rag_service" — all refer to the same
            # thing. Strip trailing parens and whitespace on both sides.
            normalized = null_source.strip().rstrip("()")

            # Look for the *usage* line first. The usage is always in
            # the file the stack trace points at. The assignment may
            # be in a different file (get_rag_service is defined in
            # rag_service.py), where its line number means nothing in
            # the file we're fixing.
            usage_line = None
            for obs in context["investigation"].get("history", []):
                if obs.get("tool") != "search_codebase":
                    continue
                result_text = obs.get("result", "")
                for line in result_text.splitlines():
                    if normalized not in line:
                        continue
                    # search_codebase result format:
                    #   "path/to/file.py:123: the line content"
                    parts = line.split(":", 2)
                    if len(parts) < 2:
                        continue
                    try:
                        usage_line = int(parts[1])
                    except ValueError:
                        continue
                    break
                if usage_line:
                    break

            if usage_line:
                target_line = usage_line
                logger.info(
                    f"🎯 Fixer: targeting line {target_line} "
                    f"(usage of `{null_source}`) instead of "
                    f"stack-trace line {trace_line}"
                )
            else:
                # Fall back to the assignment line if the usage site
                # wasn't found in the history.
                for obs in context["investigation"].get("history", []):
                    args = obs.get("args", {})
                    symbol = (args.get("symbol_name") or "").strip().rstrip("()")
                    if (
                        obs.get("tool") == "read_symbol"
                        and symbol
                        and symbol == normalized
                    ):
                        meta = obs.get("metadata", {})
                        if meta.get("start_line"):
                            target_line = meta["start_line"]
                            logger.info(
                                f"🎯 Fixer: targeting line {target_line} "
                                f"(assignment of `{null_source}`) instead of "
                                f"stack-trace line {trace_line}"
                            )
                        break
        
        code_context = None
        repo_workdir = context.get("repo_workdir")

        if repo_workdir:
            code_context = self._read_code_context_from_clone(
                repo_workdir=repo_workdir,
                file_path=stack_analysis["file_path"],
                line_number=target_line,
                context_lines=30,
            )
            if code_context:
                logger.info(
                    f"✅ Code context read from clone: "
                    f"{code_context.get('file_path')}:"
                    f"{code_context.get('line_number')}"
                )

        repo_origin = context.get("repo_origin")
        if code_context is None and repo_origin:
            try:
                github = get_github_service()
                code_context = await github.get_file_content(
                    repo_name=repo_origin,
                    file_path=stack_analysis["file_path"],
                    line_number=target_line,
                    context_lines=30,
                )
                if code_context:
                    logger.info(
                        f"✅ Code context fetched from GitHub: "
                        f"{code_context.get('file_path')}:"
                        f"{code_context.get('line_number')}"
                    )
            except Exception as e:
                logger.error(f"Code context error: {e}")

        if code_context:
            result["code_context"] = code_context
            
        diagnosis_block = self._build_diagnosis_block(context)

        try:
            autofix = AutoFixService()
            fix_result = await autofix.generate_fix(
                {
                    "incident_id": incident_id,
                    "service_name": service_name,
                    "repo_name": service.get("repo_name"),
                    "file_path": stack_analysis["file_path"],
                    "line_number": stack_analysis.get("line_number"),
                    "exception_type": stack_analysis.get("exception_type"),
                    "root_cause": analysis.get("root_cause"),
                    "null_source": null_source,
                },
                require_permission=True,
                code_context=code_context,
                diagnosis_block=diagnosis_block,
            )

            if fix_result and not fix_result.get("error"):
                result["auto_fix"] = fix_result
                logger.info(
                    f"✅ Auto-fix generated for {incident_id} (waiting for approval)"
                )
            else:
                logger.warning(f"⚠️ Auto-fix failed: {fix_result.get('error')}")
        except Exception as e:
            logger.error(f"Auto-fix error: {e}")

        return result

    # ------------------------------------------------------------------
    # Stage 4 — Verifier (Verify)
    # ------------------------------------------------------------------

    async def _stage_verifier(self, context: dict) -> dict:
        """
        Verify. Runs the auto-fix diff against the repo's own tests in
        a sandbox, gated by VERIFY_BEFORE_REPORT. The Verifier
        implementation is selected via get_verifier() — hosted Docker
        today, phone-home runner later.

        Returns:
            {verification: VerificationResult-as-dict} — the coordinator
            persists it via record_verification when present.

        No diff, or the feature flag off, returns a result with
        reason="disabled" or "no_diff" so downstream consumers can
        tell "verified and passed" from "not verified."
        """
        from src.agents.verifier import get_verifier

        auto_fix = context.get("auto_fix") or {}
        diff = auto_fix.get("fix")

        if not diff:
            return {"verification": {
                "passed": False,
                "reason": "no_diff",
                "verifier": "n/a",
            }}

        service = context["service"]
        language = context.get("language") or self._infer_language(
            context.get("stack_analysis") or {},
            service.get("repo_name") or context["service_name"],
        )

        try:
            verifier = get_verifier(has_runner=False)
            # commit_sha defaults to HEAD because nothing upstream
            # sets it today. Both get_file_content (via GitHub's
            # default-branch contents API) and _clone (via git clone
            # of the default branch) resolve to the same ref, so HEAD
            # is correct for now. When commit pinning lands, this
            # should be set by the Watcher from the stack trace's
            # context or by the blame lookup.
            logger.info(
                f"Verifier: target={context.get('stack_analysis', {}).get('file_path')}:"
                f"{context.get('stack_analysis', {}).get('line_number')}, "
                f"diff bytes={len(diff)}"
            )
                        
            # Prefer repo_origin (correct GitHub identity) over
            # service["repo_name"] (which is a directory basename
            # for local-path scans). When the Verifier has a
            # context["repo_workdir"] it reuses the clone regardless
            # of repo_name; the fallback clone path needs a real
            # owner/repo.
            verify_repo = (
                context.get("repo_origin")
                or service.get("repo_name")
                or context["service_name"]
            )
            result = await verifier.verify(
                repo_name=verify_repo,
                commit_sha=context.get("commit_sha", "HEAD"),
                diff=diff,
                language=language,
                context=context,
            )

        except Exception as e:
            logger.error(f"Verifier error: {e}")
            return {"verification": {
                "passed": False,
                "reason": "verifier_exception",
                "verifier": "unknown",
            }}

        # When verification passes via probe, persist the fix to the
        # working tree so the next scan can recognize it as
        # already-fixed. This writes <repo_workdir>/.aegis/fixes.json
        # and git-excludes the .aegis/ directory so subsequent
        # git reset/clean don't touch it.
        if result.passed and result.reason == "probe_passed":
            try:
                await self._persist_fix_to_tree(
                    context=context,
                    diff=diff,
                    verification=result,
                )
            except Exception as e:
                # Persisting the fix is a best-effort operation. If
                # it fails, the verification still stands — the
                # incident is still recorded as verified. Just log
                # and move on.
                logger.error(
                    f"Verifier: failed to persist fix to tree for "
                    f"{context.get('incident_id')}: {e}"
                )

        return {"verification": {
            "passed": result.passed,
            "reason": result.reason,
            "output": result.output,
            "duration_ms": result.duration_ms,
            "attempts": result.attempts,
            "verifier": result.verifier,
            "realignment": {
                "hunks_total": result.realignment.hunks_total,
                "hunks_realigned": result.realignment.hunks_realigned,
                "hunks_unchanged": result.realignment.hunks_unchanged,
                "hunks_flagged": result.realignment.hunks_flagged,
            },
        }}
        
    async def _persist_fix_to_tree(
        self,
        *,
        context: dict,
        diff: str,
        verification,
    ) -> None:
        """Persist a verified fix to <repo_workdir>/.aegis/fixes.json.

        This is what makes subsequent scans report the bug as
        "already_fixed by AEGIS PRO" rather than silently omitting
        the line. The file records what was fixed, when, at what
        commit, and with what probe. It's git-excluded so reset/clean
        don't remove it, but survives tree resets because the fix
        itself stays applied in the working tree.

        Failure is not fatal — the caller catches and logs.
        """
        from pathlib import Path

        repo_workdir = context.get("repo_workdir")
        if not repo_workdir:
            logger.debug(
                "Verifier: no repo_workdir; skipping fix persistence"
            )
            return

        tree_root = Path(repo_workdir)
        if not tree_root.is_dir():
            logger.warning(
                f"Verifier: repo_workdir {tree_root} is not a directory; "
                f"skipping fix persistence"
            )
            return

        # Read the investigation to extract the successful probe.
        investigation = context.get("investigation") or {}
        probe_code = ""
        probe_flags: list[str] = []
        for h in (investigation.get("history") or []):
            if h.get("tool") == "probe" and (h.get("metadata") or {}).get("reproduced") is True:
                probe_code = (h.get("args") or {}).get("code") or ""
                probe_flags = (h.get("args") or {}).get("interpreter_flags") or []
                break

        stack = context.get("stack_analysis") or {}
        chain = context.get("chain") or []
        root_link = chain[0] if chain else {}
        scan_candidate = context.get("scan_candidate") or {}

        # Compute the fix's file/line/pattern. In scan mode these
        # come from the ScanCandidate (the synthetic stack trace is
        # built from them). In incident mode they come from the
        # stack trace.
        file_rel = (
            scan_candidate.get("root_file")
            or stack.get("file_path")
            or root_link.get("file")
            or ""
        )
        line = (
            scan_candidate.get("root_line")
            or stack.get("line_number")
            or root_link.get("line")
            or 0
        )
        pattern = (
            scan_candidate.get("pattern")
            or "incident"
        )
        symbol = (
            scan_candidate.get("symbol")
            or context.get("null_source")
            or ""
        )

        if not (file_rel and line):
            logger.warning(
                f"Verifier: cannot determine fix target for "
                f"persistence (file={file_rel!r}, line={line!r}); "
                f"skipping"
            )
            return

        aegis_dir = tree_root / ".aegis"
        aegis_dir.mkdir(exist_ok=True)

        # Git-exclude .aegis/ so reset --hard and clean -fd don't
        # touch it. This is essential: the fix provenance must
        # survive the Verifier's own tree reset.
        exclude = tree_root / ".git" / "info" / "exclude"
        if exclude.is_file():
            try:
                content = exclude.read_text()
                if ".aegis/" not in content:
                    exclude.write_text(
                        content.rstrip() + "\n# AEGIS PRO state\n.aegis/\n"
                    )
            except OSError as e:
                logger.warning(
                    f"Verifier: could not update .git/info/exclude: {e}"
                )

        fixes_path = aegis_dir / "fixes.json"
        data = {"version": 1, "fixes": []}
        if fixes_path.is_file():
            try:
                data = json.loads(fixes_path.read_text())
                if not isinstance(data, dict):
                    data = {"version": 1, "fixes": []}
                data.setdefault("fixes", [])
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(
                    f"Verifier: could not read {fixes_path}: {e}; "
                    f"starting fresh"
                )
                data = {"version": 1, "fixes": []}

        new_entry = {
            "incident_id": context.get("incident_id") or "",
            "file": file_rel,
            "line": line,
            "pattern": pattern,
            "symbol": symbol,
            "fix_diff": diff,
            "base_commit": context.get("commit_sha") or "HEAD",
            "verified_at": datetime.utcnow().isoformat() + "Z",
            "verification_reason": verification.reason,
            "probe_code": probe_code,
            "probe_flags": probe_flags,
        }

        # Idempotency: replace any existing entry for the same
        # (file, line, pattern).
        data["fixes"] = [
            f for f in data["fixes"]
            if not (
                f.get("file") == file_rel
                and f.get("line") == line
                and f.get("pattern") == pattern
            )
        ]
        data["fixes"].append(new_entry)

        # Atomic write
        tmp = fixes_path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(fixes_path)
            logger.info(
                f"✅ Verifier: persisted fix for {file_rel}:{line} "
                f"({pattern}) to {fixes_path} "
                f"({len(data['fixes'])} total fixes tracked)"
            )
        except OSError as e:
            logger.error(
                f"Verifier: could not write {fixes_path}: {e}"
            )
            try:
                tmp.unlink()
            except OSError:
                pass
            raise

    def _infer_language(self, stack_analysis: dict, repo_name: str) -> str:
        """
        Best-effort language inference for the verifier's base-image
        selection. Falls back to "Python" — the most common language
        for backend repos and the safest guess when nothing else is
        available.
        """
        file_path = (stack_analysis or {}).get("file_path") or ""
        suffix_map = {
            ".py": "Python",
            ".js": "Node",
            ".ts": "Node",
            ".jsx": "Node",
            ".tsx": "Node",
        }
        for suffix, language in suffix_map.items():
            if file_path.endswith(suffix):
                return language

        # Repo-name hints, matching the demo parser's keyword set.
        name_lower = (repo_name or "").lower()
        if "python" in name_lower or name_lower.startswith("py-") or name_lower.endswith("-py"):
            return "Python"
        if any(k in name_lower for k in ("node", "-js", "-ts", "web-ts")):
            return "Node"

        return "Python"

    # ------------------------------------------------------------------
    # Stage 5 — Communicator (Report)
    # ------------------------------------------------------------------

    async def _stage_communicator(self, context: dict) -> None:
        """
        Report. Page on-call, send alerts, check K8s, broadcast over
        WebSocket. All side effects — returns nothing. Each block is
        wrapped in its own try/except so a failure in one doesn't
        affect the others.
        """
        service_name = context["service_name"]
        service = context["service"]
        analysis = context["analysis"]
        incident_id = context["incident_id"]

        oncall = OnCallService()
        on_call = None
        try:
            on_call = await oncall.get_on_call(service_name)
            if on_call and not on_call.get("error"):
                logger.info(f"📋 On-call: {on_call.get('primary', {}).get('name')}")
        except Exception as e:
            logger.error(f"On-call error: {e}")

        try:
            alert = AlertService()
            severity = analysis.get("severity", "P1")
            escalation = await oncall.get_escalation_policy(service_name, severity)
            await alert.send_alerts(
                {
                    "incident_id": incident_id,
                    "service_name": service_name,
                    "severity": severity,
                    "title": analysis.get("title"),
                },
                on_call,
                escalation,
            )
            logger.info(f"📢 Alerts sent for {incident_id}")
        except Exception as e:
            logger.error(f"Alert error: {e}")

        try:
            k8s = KubernetesService()
            status = await k8s.get_deployment_status(service_name)
            logger.info(f"☸️ K8s status: {status}")
        except Exception as e:
            logger.error(f"K8s error: {e}")

        try:
            broadcast_data = {
                "incident_id": incident_id,
                "service_name": service_name,
                "severity": analysis.get("severity"),
                "title": analysis.get("title"),
            }
            # Include verification when present so the live dashboard
            # can show "verified / failed / not run" next to the
            # incident without a second fetch.
            verification = context.get("verification")
            if verification:
                broadcast_data["verification"] = {
                    "passed": verification.get("passed"),
                    "reason": verification.get("reason"),
                    "verifier": verification.get("verifier"),
                }
            await manager.broadcast({
                "type": "new_incident",
                "data": broadcast_data,
            })
        except Exception as e:
            logger.error(f"WebSocket broadcast error: {e}")

    # ------------------------------------------------------------------
    # Stage 6 — Curator (Learn)
    # ------------------------------------------------------------------

    async def _stage_curator(self, context: dict) -> None:
        """
        Learn. Store the incident embedding so future diagnoses can
        retrieve it. Wrapped in try/except — a RAG failure must not
        return a 500 to a caller whose incident is already persisted
        and whose alerts have already fired. Closes #73.

        When the fix_outcomes table lands, the Curator stage also
        writes the approve/reject outcome here.
        """
        incident_data = context["incident_data"]

        try:
            await self.rag.store_incident(incident_data)
        except Exception as e:
            logger.error(f"RAG store error: {e}")

    # ------------------------------------------------------------------
    # Response builder
    # ------------------------------------------------------------------

    def _build_response(self, context: dict) -> dict:
        """
        Assemble the public response dict from the accumulated context.

        Kept as a method rather than an inline literal so the shape of
        the response is visible in one place and can be tested without
        running the pipeline.
        """
        service_name = context["service_name"]
        service = context["service"]
        analysis = context["analysis"]
        blast_radius = context["blast_radius"]

        response = {
            "incident_id": context["incident_id"],
            "service": service_name,
            "severity": analysis.get("severity"),
            "title": analysis.get("title"),
            "on_call": service.get("on_call", []),
            "root_cause": analysis.get("root_cause"),
            "suggested_fix": analysis.get("suggested_fix"),
            "rollback_command": analysis.get("rollback_command"),
            "confidence": analysis.get("confidence"),
            "blast_radius": blast_radius,
            "rag_context_used": context.get("rag_used", False),
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        auto_fix = context.get("auto_fix") or {}
        if auto_fix.get("fix"):
            response["auto_fix"] = {
                "diff": auto_fix["fix"],
                "repo_name": auto_fix.get("repo_name"),
                "requires_approval": auto_fix.get("requires_approval", True),
                "mode": (auto_fix.get("pr") or {}).get("mode", "unknown"),
            }

        verification = context.get("verification")
        if verification:
            response["verification"] = dict(verification)
            
        investigation = context.get("investigation")
        if investigation:
            response["investigation"] = {
                "status": investigation.get("status"),
                "null_source": investigation.get("null_source"),
                "confidence": investigation.get("confidence"),
                "iterations": investigation.get("iterations"),
                "history": investigation.get("history", []),
            }
        skip_reason = context.get("auto_fix_skipped_reason")
        if skip_reason:
            response["auto_fix_skipped_reason"] = skip_reason

        unverified = context.get("unverified_finding")
        if unverified:
            response["unverified_finding"] = unverified

        return response
    
    
    async def enrich_finding_for_report(
        self,
        incident: dict,
        repo_origin: str | None,
    ) -> dict:
        """
        Fetch GitHub enrichment (blame, recent PRs, related PRs)
        for a finding, and persist it to the incident's
        extra_metadata.github.

        Called at report time — after the pipeline completes —
        not during the pipeline. Refused findings and
        already-fixed findings don't call this. The caller
        decides which findings to enrich based on status:

          - status='active' with verification.reason='probe_passed'
            → Verified → enrich
          - status='active' with verification.reason='probe_failed'
            → Verification Failed → enrich
          - status='active' with unverified_finding present
            → Needs Review → enrich
          - status='active' with no verification and no
            unverified_finding → Refused → skip
          - status='already_fixed' → skip (provenance is
            the trust anchor; no external data needed)

        Returns the enrichment dict (may be empty), also written
        to the incident row. Safe to call multiple times —
        record_github_context merges.

        If repo_origin is None (local path with no .git/config,
        or a non-GitHub origin), returns {} without calling
        GitHub. That's the honest degradation.
        """
        if not repo_origin:
            logger.debug(
                f"enrich_finding_for_report: no repo_origin for "
                f"{incident.get('incident_id')}; skipping"
            )
            return {}

        file_path = incident.get("file_path")
        line_number = incident.get("line_number") or 1
        incident_id = incident.get("incident_id")
        if not incident_id:
            return {}

        try:
            github = get_github_service()
        except Exception as e:
            logger.warning(f"enrich_finding_for_report: GitHub unavailable: {e}")
            return {}

        enrichment: dict = {}

        try:
            enrichment["recent_prs"] = await github.get_recent_prs(repo_origin)
        except Exception as e:
            logger.warning(f"enrich_finding_for_report: get_recent_prs failed: {e}")

        if file_path:
            try:
                logger.info(
                    f"🔍 Enriching {incident_id}: blame for "
                    f"{file_path}:{line_number} (repo={repo_origin})"
                )
                blame = await github.get_blame_with_pr(
                    repo_origin, file_path, line_number,
                )
                if blame:
                    enrichment["blame"] = blame
                    logger.info(
                        f"✅ Blame found for {incident_id}: "
                        f"{blame.get('author')} - "
                        f"{(blame.get('message') or '')[:50]}"
                    )
            except Exception as e:
                logger.warning(f"enrich_finding_for_report: get_blame_with_pr failed: {e}")

            try:
                related = await github.get_related_prs(
                    repo_name=repo_origin,
                    file_path=file_path,
                    line_number=line_number,
                    limit=5,
                )
                if related:
                    enrichment["related_prs"] = related
                    logger.info(
                        f"🔗 Enriching {incident_id}: found "
                        f"{len(related)} related PRs"
                    )
            except Exception as e:
                logger.warning(f"enrich_finding_for_report: get_related_prs failed: {e}")

        if enrichment:
            try:
                if enrichment.get("recent_prs"):
                    await self.record_github_context(
                        incident_id, {"recent_prs": enrichment["recent_prs"]}
                    )
                if enrichment.get("blame"):
                    await self.record_github_context(
                        incident_id, {"blame": enrichment["blame"]}
                    )
                if enrichment.get("related_prs"):
                    await self.record_related_prs(
                        incident_id, enrichment["related_prs"]
                    )
            except Exception as e:
                logger.warning(
                    f"enrich_finding_for_report: persist failed for "
                    f"{incident_id}: {e}"
                )

        return enrichment

    def _should_enrich(self, incident: dict) -> bool:
        """
        True when a finding is in one of the states that warrants
        GitHub enrichment at report time. All four report buckets
        qualify:

          Verified            — verified.passed && reason=='probe_passed'
          Verification Failed — verified.reason=='probe_failed'
          Needs Review        — unverified_finding present
          Already Fixed       — status=='already_fixed'

        Already Fixed is enriched because a reviewer looking at a
        prior fix wants the same context as one looking at a new
        fix: who authored the line, what PR touched it, what's
        nearby. The provenance record shows what AEGIS did; the
        enrichment shows what humans did. Both are useful.

        Refused findings are the only bucket that gets no
        enrichment — a reviewer reads the Investigator's reasoning,
        not git history.

        IMPORTANT: verification and unverified_finding live under
        extra_metadata, not at the top level of the incident dict.
        get_incident returns the raw row; the CLI report and this
        helper both read from extra_metadata. Reading from the
        top level silently returns None and every finding looks
        refused.
        """
        if incident.get("status") == "already_fixed":
            return True

        meta = incident.get("extra_metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (TypeError, json.JSONDecodeError):
                meta = {}
        if not isinstance(meta, dict):
            meta = {}

        verification = meta.get("verification") or {}
        if verification.get("passed") and verification.get("reason") == "probe_passed":
            return True
        if verification.get("reason") == "probe_failed":
            return True
        if meta.get("unverified_finding"):
            return True

        return False

    # ------------------------------------------------------------------
    # Persistence: INSERT once, then UPDATE per stage
    # ------------------------------------------------------------------

    async def _persist_diagnosed_incident(self, incident_data: dict):
        """
        One-shot INSERT of the incident row. Called exactly once per
        declare_incident, immediately after diagnosis completes and
        before any enrichment.

        Named to make that explicit — this is not a general-purpose
        saver. Enrichment writes go through the record_* methods below.
        """
        try:
            async with get_db_session() as session:
                await session.execute(
                    text("""
                        INSERT INTO incidents (
                            incident_id, service_name, severity, status, title, description,
                            stack_trace, exception_type, file_path, line_number,
                            root_cause, suggested_fix, rollback_command, confidence_score,
                            declared_at, extra_metadata, affected_services
                        ) VALUES (
                            :incident_id, :service_name, :severity, :status, :title, :description,
                            :stack_trace, :exception_type, :file_path, :line_number,
                            :root_cause, :suggested_fix, :rollback_command, :confidence_score,
                            :declared_at, :extra_metadata, :affected_services
                        )
                    """),
                    incident_data
                )
                await session.commit()
                logger.info(f"✅ Incident {incident_data['incident_id']} persisted")
        except Exception as e:
            logger.error(f"Error persisting incident: {e}")

    async def _load_extra_metadata(self, session, incident_id: str):
        """
        Read the current extra_metadata for an incident. Returns the
        raw value (str, dict, or None) and whether the row exists.
        """
        result = await session.execute(
            text("SELECT extra_metadata FROM incidents WHERE incident_id = :id"),
            {"id": incident_id}
        )
        row = result.fetchone()
        if not row:
            return None, False
        return row[0], True

    async def record_github_context(self, incident_id: str, github_context: dict):
        """Merge the GitHub context (recent_prs, blame) into extra_metadata.github."""
        async with get_db_session() as session:
            existing, found = await self._load_extra_metadata(session, incident_id)
            if not found:
                logger.warning(f"record_github_context: incident {incident_id} not found")
                return

            # Read-merge-write. Preserve any sibling keys under "github"
            # that a previous record_* method may have written. This
            # makes record_github_context and record_related_prs
            # order-independent.
            metadata = self._safe_json_load(existing)
            github = metadata.get("github")
            if not isinstance(github, dict):
                github = {}
            github.update(github_context)
            metadata["github"] = github

            await session.execute(
                text("UPDATE incidents SET extra_metadata = CAST(:m AS jsonb) WHERE incident_id = :id"),
                {"m": json.dumps(metadata), "id": incident_id}
            )
            await session.commit()

    async def record_code_context(self, incident_id: str, code_context: dict):
        """Merge the fetched code context into extra_metadata.code_context."""
        async with get_db_session() as session:
            existing, found = await self._load_extra_metadata(session, incident_id)
            if not found:
                logger.warning(f"record_code_context: incident {incident_id} not found")
                return

            merged = merge_incident_metadata(existing, "code_context", code_context)
            await session.execute(
                text("UPDATE incidents SET extra_metadata = CAST(:m AS jsonb) WHERE incident_id = :id"),
                {"m": merged, "id": incident_id}
            )
            await session.commit()

    async def record_related_prs(self, incident_id: str, related_prs: list):
        """
        Merge related PRs into extra_metadata.github.related_prs.

        Nested one level under "github". Order-independent from
        record_github_context — both defensively ensure the parent is
        a dict before writing.
        """
        async with get_db_session() as session:
            existing, found = await self._load_extra_metadata(session, incident_id)
            if not found:
                logger.warning(f"record_related_prs: incident {incident_id} not found")
                return

            metadata = self._safe_json_load(existing)
            github = metadata.get("github")
            if not isinstance(github, dict):
                github = {}
            github["related_prs"] = related_prs
            metadata["github"] = github

            await session.execute(
                text("UPDATE incidents SET extra_metadata = CAST(:m AS jsonb) WHERE incident_id = :id"),
                {"m": json.dumps(metadata), "id": incident_id}
            )
            await session.commit()

    async def record_auto_fix(self, incident_id: str, fix_result: dict):
        """Merge the auto-fix payload into extra_metadata.auto_fix."""
        async with get_db_session() as session:
            existing, found = await self._load_extra_metadata(session, incident_id)
            if not found:
                logger.warning(f"record_auto_fix: incident {incident_id} not found")
                return

            merged = merge_incident_metadata(existing, "auto_fix", fix_result)
            await session.execute(
                text("UPDATE incidents SET extra_metadata = CAST(:m AS jsonb) WHERE incident_id = :id"),
                {"m": merged, "id": incident_id}
            )
            await session.commit()

    @staticmethod
    def _safe_json_load(existing):
        """Return existing as a dict, or {} if it isn't one."""
        if not existing:
            return {}
        if isinstance(existing, dict):
            return existing
        try:
            loaded = json.loads(existing)
        except (TypeError, json.JSONDecodeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}
    
    
    async def record_verification(self, incident_id: str, verification: dict):
        """Merge the verification result into extra_metadata.verification."""
        async with get_db_session() as session:
            existing, found = await self._load_extra_metadata(session, incident_id)
            if not found:
                logger.warning(f"record_verification: incident {incident_id} not found")
                return

            merged = merge_incident_metadata(existing, "verification", verification)
            await session.execute(
                text("UPDATE incidents SET extra_metadata = CAST(:m AS jsonb) WHERE incident_id = :id"),
                {"m": merged, "id": incident_id}
            )
            await session.commit()
            
    async def record_unverified_finding(self, incident_id: str, finding: dict):
        """
        Merge the unverified-finding block into
        extra_metadata.unverified_finding.

        Same shape as record_verification — merge-not-overwrite, via
        merge_incident_metadata. Separate from auto_fix because the
        finding has no diff; it's a report entry, not a fix.
        """
        async with get_db_session() as session:
            existing, found = await self._load_extra_metadata(session, incident_id)
            if not found:
                logger.warning(
                    f"record_unverified_finding: incident {incident_id} not found"
                )
                return

            merged = merge_incident_metadata(existing, "unverified_finding", finding)
            await session.execute(
                text("UPDATE incidents SET extra_metadata = CAST(:m AS jsonb) WHERE incident_id = :id"),
                {"m": merged, "id": incident_id}
            )
            await session.commit()
            
    async def record_investigation(self, incident_id: str, investigation: dict):
        """
        Merge the Investigator agent's result into
        extra_metadata.investigation.

        Same shape as record_verification — merge-not-overwrite, via
        merge_incident_metadata.
        """
        async with get_db_session() as session:
            existing, found = await self._load_extra_metadata(session, incident_id)
            if not found:
                logger.warning(f"record_investigation: incident {incident_id} not found")
                return

            merged = merge_incident_metadata(existing, "investigation", investigation)
            await session.execute(
                text("UPDATE incidents SET extra_metadata = CAST(:m AS jsonb) WHERE incident_id = :id"),
                {"m": merged, "id": incident_id}
            )
            await session.commit()

    # ------------------------------------------------------------------
    # Read APIs (unchanged from before 12.1a)
    # ------------------------------------------------------------------

    async def get_service(self, service_name: str) -> dict:
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    text("SELECT * FROM services WHERE name = :name"),
                    {"name": service_name}
                )
                row = result.fetchone()
                if row:
                    return dict(row._mapping)
                return None
        except Exception as e:
            logger.error(f"Error getting service: {e}")
            return self._mock_service(service_name)

    async def list_services(self) -> list:
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    text("""
                        SELECT 
                            name, 
                            description, 
                            on_call, 
                            dependencies, 
                            is_critical,
                            repo_name
                        FROM services 
                        ORDER BY name
                    """)
                )
                rows = result.fetchall()
                return [
                    {
                        "name": row[0],
                        "description": row[1],
                        "on_call": row[2] if row[2] else [],
                        "dependencies": row[3] if row[3] else [],
                        "is_critical": row[4] if row[4] else False,
                        "repo_name": row[5],
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Error listing services: {e}")
            return self._mock_services_list()

    async def get_incident(self, incident_id: str) -> dict:
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    text("SELECT * FROM incidents WHERE incident_id = :incident_id"),
                    {"incident_id": incident_id}
                )
                row = result.fetchone()
                if row:
                    data = dict(row._mapping)
                    if data.get('extra_metadata') and isinstance(data['extra_metadata'], str):
                        try:
                            data['extra_metadata'] = json.loads(data['extra_metadata'])
                        except:
                            pass
                    if data.get('affected_services') and isinstance(data['affected_services'], str):
                        try:
                            data['affected_services'] = json.loads(data['affected_services'])
                        except:
                            pass
                    return data
                return None
        except Exception as e:
            logger.error(f"Error getting incident: {e}")
            return None

    async def get_all_incidents(self, limit: int = 200) -> list:
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    text("""
                        SELECT 
                            incident_id, 
                            service_name, 
                            severity, 
                            status, 
                            title,
                            description,
                            root_cause,
                            suggested_fix,
                            rollback_command,
                            confidence_score,
                            affected_services,
                            declared_at,
                            extra_metadata
                        FROM incidents 
                        ORDER BY declared_at DESC 
                        LIMIT :limit
                    """),
                    {"limit": limit}
                )
                rows = result.fetchall()
                incidents = []
                for row in rows:
                    incident = {
                        "incident_id": row[0],
                        "service_name": row[1],
                        "severity": row[2],
                        "status": row[3],
                        "title": row[4],
                        "description": row[5],
                        "root_cause": row[6],
                        "suggested_fix": row[7],
                        "rollback_command": row[8],
                        "confidence_score": row[9],
                        "declared_at": row[11]
                    }
                    if row[10]:
                        if isinstance(row[10], str):
                            try:
                                incident["affected_services"] = json.loads(row[10])
                            except:
                                incident["affected_services"] = []
                        elif isinstance(row[10], list):
                            incident["affected_services"] = row[10]
                        else:
                            incident["affected_services"] = []
                    else:
                        incident["affected_services"] = []
                    extra = row[12]
                    if extra:
                        if isinstance(extra, str):
                            try:
                                extra = json.loads(extra)
                            except:
                                extra = {}
                        incident["extra_metadata"] = extra
                    incidents.append(incident)
                return incidents
        except Exception as e:
            logger.error(f"Error getting incidents: {e}")
            return []

    async def calculate_blast_radius(self, service_name: str, dependencies: list) -> dict:
        affected: set[str] = set()
        queue = [service_name] + list(dependencies or [])

        # Bounded BFS — prevents infinite loops on circular deps.
        max_depth = 10
        seen: set[str] = set()

        while queue and len(seen) < max_depth * 10:
            current = queue.pop(0)
            if not current or current in seen:
                continue
            seen.add(current)
            affected.add(current)

            service = await self.get_service(current)
            if service and service.get("dependencies"):
                for dep in service["dependencies"]:
                    if dep and dep not in seen:
                        queue.append(dep)

        affected_list = sorted(affected)

        severity = (
            "CRITICAL" if len(affected_list) > 5
            else "HIGH" if len(affected_list) > 2
            else "MEDIUM"
        )

        return {
            "root": service_name,
            "affected": affected_list,
            "count": len(affected_list),
            "severity": severity
        }

    async def rollback(self, incident_id: str) -> dict:
        incident = await self.get_incident(incident_id)
        if not incident:
            return {"error": "Incident not found"}

        try:
            async with get_db_session() as session:
                await session.execute(
                    text("UPDATE incidents SET status = 'resolved', resolved_at = NOW() WHERE incident_id = :incident_id"),
                    {"incident_id": incident_id}
                )
                await session.commit()
        except Exception as e:
            logger.error(f"Error updating incident: {e}")

        return {
            "incident_id": incident_id,
            "status": "rollback_initiated",
            "rollback_command": incident.get("rollback_command", "kubectl rollout undo deployment"),
            "estimated_time": "2 minutes",
            "mock": True
        }

    async def seed_services(self) -> dict:
        try:
            async with get_db_session() as session:
                await session.execute(text("DELETE FROM services"))

                services = [
                    ("payment-api", "Payment processing — cards, wallets, bank transfers", "payment-service", '["@marcus", "@prisha"]', '["auth", "ledger", "fraud"]', True),
                    ("auth", "Authentication and authorization", "auth-service", '["@dana", "@wei"]', '["user"]', True),
                    ("ledger", "Transaction ledger and accounting", "ledger-service", '["@sofia", "@ade"]', '["database"]', True),
                    ("refund", "Refund and reversal processing", "refund-service", '["@nina"]', '["payment-api", "auth"]', False),
                    ("fraud", "Fraud detection and risk scoring", "fraud-service", '["@omar"]', '["payment-api", "auth"]', False),
                    ("notification", "Email, SMS, and push notifications", "notification-service", '["@lila"]', '["user"]', False),
                    ("user", "User profile and KYC management", "user-service", '["@kenji"]', '[]', False),
                    ("database", "Database operations and migrations", "database-service", '["@rina", "@youssef"]', '[]', True),
                ]

                for service in services:
                    await session.execute(
                        text("""
                            INSERT INTO services (name, description, repo_name, on_call, dependencies, is_critical)
                            VALUES (:name, :description, :repo_name, :on_call, :dependencies, :is_critical)
                        """),
                        {
                            "name": service[0],
                            "description": service[1],
                            "repo_name": service[2],
                            "on_call": service[3],
                            "dependencies": service[4],
                            "is_critical": service[5]
                        }
                    )

                await session.commit()
                return {"status": "seeded", "count": len(services)}
        except Exception as e:
            logger.error(f"Error seeding services: {e}")
            return {"status": "error", "message": str(e)}

    async def add_service(self, service: dict) -> dict:
        async with get_db_session() as session:
            deps = service.get("dependencies") or []
            on_call = service.get("on_call") or []
            if isinstance(deps, str):
                deps = [d.strip() for d in deps.split(",") if d.strip()]
            await session.execute(
                text("""
                    INSERT INTO services (name, description, repo_name, on_call, dependencies, is_critical)
                    VALUES (:name, :description, :repo_name, CAST(:on_call AS jsonb), CAST(:dependencies AS jsonb), :is_critical)
                """),
                {
                    "name": service["name"],
                    "description": service.get("description") or "",
                    "repo_name": service.get("repo_name") or service["name"],
                    "on_call": json.dumps(on_call),
                    "dependencies": json.dumps(deps),
                    "is_critical": bool(service.get("is_critical")),
                }
            )
            await session.commit()
            return {"status": "created", "name": service["name"]}
    
    
    async def resolve_scan_service(
        self,
        owner_repo: str,
        *,
        repo_name: str | None = None,
    ) -> str:
        """Return the service name to use for a scan of `owner_repo`.

        Args:
            owner_repo: service identifier. Used as the service
                        `name`. For local-path scans this is the
                        directory basename (e.g. "requests-buggy").
            repo_name:  the GitHub identity, when known. Used as
                        `services.repo_name`. For local-path scans
                        with a .git/config, this is "psf/requests"
                        (the true origin). For remote scans it's the
                        same as owner_repo. When None (local path
                        with no .git/config), repo_name stays NULL
                        so downstream enrichment knows there's
                        nothing to enrich against.

        Previously, this method set repo_name = owner_repo
        unconditionally. For local-path scans that stored
        "requests-buggy" as the repo_name, which is a directory
        basename, not a GitHub identifier. The enrichment path
        then tried to look up "requests-buggy" on GitHub and
        got 404 every time.

        The fix: accept repo_name separately. Callers that know
        the true GitHub origin (via .git/config or the clone URL)
        pass it; callers that don't pass None, and enrichment
        is skipped honestly.

        Resolution:
          1. If a service already maps to this repo_name, reuse it.
          2. Otherwise, insert with the provided repo_name.
        """
        effective_repo_name = repo_name if repo_name else None

        async with get_db_session() as session:
            # Look up by repo_name when we have one. When we don't,
            # look up by name (so re-scanning the same local path
            # reuses the same service).
            if effective_repo_name:
                result = await session.execute(
                    text("""
                        SELECT name FROM services
                        WHERE repo_name = :repo
                        ORDER BY name ASC
                    """),
                    {"repo": effective_repo_name},
                )
            else:
                result = await session.execute(
                    text("""
                        SELECT name FROM services
                        WHERE name = :name
                        ORDER BY name ASC
                    """),
                    {"name": owner_repo},
                )

            rows = result.fetchall()
            if rows:
                return rows[0][0]

            # No service maps to this repo. Create one scoped to
            # scans, so future scans of the same repo reuse it.
            # ON CONFLICT DO NOTHING keeps an existing manual service
            # with the same name unchanged.
            await session.execute(
                text("""
                    INSERT INTO services (name, repo_name, source)
                    VALUES (:name, :repo, 'scan')
                    ON CONFLICT (name) DO NOTHING
                """),
                {"name": owner_repo, "repo": effective_repo_name},
            )
            await session.commit()
            return owner_repo

    async def delete_service(self, name: str) -> dict:
        async with get_db_session() as session:
            await session.execute(text("DELETE FROM services WHERE name = :name"), {"name": name})
            await session.commit()
            return {"status": "deleted", "name": name}

    def _parse_stack_trace(self, stack_trace: str) -> dict:
        """Parse stack trace - handles multiple formats including Java"""
        import re

        result = {
            "exception_type": None,
            "file_path": None,
            "line_number": None,
            "full_trace": stack_trace[:500]
        }

        exception_patterns = [
            r"([A-Za-z]+(?:Exception|Error)):",
            r"([A-Za-z]+(?:Exception|Error))\s+at",
            r"([A-Za-z]+(?:Exception|Error))\s+at\s+[\w.]+\.(\w+)\(([\w./-]+\.\w+):(\d+)\)",
        ]
        for pattern in exception_patterns:
            exception_match = re.search(pattern, stack_trace)
            if exception_match:
                result["exception_type"] = exception_match.group(1)
                break

        patterns = [
            r"at\s+[\w.]+\.(\w+)\(([\w./-]+\.\w+):(\d+)\)",
            r"at\s+([\w./-]+\.\w+):(\d+)",
            r'File "([^"]+)", line (\d+)',
            r"([\w./-]+\.\w+):(\d+)",
            r"([A-Z][a-zA-Z]+\.java):(\d+)",
            r"([A-Za-z]+\.java):(\d+)",
            r"([A-Za-z]+Service):(\d+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, stack_trace)
            if match:
                if len(match.groups()) == 3:
                    result["file_path"] = match.group(2)
                    result["line_number"] = int(match.group(3))
                elif len(match.groups()) == 2:
                    result["file_path"] = match.group(1)
                    result["line_number"] = int(match.group(2))
                break

        if not result["file_path"]:
            patterns = [
                r'([A-Za-z]+\.java):(\d+)',
                r'([A-Za-z]+Service):(\d+)',
                r'([A-Za-z]+\.py):(\d+)',
                r'([\w./-]+\.\w+):(\d+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, stack_trace)
                if match:
                    result["file_path"] = match.group(1)
                    result["line_number"] = int(match.group(2))
                    break

        if result["file_path"] and " " in result["file_path"]:
            result["file_path"] = result["file_path"].strip()

        return result

    def _mock_service(self, service_name: str) -> dict:
        services = {
            "payment-api": {"name": "payment-api", "on_call": ["@marcus", "@prisha"], "dependencies": ["auth", "ledger", "fraud"]},
            "auth": {"name": "auth", "on_call": ["@dana", "@wei"], "dependencies": ["user"]},
            "ledger": {"name": "ledger", "on_call": ["@sofia", "@ade"], "dependencies": ["database"]},
            "refund": {"name": "refund", "on_call": ["@nina"], "dependencies": ["payment-api", "auth"]},
            "fraud": {"name": "fraud", "on_call": ["@omar"], "dependencies": ["payment-api", "auth"]},
            "notification": {"name": "notification", "on_call": ["@lila"], "dependencies": ["user"]},
            "user": {"name": "user", "on_call": ["@kenji"], "dependencies": []},
            "database": {"name": "database", "on_call": ["@rina", "@youssef"], "dependencies": []}
        }
        return services.get(service_name, {"name": service_name, "on_call": [], "dependencies": []})

    def _mock_services_list(self) -> list:
        return [
            {"name": "payment-api",  "description": "Payment processing — cards, wallets, bank transfers", "on_call": ["@marcus", "@prisha"], "dependencies": ["auth", "ledger", "fraud"], "is_critical": True},
            {"name": "auth",         "description": "Authentication and authorization",                    "on_call": ["@dana", "@wei"],     "dependencies": ["user"],                     "is_critical": True},
            {"name": "ledger",       "description": "Transaction ledger and accounting",                    "on_call": ["@sofia", "@ade"],    "dependencies": ["database"],                 "is_critical": True},
            {"name": "refund",       "description": "Refund and reversal processing",                       "on_call": ["@nina"],             "dependencies": ["payment-api", "auth"],      "is_critical": False},
            {"name": "fraud",        "description": "Fraud detection and risk scoring",                     "on_call": ["@omar"],             "dependencies": ["payment-api", "auth"],      "is_critical": False},
            {"name": "notification", "description": "Email, SMS, and push notifications",                   "on_call": ["@lila"],             "dependencies": ["user"],                     "is_critical": False},
            {"name": "user",         "description": "User profile and KYC management",                      "on_call": ["@kenji"],            "dependencies": [],                           "is_critical": False},
            {"name": "database",     "description": "Database operations and migrations",                   "on_call": ["@rina", "@youssef"], "dependencies": [],                           "is_critical": True},
        ]

    async def update_incident(self, incident_id: str, update_data: dict) -> dict:
        try:
            async with get_db_session() as session:
                from sqlalchemy import update
                from src.models import Incident

                stmt = update(Incident).where(Incident.incident_id == incident_id)

                for key, value in update_data.items():
                    stmt = stmt.values({key: value})

                result = await session.execute(stmt.returning(Incident.incident_id))
                await session.commit()

                row = result.fetchone()
                if row:
                    logger.info(f"✅ Updated incident {incident_id}")
                    return {"status": "updated", "incident_id": incident_id}
                else:
                    return {"error": "Incident not found"}
        except Exception as e:
            logger.error(f"Error updating incident: {e}")
            return {"error": str(e)}
