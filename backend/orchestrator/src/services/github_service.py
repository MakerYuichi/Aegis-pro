from github import Github, Auth
from src.config import settings
from loguru import logger
import httpx

class GitHubService:
    def __init__(self):
        self.client = None
        if settings.GITHUB_TOKEN:
            try:
                auth = Auth.Token(settings.GITHUB_TOKEN)
                self.client = Github(auth=auth)
                logger.info("✅ GitHub service initialized")
            except Exception as e:
                logger.error(f"GitHub init error: {e}")
        else:
            logger.warning("⚠️ GitHub token not configured")
    
    async def get_recent_prs(self, repo_name: str, hours: int = 24) -> list:
        """Get recent merged PRs from ANY public repo"""
        if not self.client:
            logger.warning("GitHub client not initialized")
            return []
        
        try:
            # If repo_name contains '/', use it directly (owner/repo format)
            if '/' in repo_name:
                full_repo = repo_name
            elif settings.GITHUB_ORG:
                full_repo = f"{settings.GITHUB_ORG}/{repo_name}"
            else:
                full_repo = repo_name
            
            logger.info(f"Attempting to fetch PRs from: {full_repo}")
            repo = self.client.get_repo(full_repo)
            
            if not repo:
                return []
            
            prs = []
            for pr in repo.get_pulls(state='closed', sort='updated', direction='desc')[:5]:
                if pr.merged:
                    prs.append({
                        "number": pr.number,
                        "title": pr.title,
                        "author": pr.user.login,
                        "url": pr.html_url,
                        "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
                        "additions": pr.additions,
                        "deletions": pr.deletions
                    })
            
            logger.info(f"Found {len(prs)} recent PRs for {full_repo}")
            return prs
            
        except Exception as e:
            logger.error(f"GitHub error fetching {repo_name}: {e}")
            return []
    
    async def get_blame(self, repo_name: str, file_path: str, line_number: int) -> dict:
        """Get Git blame for a specific line"""
        if not self.client:
            return {}
        
        try:
            if '/' in repo_name:
                full_repo = repo_name
            elif settings.GITHUB_ORG:
                full_repo = f"{settings.GITHUB_ORG}/{repo_name}"
            else:
                full_repo = repo_name
            
            url = f"https://api.github.com/repos/{full_repo}/blame/{file_path}"
            headers = {"Authorization": f"Bearer {settings.GITHUB_TOKEN}"}
            
            async with httpx.AsyncClient(timeout=10.0) as client:
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
                                "email": commit.get("author", {}).get("email", ""),
                                "message": commit.get("commit", {}).get("message", "").split("\n")[0],
                                "date": commit.get("commit", {}).get("author", {}).get("date", ""),
                                "line": line_number,
                                "file": file_path
                            }
                else:
                    logger.error(f"Git blame API error: {response.status_code}")
            
            return {}
            
        except Exception as e:
            logger.error(f"Git blame error: {e}")
            return {}