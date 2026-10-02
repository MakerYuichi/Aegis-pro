from sqlalchemy import text
from datetime import datetime
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
        context = {
            "service_name": service_name,
            "message": message,
            "stack_trace": stack_trace,
            "reported_by": reported_by,
        }

        # Stage 1 — Watcher (Perceive)
        context.update(await self._stage_watcher(context))
        if context.get("error"):
            return context

        # Stage 2 — Provisioner (Clone once)
        #
        # The Provisioner creates one clone per incident when the
        # incident will need filesystem access (repo_name + file_path
        # both set). Every later stage that needs the clone reads
        # context["repo_workdir"]; none of them create or remove it.
        # The coordinator's finally below calls the Provisioner's
        # cleanup to remove the clone after all stages are done.
        context.update(await self._stage_provisioner(context))

        # Stage 3 — Investigator (Reason)
        context.update(await self._stage_investigator(context))

        # Persist the diagnosed incident before any enrichment. This is
        # the invariant that makes every record_* call below safe: the
        # row exists, so a downstream failure leaves a durable record of
        # what we knew at diagnosis time, not silence.
        await self._persist_diagnosed_incident(context["incident_data"])

        # --- Writes owned by the coordinator, sourced from each stage ---

        if context.get("github_context"):
            await self.record_github_context(
                context["incident_id"], context["github_context"]
            )

        if context.get("related_prs"):
            await self.record_related_prs(
                context["incident_id"], context["related_prs"]
            )
        
        if context.get("investigation"):
            await self.record_investigation(
                context["incident_id"], context["investigation"]
            )

        # Stage 3 — Fixer (Act)
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
            cleanup_repo(context.get("repo_workdir"))
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

        The Provisioner is the sole owner of the clone's lifecycle.
        It creates the clone here and it defines the cleanup that the
        coordinator calls in its finally block. No other stage
        creates, reads the process of creating, or removes the clone.

        Returns:
            {"repo_workdir": "<path>"} on success.
            {} when no clone is needed (no repo, no stack-trace file
            path, or the clone failed). An empty return is not an
            error — downstream stages detect the missing clone and
            degrade honestly.
        """
        from src.agents.provisioner import provision_clone

        return await provision_clone(context)

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

        github_context = None
        related_prs = None

        if service.get("repo_name"):
            try:
                github = get_github_service()

                github_context = {
                    "recent_prs": await github.get_recent_prs(service["repo_name"])
                }

                if stack_analysis and stack_analysis.get("file_path"):
                    logger.info(
                        f"🔍 Getting blame for: {stack_analysis['file_path']}:"
                        f"{stack_analysis.get('line_number', 'unknown')}"
                    )
                    blame_info = await github.get_blame_with_pr(
                        service["repo_name"],
                        stack_analysis["file_path"],
                        stack_analysis.get("line_number", 1),
                    )
                    if blame_info:
                        github_context["blame"] = blame_info
                        logger.info(
                            f"✅ Blame found: {blame_info.get('author')} - "
                            f"{blame_info.get('message')[:50]}"
                        )
                    else:
                        logger.warning("⚠️ No blame info found for this file/line")
            except Exception as e:
                logger.error(f"GitHub integration error: {e}")

        if stack_analysis and stack_analysis.get("file_path") and service.get("repo_name"):
            try:
                github = get_github_service()
                related_prs = await github.get_related_prs(
                    repo_name=service["repo_name"],
                    file_path=stack_analysis["file_path"],
                    line_number=stack_analysis.get("line_number", 1),
                    limit=5,
                )
                if related_prs:
                    logger.info(
                        f"🔗 Found {len(related_prs)} related PRs for "
                        f"{stack_analysis['file_path']}"
                    )
                else:
                    related_prs = None
            except Exception as e:
                logger.error(f"Related PRs error: {e}")

        result: dict = {
            "analysis": analysis,
            "rag_used": rag_used,
            "incident_data": incident_data,
            "github_context": github_context,
            "related_prs": related_prs,
        }
        
        if settings.INVESTIGATOR_MODE == "agent":
            investigation = await self._run_investigator_agent(
                context=context,
                service_name=service_name,
                message=message,
                repo=service.get("repo_name") or service_name,
                stack_trace=context.get("stack_trace"),
                stack_analysis=stack_analysis,
                github_context=github_context,
                related_prs=related_prs,
                rag_context=rag_context,
                fix_outcomes=fix_outcomes_context,
                blast_radius=blast_radius,
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
            )
            agent = InvestigatorAgent(
                llm_service=self.llm,
                repo_root=repo_workdir or "",
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

        Today the only diagnosis kind is a null source. When the
        agent learns others, add a branch here — the Fixer's prompt
        template does not change, and AutoFixService does not change.

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
        if not null_source:
            return ""

        return (
            f"\nThe exception is a null dereference. The Investigator "
            f"has identified the null source as:\n\n"
            f"    {null_source}\n\n"
            f"Your diff MUST address this exact expression. Either "
            f"guard its use, add a null check where it's assigned, or "
            f"replace it with a safe alternative. Do NOT modify any "
            f"other line in the file — a diff that touches unrelated "
            f"code will fail verification."
        )

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

        if not (stack_analysis and stack_analysis.get("file_path")):
            return result

        # Fetch code context once. Prefer reading from the clone the
        # Investigator created — it's on disk, it's not rate-limited,
        # and it handles the monorepo path mismatch the GitHub API
        # does not (the stack trace says src/services/foo.py; the repo
        # has backend/orchestrator/src/services/foo.py). Fall back to
        # the GitHub API only when there is no clone.
        code_context = None
        repo_workdir = context.get("repo_workdir")

        if repo_workdir:
            code_context = self._read_code_context_from_clone(
                repo_workdir=repo_workdir,
                file_path=stack_analysis["file_path"],
                line_number=stack_analysis.get("line_number", 1),
                context_lines=30,
            )
            if code_context:
                logger.info(
                    f"✅ Code context read from clone: "
                    f"{code_context.get('file_path')}:"
                    f"{code_context.get('line_number')}"
                )

        if code_context is None and service.get("repo_name"):
            try:
                github = get_github_service()
                code_context = await github.get_file_content(
                    repo_name=service["repo_name"],
                    file_path=stack_analysis["file_path"],
                    line_number=stack_analysis.get("line_number", 1),
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
                    "null_source": context.get("null_source"),
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
                        
            result = await verifier.verify(
                repo_name=service.get("repo_name") or context["service_name"],
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
        
        return response


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
