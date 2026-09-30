from sqlalchemy import text
from src.database import get_db_session
from src.services.factory import get_github_service
from src.services.llm_service import LLMService
from src.config import settings
from loguru import logger
import json
import re

class AutoFixService:
    def __init__(self):
        self.github = get_github_service()
        self.llm = LLMService()
        logger.info("✅ AutoFixService initialized")
        
    @staticmethod
    def _extract_diff(raw: str) -> str:
        """
        Extract a unified diff from the LLM's raw response.

        Real LLMs often wrap the diff in Markdown code fences or
        prepend prose like "Here's the fix:". git apply requires a
        bare unified diff. This extracts what we need from the common
        shapes:

          1. Raw diff (starts with ---) — returned as-is
          2. Markdown fenced block: ```diff ... ``` or ``` ... ```
          3. Prose before/after the diff — take everything from the
             first line starting with --- to the end of the last hunk
          4. No diff found — return the raw string; the verifier will
             reject it, which is the honest outcome
        """
        if not raw:
            return raw

        text = raw.strip()

        # Case 1: already a bare diff.
        if text.startswith("---") or text.startswith("diff --git"):
            return text

        # Case 2: fenced Markdown block.
        fence_pattern = re.compile(
            r"```(?:diff|patch)?\s*\n(.*?)\n```",
            re.DOTALL,
        )
        matches = fence_pattern.findall(text)
        if matches:
            # Take the first fenced block that looks like a diff.
            for candidate in matches:
                candidate = candidate.strip()
                if candidate.startswith("---") or candidate.startswith("diff --git"):
                    return candidate
            # No diff-shaped fence — fall through to case 3.

        # Case 3: find the first line starting with "---" and take
        # everything from there. The diff extends to the end of the
        # string; trailing prose would have been caught by case 2's
        # fence check.
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("--- ") or line.startswith("diff --git"):
                return "\n".join(lines[i:]).rstrip()

        # Case 4: no diff found. Return as-is; the verifier's git
        # apply will reject it and the reason will be
        # "diff_does_not_apply", which is honest.
        return text
    
    @staticmethod
    def _trim_trailing_noise(diff: str) -> str:
        """
        Strip trailing lines that can't be part of a unified diff.

        The extraction from case 2 and case 3 can leave trailing
        backticks, prose, or blank lines if the LLM's output doesn't
        match the expected fence shape exactly. A diff's last line is
        always a context line (' '), an addition ('+'), a removal
        ('-'), or a '\\' no-newline marker. Anything else is noise.

        The returned string never has a trailing newline. Tests that
        compare against this function's output should use .rstrip()
        on their expected value.
        """
        lines = diff.split("\n")
        while lines:
            last = lines[-1]
            if last == "":
                lines.pop()
                continue
            if last.startswith(" ") or last.startswith("+") or \
               last.startswith("-") or last.startswith("\\"):
                break
            lines.pop()
        return "\n".join(lines)
    
    @staticmethod
    def _diff_looks_valid(diff: str) -> bool:
        """
        Cheap structural check on a diff before it goes to the verifier
        or a PR. Rejects the common failure modes LLMs produce:

          - No --- / +++ file markers
          - No hunk header at all
          - Bare @@ without line numbers (git apply cannot infer starts)
          - Truncated output

        Does not check hunk counts — the verifier invokes git apply
        with --recount, which trusts the body over the header counts.
        Starting line numbers, however, cannot be inferred and must
        be present.
        """
        if not diff or len(diff) < 20:
            return False
        lines = diff.split("\n")
        if not any(l.startswith("--- ") for l in lines):
            return False

        has_hunk = False
        for line in lines:
            if not line.startswith("@@"):
                continue
            has_hunk = True
            # Require "@@ -N..." or "@@ -N,M ..." — a bare "@@" is
            # rejected because git apply --recount cannot infer the
            # starting line number.
            if not re.match(r"^@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@", line):
                return False

        return has_hunk
    
    
    async def generate_fix(
        self,
        incident_data: dict,
        require_permission: bool = True,
    ) -> dict:
        try:
            service_name = incident_data.get("service_name")
            file_path = incident_data.get("file_path")
            line_number = incident_data.get("line_number")
            error_type = incident_data.get("exception_type")
            root_cause = incident_data.get("root_cause")
            incident_id = incident_data.get("incident_id")

            if not file_path or not line_number:
                return {"error": "Missing file path or line number"}

            repo_name = incident_data.get("repo_name")
            if not repo_name:
                return {
                    "error": "Missing repo_name — cannot generate fix without a target repository"
                }
            code_context = await self.github.get_file_content(
                repo_name=repo_name,
                file_path=file_path,
                line_number=line_number,
                context_lines=10,
            )

            if not code_context:
                return {"error": "Failed to fetch code from GitHub"}

            prompt = f"""You are an expert software engineer. Fix this issue.

Error: {error_type}
Root Cause: {root_cause}
File: {file_path}
Target line: {line_number}
The diff must modify ONLY this line, or a small range containing it.
Do not modify other lines.

Current Code:
{code_context.get('raw_snippet') or code_context['code_snippet']}

Return ONLY a unified diff, in the exact format git apply expects.
No prose before or after. No Markdown code fences. No explanation.
No headings.

CRITICAL — how the removed lines must look:

The '-' lines in your diff must match lines that appear in the
"Current Code" block above, byte-for-byte. That includes the exact
number of leading spaces. Do not re-indent, do not re-type from
memory. Copy the exact characters from the code above, then prefix
the copied line with a single '-'.

The context lines (prefixed with a single space) follow the same
rule: copy them exactly from the code above.

If a '-' or ' ' line does not match the file byte-for-byte, git
apply will reject the entire patch. This is the single most common
reason an LLM-generated diff fails.

Every hunk MUST have a full header with line numbers, in the
exact form:

    @@ -old_start,old_count +new_start,new_count @@

A bare @@ with no numbers is invalid and git apply will reject the
entire patch. Estimate the starting line number from the "Line: N"
field above (the first context line of the hunk is usually one or
two lines before the target). The counts may be slightly off —
git apply --recount will correct them — but the starting numbers
must be present and roughly right.

CRITICAL: Every hunk must have a full header with line numbers,
in the form:

    @@ -old_start,old_count +new_start,new_count @@

For example, a hunk starting at line 150 with 5 old lines and
6 new lines uses:

    @@ -150,5 +150,6 @@

The @@ marker without line numbers is invalid and git apply will
reject the entire patch.

Full format example:

--- a/path/to/file.py
+++ b/path/to/file.py
@@ -42,6 +42,7 @@
 context line
 context line
-removed line
+added line
 context line
 context line
 context line
"""

            raw_response = await self.llm.complete_raw_detailed(
                prompt=prompt,
                system=(...),
                temperature=0.2,
                max_tokens=1500,
            )

            if not raw_response.content:
                return {"error": "All LLM providers failed to generate a fix"}

            logger.info(
                f"Fix response: {len(raw_response.content)} chars, "
                f"finish_reason={raw_response.finish_reason!r}, "
                f"provider={raw_response.provider!r}, "
                f"model={raw_response.model!r}"
            )
            if raw_response.finish_reason in ("length", "MAX_TOKENS", "max_tokens"):
                logger.warning(
                    f"Fix response was truncated by token limit. "
                    f"Diff will likely be incomplete."
                )
                return {
                    "error": (
                        "LLM response was cut off by the token limit "
                        "before the diff finished. Increase max_tokens "
                        "or shorten the prompt."
                    )
                }

            # LLMs routinely wrap diffs in Markdown or prepend prose.
            # git apply needs a bare diff. Extract what we need, then
            # trim trailing noise (stray backticks, prose after the
            # diff). Hunk counts are left as-is — the verifier passes
            # --recount to git apply, which trusts the body over the
            # header counts.
            fix_result = self._extract_diff(raw_response.content)
            fix_result = self._trim_trailing_noise(fix_result)
            if not self._diff_looks_valid(fix_result):
                logger.warning(
                    f"Auto-fix produced a structurally invalid diff for "
                    f"{incident_id}; discarding. First 200 chars: "
                    f"{fix_result[:200]!r}"
                )
                return {
                    "error": (
                        "LLM produced a structurally invalid diff "
                        "(missing or malformed hunk header). "
                        "Discarding rather than handing to the verifier."
                    )
                }

            pr_info = await self.create_pr(
                repo_name=repo_name,
                file_path=file_path,
                line_number=line_number,
                fix=fix_result,
                incident_id=incident_id,
                require_permission=require_permission,
            )

            return {
                "status": "fix_generated",
                "fix": fix_result,
                "pr": pr_info,
                "code_context": code_context,
                "requires_approval": require_permission,
                "repo_name": repo_name,
            }

        except Exception as e:
            logger.error(f"Auto-fix error: {e}")
            return {"error": str(e)}

    async def create_pr(
        self,
        repo_name: str,
        file_path: str,
        line_number: int,
        fix: str,
        incident_id: str,
        require_permission: bool = True,  # kept for backward compat; AUTO_FIX_MODE owns the decision
    ) -> dict:
        """
        Route PR creation by AUTO_FIX_MODE.

        - read_only:  never touch GitHub write APIs. Return the diff only.
        - pr_draft:   stage the PR payload; creation happens on approval.
        - auto_pr:    real PR creation (deferred — see issue #30).
        """
        mode = (settings.AUTO_FIX_MODE or "read_only").strip().lower()

        if mode == "read_only":
            logger.info(f"🔒 read_only — PR creation disabled for {incident_id}")
            return {
                "mode": "read_only",
                "status": "skipped",
                "fix_preview": fix[:500],
                "message": "AUTO_FIX_MODE=read_only: PR creation disabled by policy.",
            }

        if mode == "pr_draft":
            logger.info(f"📝 pr_draft — staging PR for {incident_id}")
            return {
                "mode": "pr_draft",
                "status": "pr_draft",
                "fix_preview": fix[:500],
                "approval_required": True,
                "approval_url": f"/approve/{incident_id}",
                "message": "Fix staged. Approve in dashboard to create PR.",
            }

        if mode == "auto_pr":
            logger.warning(f"⚠️ auto_pr — creating PR for {incident_id}")
            # TODO(#30): real GitHub PR creation via PyGithub
            raise NotImplementedError(
                "auto_pr requires real GitHub integration — see issue #30"
            )

        raise ValueError(
            f"Invalid AUTO_FIX_MODE: {mode!r}. Expected read_only, pr_draft, or auto_pr."
        )

    def _parse_metadata(self, extra_metadata) -> dict:
        if not extra_metadata:
            return {}
        if isinstance(extra_metadata, str):
            try:
                return json.loads(extra_metadata)
            except Exception:
                return {}
        return extra_metadata
    
    async def _record_outcome(
        self,
        incident: dict,
        auto_fix: dict,
        human_decision: str,
        human_reason: str | None = None,
    ) -> None:
        """
        Write a fix_outcomes row for a human approve/reject.

        Failure mode: log and continue. A failure here must not turn
        a successful human approve/reject into a 500 for the caller.
        Same shape as #73's fix — the human action succeeded; the
        audit record is best-effort.

        The verification block (if present) is read from
        extra_metadata.verification, written by the Verifier stage.
        """
        try:
            from src.services.rag_service import get_rag_service

            incident_id = incident.get("incident_id") or incident.get("id")
            if not incident_id:
                logger.warning("_record_outcome: incident has no incident_id, skipping")
                return

            extra_metadata = self._parse_metadata(incident.get("extra_metadata", {}))
            verification = extra_metadata.get("verification") or {}

            outcome = {
                "incident_id": incident_id,
                "service_name": incident.get("service_name") or auto_fix.get("service_name"),
                "repo_name": auto_fix.get("repo_name"),
                "fix_diff": auto_fix.get("fix"),
                "verification_passed": verification.get("passed"),
                "verification_reason": verification.get("reason"),
                "human_decision": human_decision,
                "human_reason": human_reason,
                "root_cause": incident.get("root_cause"),
                "suggested_fix": incident.get("suggested_fix"),
                "stack_context": incident.get("stack_trace"),
            }

            rag = get_rag_service()
            await rag.store_outcome(outcome)
        except Exception as e:
            logger.error(f"Failed to record {human_decision} outcome: {e}")
    
    def _is_pending(self, auto_fix: dict) -> bool:
        if not auto_fix or auto_fix.get("error"):
            return False
        status = (
            auto_fix.get("status") or auto_fix.get("pr", {}).get("status") or ""
        ).lower()
        if status in ("approved", "rejected", "pr_created"):
            return False
        if auto_fix.get("approved") is True:
            return False
        return bool(
            auto_fix.get("requires_approval")
            or auto_fix.get("pr", {}).get("approval_required")
            or status in ("fix_generated", "pr_draft", "pending")
        )

    async def _update_auto_fix(
        self,
        incident_id: str,
        extra_metadata: dict,
        incident_status: str,
    ) -> None:
        async with get_db_session() as session:
            await session.execute(
                text(
                    """
                    UPDATE incidents
                    SET extra_metadata = CAST(:metadata AS jsonb),
                        status = :status
                    WHERE incident_id = :incident_id
                    """
                ),
                {
                    "metadata": json.dumps(extra_metadata),
                    "status": incident_status,
                    "incident_id": incident_id,
                },
            )
            await session.commit()

    async def get_pending_fixes(self) -> list:
        async with get_db_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT incident_id, title, severity, declared_at,
                           extra_metadata, status, service_name
                    FROM incidents
                    ORDER BY declared_at DESC
                    LIMIT 200
                    """
                )
            )
            pending = []
            for row in result.fetchall():
                extra = self._parse_metadata(row[4])
                auto_fix = extra.get("auto_fix") or {}
                if not self._is_pending(auto_fix):
                    continue
                code_ctx = auto_fix.get("code_context") or extra.get("code_context") or {}
                pr = auto_fix.get("pr") or {}
                pending.append(
                    {
                        "id": row[0],
                        "incident_id": row[0],
                        "title": row[1],
                        "severity": row[2],
                        "created_at": row[3].isoformat() if row[3] else None,
                        "status": "pending",
                        "service_name": row[6],
                        "file_path": code_ctx.get("file_path")
                        or auto_fix.get("file_path")
                        or "unknown",
                        "line_number": code_ctx.get("line_number")
                        or auto_fix.get("line_number")
                        or 0,
                        "fix_preview": pr.get("fix_preview")
                        or auto_fix.get("fix")
                        or auto_fix.get("diff")
                        or "",
                        "diff": auto_fix.get("diff")
                        or pr.get("fix_preview")
                        or auto_fix.get("fix")
                        or "",
                        "explanation": auto_fix.get("explanation")
                        or pr.get("message")
                        or auto_fix.get("fix")
                        or "",
                        "requires_approval": True,
                    }
                )
            return pending

    async def approve_fix(self, incident_id: str) -> dict:
        """Approve and create the PR (called after human approval)."""
        try:
            from src.services.incident_service import IncidentService

            incident_service = IncidentService()
            incident = await incident_service.get_incident(incident_id)

            if not incident:
                return {"error": "Incident not found"}

            extra_metadata = self._parse_metadata(incident.get("extra_metadata", {}))
            auto_fix = extra_metadata.get("auto_fix", {})
            if not auto_fix or auto_fix.get("error"):
                return {"error": "No fix found for this incident"}

            fix = auto_fix.get("fix")
            file_path = incident.get("file_path") or auto_fix.get("file_path") or "unknown"
            line_number = incident.get("line_number") or auto_fix.get("line_number") or 0
            
            repo_name = auto_fix.get("repo_name")
            if not repo_name:
                logger.error(
                    f"approve_fix: refusing to create PR for incident "
                    f"{incident_id} — no repo_name in auto_fix payload. "
                    f"generate_fix writes this at fix-generation time; "
                    f"its absence means the snapshot is missing."
                )
                return {
                    "error": (
                        "Cannot create PR: the fix has no repo_name "
                        "snapshot. Regenerate the fix so generate_fix "
                        "records a target repository."
                    )
                }

            pr_info = await self.create_pr(
                repo_name=repo_name,
                file_path=file_path,
                line_number=line_number,
                fix=fix,
                incident_id=incident_id,
                require_permission=False,
            )

            auto_fix["approved"] = True
            auto_fix["requires_approval"] = False
            auto_fix["status"] = "approved"
            auto_fix["pr"] = {
                **(auto_fix.get("pr") or {}),
                **pr_info,
                "approval_required": False,
                "status": "approved",
            }
            extra_metadata["auto_fix"] = auto_fix
            await self._update_auto_fix(incident_id, extra_metadata, "fix_approved")

            # Best-effort: write the fix_outcomes row for the Curator.
            # Failure here doesn't affect the approval itself.
            await self._record_outcome(
                incident=incident,
                auto_fix=auto_fix,
                human_decision="approved",
                human_reason=None,
            )
            
            mode = (settings.AUTO_FIX_MODE or "read_only").strip().lower()
            if mode == "read_only":
                message = "✅ Fix approved (PR creation disabled by AUTO_FIX_MODE=read_only)"
            elif mode == "pr_draft":
                message = "✅ Fix approved (PR creation pending GitHub integration — see #30)"
            else:
                message = "✅ Fix approved and PR created!"

            return {
                "status": "approved",
                "pr": pr_info,
                "auto_fix": auto_fix,
                "message": message,
            }

        except Exception as e:
            logger.error(f"Approval error: {e}")
            return {"error": str(e)}

    async def reject_fix(self, incident_id: str, reason: str = None) -> dict:
        """Reject a pending auto-generated fix."""
        try:
            from src.services.incident_service import IncidentService

            incident_service = IncidentService()
            incident = await incident_service.get_incident(incident_id)
            if not incident:
                return {"error": "Incident not found"}

            extra_metadata = self._parse_metadata(incident.get("extra_metadata", {}))
            auto_fix = extra_metadata.get("auto_fix", {})
            if not auto_fix:
                return {"error": "No fix found for this incident"}

            auto_fix["approved"] = False
            auto_fix["requires_approval"] = False
            auto_fix["status"] = "rejected"
            auto_fix["rejected"] = True
            auto_fix["rejection_reason"] = reason
            if auto_fix.get("pr"):
                auto_fix["pr"]["approval_required"] = False
                auto_fix["pr"]["status"] = "rejected"
            extra_metadata["auto_fix"] = auto_fix
            await self._update_auto_fix(
                incident_id, extra_metadata, incident.get("status") or "active"
            )

            # Best-effort: write the fix_outcomes row for the Curator.
            await self._record_outcome(
                incident=incident,
                auto_fix=auto_fix,
                human_decision="rejected",
                human_reason=reason,
            )

            return {
                "status": "rejected",
                "auto_fix": auto_fix,
                "message": "Fix rejected",
            }
        except Exception as e:
            logger.error(f"Reject error: {e}")
            return {"error": str(e)}
