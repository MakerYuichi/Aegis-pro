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
        """
        Generate a fix and create a PR (with permission check)
        """
        try:
            # Extract incident details
            service_name = incident_data.get('service_name')
            file_path = incident_data.get('file_path')
            line_number = incident_data.get('line_number')
            error_type = incident_data.get('exception_type')
            root_cause = incident_data.get('root_cause')
            incident_id = incident_data.get('incident_id')
            
            if not file_path or not line_number:
                return {"error": "Missing file path or line number"}
            
            # Fetch the actual code from GitHub
            repo_name = "fastapi"  # This should come from service catalog
            code_context = await self.github.get_file_content(
                repo_name=repo_name,
                file_path=file_path,
                line_number=line_number,
                context_lines=10
            )
            
            if not code_context:
                return {"error": "Failed to fetch code from GitHub"}
            
            # Generate fix using LLM with code context
            prompt = f"""
            You are an expert software engineer. Fix this issue:
            
            Error: {error_type}
            Root Cause: {root_cause}
            File: {file_path}
            Line: {line_number}
            
            Current Code:
            {code_context['code_snippet']}
            
            Please provide:
            1. The fixed code (show the exact changes)
            2. A short explanation of the fix
            3. Any additional context needed
            """
            
            response = await self.llm.client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[
                    {"role": "system", "content": "You are an expert software engineer. Provide code fixes."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1000
            )
            
            fix_result = response.choices[0].message.content
            
            # Create PR (with permission check)
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
        """
        Create a Pull Request with the fix (with permission check)
        """
        # This would actually create a PR via GitHub API
        # For demo, we'll mock it
        
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
    
    async def approve_fix(self, incident_id: str) -> dict:
        """
        Approve and create the PR (called after human approval)
        """
        try:
            # Get the incident
            from src.services.incident_service import IncidentService
            incident_service = IncidentService()
            incident = await incident_service.get_incident(incident_id)
            
            if not incident:
                return {"error": "Incident not found"}
            
            # Get the fix from metadata
            extra_metadata = incident.get('extra_metadata', {})
            if isinstance(extra_metadata, str):
                extra_metadata = json.loads(extra_metadata)
            
            auto_fix = extra_metadata.get('auto_fix', {})
            if not auto_fix or auto_fix.get('error'):
                return {"error": "No fix found for this incident"}
            
            # Create the PR
            fix = auto_fix.get('fix')
            pr_info = await self.create_pr(
                repo_name="fastapi",
                file_path=incident.get('file_path', ''),
                line_number=incident.get('line_number', 1),
                fix=fix,
                incident_id=incident_id,
                require_permission=False
            )
            
            return {
                "status": "approved",
                "pr": pr_info,
                "message": "✅ Fix approved and PR created!"
            }
            
        except Exception as e:
            logger.error(f"Approval error: {e}")
            return {"error": str(e)}
