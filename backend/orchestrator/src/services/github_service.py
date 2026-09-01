from github import Github, Auth
from src.config import settings
from loguru import logger
import httpx

class GitHubService:
    def __init__(self):
        self.client = None
        if settings.GITHUB_TOKEN:
            auth = Auth.Token(settings.GITHUB_TOKEN)
            self.client = Github(auth=auth)
            logger.info("✅ GitHub service initialized")
    
    async def get_recent_prs(self, repo_name: str, hours: int = 24) -> list:
        """Get recent merged PRs"""
        if not self.client:
            return []
        
        try:
            repo = self.client.get_repo(f"{settings.GITHUB_ORG}/{repo_name}")
            prs = []
            for pr in repo.get_pulls(state='closed', sort='updated', direction='desc')[:5]:
                if pr.merged:
                    prs.append({
                        "number": pr.number,
                        "title": pr.title,
                        "author": pr.user.login,
                        "url": pr.html_url,
                        "merged_at": pr.merged_at.isoformat() if pr.merged_at else None
                    })
            return prs
        except Exception as e:
            logger.error(f"GitHub error: {e}")
            return []
    
    async def get_blame(self, repo_name: str, file_path: str, line_number: int) -> dict:
        """Get Git blame for a specific line"""
        if not self.client:
            return {}
        
        try:
            url = f"https://api.github.com/repos/{settings.GITHUB_ORG}/{repo_name}/blame/{file_path}"
            headers = {"Authorization": f"Bearer {settings.GITHUB_TOKEN}"}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    for entry in data:
                        start = entry.get("start", 0)
                        end = entry.get("end", 0)
                        if start <= line_number <= end:
                            commit = entry.get("commit", {})
                            return {
                                "commit_hash": commit.get("sha", "")[:8],
                                "author": commit.get("author", {}).get("name", "Unknown"),
                                "message": commit.get("commit", {}).get("message", "").split("\n")[0]
                            }
            return {}
        except Exception as e:
            logger.error(f"Git blame error: {e}")
            return {}
