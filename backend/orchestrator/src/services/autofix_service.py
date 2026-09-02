from src.services.github_service import GitHubService
from src.services.llm_service import LLMService
from loguru import logger
import json

class AutoFixService:
    def __init__(self):
        self.github = GitHubService()
        self.llm = LLMService()
        logger.info("✅ AutoFixService initialized")
    
    async def generate_fix(self, incident_data: dict) -> dict:
        """
        Generate a fix and create a PR (requires human approval)
        """
        try:
            # Extract incident details
            service_name = incident_data.get('service_name')
            file_path = incident_data.get('file_path')
            line_number = incident_data.get('line_number')
            error_type = incident_data.get('exception_type')
            root_cause = incident_data.get('root_cause')
            
            if not file_path or not line_number:
                return {"error": "Missing file path or line number"}
            
            # Fetch the actual code from GitHub
            repo_name = incident_data.get('repo_name', 'fastapi')
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
                    {"role": "system", "content": "You are an expert software engineer. Provide code fixes. Always include the exact lines that need to change."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1000
            )
            
            fix_result = response.choices[0].message.content
            
            # Create PR draft (not auto-merged)
            pr_info = await self.create_pr_draft(
                repo_name=repo_name,
                file_path=file_path,
                line_number=line_number,
                fix=fix_result,
                incident_id=incident_data.get('incident_id')
            )
            
            return {
                "status": "fix_generated",
                "requires_approval": True,
                "fix": fix_result,
                "pr": pr_info,
                "code_context": code_context,
                "approval_url": pr_info.get("approval_url")
            }
            
        except Exception as e:
            logger.error(f"Auto-fix error: {e}")
            return {"error": str(e)}
    
    async def create_pr_draft(self, repo_name: str, file_path: str, line_number: int, fix: str, incident_id: str) -> dict:
        """
        Create a Pull Request DRAFT (requires human approval)
        """
        # This would actually create a PR via GitHub API
        # For demo, we'll mock it with approval required
        return {
            "status": "pr_draft_created",
            "pr_number": 12345,
            "pr_url": f"https://github.com/your-org/{repo_name}/pull/12345",
            "approval_url": f"https://github.com/your-org/{repo_name}/pull/12345/approve",
            "branch_name": f"fix/incident-{incident_id}",
            "title": f"[DRAFT] Auto-generated fix for incident {incident_id}",
            "body": f"Auto-generated fix for incident {incident_id}\n\nLine {line_number} in {file_path}\n\n**Requires approval before merging**\n\n{fix}",
            "requires_approval": True
        }
    
    async def approve_and_deploy(self, pr_number: int, repo_name: str) -> dict:
        """
        Approve and deploy a PR (human action required)
        """
        # This would actually approve and deploy
        # For demo, we'll mock it
        return {
            "status": "approved_and_deployed",
            "pr_number": pr_number,
            "deployment_status": "success",
            "deployment_url": f"https://your-deployment-system.com/deploy/{pr_number}",
            "approved_by": "human",
            "timestamp": datetime.utcnow().isoformat()
        }
