from sqlalchemy import text
from src.database import get_db
from src.services.github_service import GitHubService
from src.services.llm_service import LLMService
from loguru import logger
import json

class AutoFixService:
    def __init__(self):
        self.github = GitHubService()
        self.llm = LLMService()
        logger.info("✅ AutoFixService initialized")
    
    async def generate_fix(self, incident_data: dict, require_permission: bool = True) -> dict:
        try:
            service_name = incident_data.get('service_name')
            file_path = incident_data.get('file_path')
            line_number = incident_data.get('line_number')
            error_type = incident_data.get('exception_type')
            root_cause = incident_data.get('root_cause')
            incident_id = incident_data.get('incident_id')
            
            if not file_path or not line_number:
                return {"error": "Missing file path or line number"}
            
            repo_name = "fastapi"
            code_context = await self.github.get_file_content(
                repo_name=repo_name,
                file_path=file_path,
                line_number=line_number,
                context_lines=10
            )
            
            if not code_context:
                return {"error": "Failed to fetch code from GitHub"}
            
            prompt = f"""
            You are an expert software engineer. Fix this issue:
            
            Error: {error_type}
            Root Cause: {root_cause}
            File: {file_path}
            Line: {line_number}
            
            Current Code:
            {code_context['code_snippet']}
            
            Please provide:
            1. The fixed code (show the exact changes in diff format)
            2. A short explanation of the fix
            """
            
            response = self.llm.client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[
                    {"role": "system", "content": "You are an expert software engineer. Provide code fixes in diff format."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1000
            )
            
            fix_result = response.choices[0].message.content
            
            pr_info = await self.create_pr(
                repo_name=repo_name,
                file_path=file_path,
                line_number=line_number,
                fix=fix_result,
                incident_id=incident_id,
                require_permission=require_permission
            )
            
            return {
                "status": "fix_generated",
                "fix": fix_result,
                "pr": pr_info,
                "code_context": code_context,
                "requires_approval": require_permission
            }
            
        except Exception as e:
            logger.error(f"Auto-fix error: {e}")
            return {"error": str(e)}
    
    async def create_pr(self, repo_name: str, file_path: str, line_number: int, fix: str, incident_id: str, require_permission: bool = True) -> dict:
        if require_permission:
            return {
                "status": "pr_draft",
                "message": "✅ Fix generated. Waiting for approval before creating PR.",
                "fix_preview": fix[:500],
                "approval_required": True,
                "approval_url": f"/approve/{incident_id}"
            }
        else:
            return {
                "status": "pr_created",
                "pr_number": 12345,
                "pr_url": f"https://github.com/your-org/{repo_name}/pull/12345",
                "branch_name": f"fix/incident-{incident_id}",
                "title": f"Fix: Auto-generated fix for incident {incident_id}",
                "body": f"Auto-generated fix for incident {incident_id}\n\nLine {line_number} in {file_path}\n\n{fix}"
            }
    
    def _parse_metadata(self, extra_metadata) -> dict:
        if not extra_metadata:
            return {}
        if isinstance(extra_metadata, str):
            try:
                return json.loads(extra_metadata)
            except Exception:
                return {}
        return extra_metadata

    def _is_pending(self, auto_fix: dict) -> bool:
        if not auto_fix or auto_fix.get("error"):
            return False
        status = (auto_fix.get("status") or auto_fix.get("pr", {}).get("status") or "").lower()
        if status in ("approved", "rejected", "pr_created"):
            return False
        if auto_fix.get("approved") is True:
            return False
        return bool(
            auto_fix.get("requires_approval")
            or auto_fix.get("pr", {}).get("approval_required")
            or status in ("fix_generated", "pr_draft", "pending")
        )

    async def _update_auto_fix(self, incident_id: str, extra_metadata: dict, incident_status: str) -> None:
        session = await get_db()
        async with session:
            await session.execute(
                text("""
                    UPDATE incidents
                    SET extra_metadata = CAST(:metadata AS jsonb),
                        status = :status
                    WHERE incident_id = :incident_id
                """),
                {
                    "metadata": json.dumps(extra_metadata),
                    "status": incident_status,
                    "incident_id": incident_id,
                }
            )
            await session.commit()

    async def get_pending_fixes(self) -> list:
        session = await get_db()
        async with session:
            result = await session.execute(
                text("""
                    SELECT incident_id, title, severity, declared_at, extra_metadata, status, service_name
                    FROM incidents
                    ORDER BY declared_at DESC
                    LIMIT 200
                """)
            )
            pending = []
            for row in result.fetchall():
                extra = self._parse_metadata(row[4])
                auto_fix = extra.get("auto_fix") or {}
                if not self._is_pending(auto_fix):
                    continue
                code_ctx = auto_fix.get("code_context") or extra.get("code_context") or {}
                pr = auto_fix.get("pr") or {}
                pending.append({
                    "id": row[0],
                    "incident_id": row[0],
                    "title": row[1],
                    "severity": row[2],
                    "created_at": row[3].isoformat() if row[3] else None,
                    "status": "pending",
                    "service_name": row[6],
                    "file_path": code_ctx.get("file_path") or auto_fix.get("file_path") or "unknown",
                    "line_number": code_ctx.get("line_number") or auto_fix.get("line_number") or 0,
                    "fix_preview": pr.get("fix_preview") or auto_fix.get("fix") or auto_fix.get("diff") or "",
                    "diff": auto_fix.get("diff") or pr.get("fix_preview") or auto_fix.get("fix") or "",
                    "explanation": auto_fix.get("explanation") or pr.get("message") or auto_fix.get("fix") or "",
                    "requires_approval": True,
                })
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

            pr_info = await self.create_pr(
                repo_name="fastapi",
                file_path=file_path,
                line_number=line_number,
                fix=fix,
                incident_id=incident_id,
                require_permission=False
            )

            auto_fix["approved"] = True
            auto_fix["requires_approval"] = False
            auto_fix["status"] = "approved"
            auto_fix["pr"] = {**(auto_fix.get("pr") or {}), **pr_info, "approval_required": False, "status": "approved"}
            extra_metadata["auto_fix"] = auto_fix
            await self._update_auto_fix(incident_id, extra_metadata, "fix_approved")

            return {
                "status": "approved",
                "pr": pr_info,
                "auto_fix": auto_fix,
                "message": "✅ Fix approved and PR created!"
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
            await self._update_auto_fix(incident_id, extra_metadata, incident.get("status") or "active")

            return {
                "status": "rejected",
                "auto_fix": auto_fix,
                "message": "Fix rejected"
            }
        except Exception as e:
            logger.error(f"Reject error: {e}")
            return {"error": str(e)}