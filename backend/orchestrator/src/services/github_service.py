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
    
    async def _get_repo(self, repo_name: str):
        """Find a repository dynamically"""
        if not self.client:
            return None
        
        if '/' in repo_name:
            try:
                return self.client.get_repo(repo_name)
            except Exception:
                pass
        
        if settings.GITHUB_ORG:
            try:
                return self.client.get_repo(f"{settings.GITHUB_ORG}/{repo_name}")
            except Exception:
                pass
        
        try:
            query = f"{repo_name} in:name"
            result = self.client.search_repositories(query, sort='stars', order='desc')
            for repo in result[:5]:
                if repo.name.lower() == repo_name.lower() or repo_name.lower() in repo.full_name.lower():
                    logger.info(f"Found repository: {repo.full_name}")
                    return repo
                if repo.name.lower().startswith(repo_name.lower()) or repo.full_name.lower().endswith(f"/{repo_name.lower()}"):
                    logger.info(f"Found repository: {repo.full_name}")
                    return repo
            for repo in result[:5]:
                logger.info(f"Found repository via search: {repo.full_name}")
                return repo
        except Exception as e:
            logger.debug(f"Search failed: {e}")
        
        return None
    
    async def get_recent_prs(self, repo_name: str, hours: int = 24) -> list:
        """Get recent merged PRs from ANY public repo"""
        if not self.client:
            logger.warning("GitHub client not initialized")
            return []
        
        try:
            repo = await self._get_repo(repo_name)
            if not repo:
                logger.warning(f"Repository {repo_name} not found")
                return []
            
            prs = []
            for pr in repo.get_pulls(state='closed', sort='updated', direction='desc')[:10]:
                if pr.merged:
                    prs.append({
                        "number": pr.number,
                        "title": pr.title,
                        "author": pr.user.login,
                        "url": pr.html_url,
                        "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
                        "additions": pr.additions,
                        "deletions": pr.deletions,
                        "files": [f.filename for f in pr.get_files()[:5]]
                    })
            
            logger.info(f"Found {len(prs)} recent PRs for {repo_name}")
            return prs
            
        except Exception as e:
            logger.error(f"GitHub error fetching {repo_name}: {e}")
            return []
    
    async def get_blame_with_pr(self, repo_name: str, file_path: str, line_number: int) -> dict:
        """Get Git blame AND the associated PR using commit history (most reliable)"""
        if not self.client:
            return {}
        
        try:
            repo = await self._get_repo(repo_name)
            if not repo:
                return {}
            
            # Try multiple approaches to find the commit
            
            # Approach 1: Get commit history for the file with exact path
            try:
                commits = repo.get_commits(path=file_path)
                if commits.totalCount > 0:
                    commit = commits[0]  # Get the most recent commit
                    pr_info = await self._find_pr_for_commit(repo, commit.sha)
                    result = {
                        "commit_hash": commit.sha[:8],
                        "author": commit.author.login if commit.author else "Unknown",
                        "message": commit.commit.message.split("\n")[0][:100],
                        "line": line_number,
                        "file": file_path,
                    }
                    if pr_info:
                        result.update({
                            "pr_number": pr_info.get("number"),
                            "pr_title": pr_info.get("title"),
                            "pr_url": pr_info.get("url"),
                            "pr_author": pr_info.get("author")
                        })
                        logger.info(f"✅ Found PR #{pr_info.get('number')} for commit {commit.sha[:8]}")
                    else:
                        logger.info(f"✅ Found commit {commit.sha[:8]} but no PR associated")
                    return result
            except Exception as e:
                logger.debug(f"Commit history approach failed: {e}")
            
            # Approach 2: Try with different path variants
            path_variants = [
                file_path,
                file_path.replace('fastapi/', ''),
                file_path.split('/')[-1] if '/' in file_path else file_path
            ]
            
            for variant in path_variants:
                try:
                    commits = repo.get_commits(path=variant)
                    if commits.totalCount > 0:
                        commit = commits[0]
                        pr_info = await self._find_pr_for_commit(repo, commit.sha)
                        result = {
                            "commit_hash": commit.sha[:8],
                            "author": commit.author.login if commit.author else "Unknown",
                            "message": commit.commit.message.split("\n")[0][:100],
                            "line": line_number,
                            "file": file_path,
                        }
                        if pr_info:
                            result.update({
                                "pr_number": pr_info.get("number"),
                                "pr_title": pr_info.get("title"),
                                "pr_url": pr_info.get("url"),
                                "pr_author": pr_info.get("author")
                            })
                            logger.info(f"✅ Found PR #{pr_info.get('number')} for commit {commit.sha[:8]} (variant: {variant})")
                        return result
                except Exception as e:
                    continue
            
            # Approach 3: Try blame API as fallback
            try:
                full_repo = repo.full_name
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
                                commit_sha = commit.get("sha", "")
                                author = commit.get("author", {}).get("name", "Unknown")
                                message = commit.get("commit", {}).get("message", "").split("\n")[0]
                                
                                pr_info = await self._find_pr_for_commit(repo, commit_sha)
                                result = {
                                    "commit_hash": commit_sha[:8],
                                    "author": author,
                                    "message": message,
                                    "line": line_number,
                                    "file": file_path,
                                }
                                if pr_info:
                                    result.update({
                                        "pr_number": pr_info.get("number"),
                                        "pr_title": pr_info.get("title"),
                                        "pr_url": pr_info.get("url"),
                                        "pr_author": pr_info.get("author")
                                    })
                                logger.info(f"✅ Found blame via API for {file_path}")
                                return result
            except Exception as e:
                logger.debug(f"Blame API approach failed: {e}")
            
            return {}
            
        except Exception as e:
            logger.error(f"Git blame error: {e}")
            return {}
    
    async def _find_pr_for_commit(self, repo, commit_sha: str) -> dict:
        """Find the PR that introduced a commit"""
        try:
            commit = repo.get_commit(commit_sha)
            prs = commit.get_pulls()
            for pr in prs:
                return {
                    "number": pr.number,
                    "title": pr.title,
                    "url": pr.html_url,
                    "author": pr.user.login
                }
            return {}
        except Exception as e:
            logger.debug(f"PR lookup error: {e}")
            return {}