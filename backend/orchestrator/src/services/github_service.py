from github import Github, Auth
from src.config import settings
from loguru import logger
import httpx
import re

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
        """Get Git blame AND the associated PR using commit history"""
        if not self.client:
            return {}
        
        try:
            repo = await self._get_repo(repo_name)
            if not repo:
                return {}
            
            logger.info(f"🔍 Getting blame for: {file_path}:{line_number}")
            
            # Approach 1: Get commit history for the file with exact path
            try:
                commits = repo.get_commits(path=file_path)
                logger.info(f"📝 Found {commits.totalCount} commits for {file_path}")
                
                if commits.totalCount > 0:
                    commit = commits[0]
                    pr_info = await self._find_pr_for_commit(repo, commit.sha)
                    
                    result = {
                        "commit_hash": commit.sha[:8],
                        "author": commit.author.login if commit.author else "Unknown",
                        "author_avatar": commit.author.avatar_url if commit.author else None,
                        "message": commit.commit.message.split("\n")[0][:100],
                        "line": line_number,
                        "file": file_path,
                    }
                    
                    if pr_info:
                        pr_number = pr_info.get("number")
                        contributors = await self._get_pr_contributors(repo, pr_number)
                        result.update({
                            "pr_number": pr_number,
                            "pr_title": pr_info.get("title"),
                            "pr_url": pr_info.get("url"),
                            "pr_author": pr_info.get("author"),
                            "contributors": contributors,
                        })
                        logger.info(f"✅ Found PR #{pr_number} for commit {commit.sha[:8]}")
                    else:
                        logger.info(f"✅ Found commit {commit.sha[:8]} but no PR associated")
                    
                    return result
                    
            except Exception as e:
                logger.error(f"Error getting commits: {e}")
            
            return {}
            
        except Exception as e:
            logger.error(f"Git blame error: {e}")
            return {}
    
    async def get_related_prs(self, repo_name: str, file_path: str, line_number: int, limit: int = 5) -> list:
        """Find PRs that are related to a specific file/line"""
        try:
            repo = await self._get_repo(repo_name)
            if not repo:
                return []
            
            related_prs = []
            seen_prs = set()
            
            # 1. Get PRs that modified this file
            try:
                commits = repo.get_commits(path=file_path)
                for commit in commits[:20]:
                    prs = commit.get_pulls()
                    for pr in prs:
                        if pr.number not in seen_prs:
                            seen_prs.add(pr.number)
                            relevance = await self._calculate_relevance(pr, file_path, line_number)
                            related_prs.append({
                                "number": pr.number,
                                "title": pr.title,
                                "author": pr.user.login,
                                "url": pr.html_url,
                                "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
                                "relevance_score": relevance,
                                "reason": f"Modified {file_path}",
                                "files": [f.filename for f in pr.get_files()[:5]]
                            })
            except Exception as e:
                logger.debug(f"Error getting file PRs: {e}")
            
            # 2. Get PRs with similar commit messages
            try:
                for pr in repo.get_pulls(state='closed', sort='updated', direction='desc')[:30]:
                    if pr.number in seen_prs:
                        continue
                    
                    relevance = await self._calculate_message_relevance(pr, file_path)
                    if relevance > 0.5:
                        seen_prs.add(pr.number)
                        related_prs.append({
                            "number": pr.number,
                            "title": pr.title,
                            "author": pr.user.login,
                            "url": pr.html_url,
                            "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
                            "relevance_score": relevance,
                            "reason": f"Related keywords",
                            "files": [f.filename for f in pr.get_files()[:5]]
                        })
            except Exception as e:
                logger.debug(f"Error getting message PRs: {e}")
            
            # Sort by relevance score
            related_prs.sort(key=lambda x: x['relevance_score'], reverse=True)
            return related_prs[:limit]
            
        except Exception as e:
            logger.error(f"Error getting related PRs: {e}")
            return []
    
    async def _calculate_relevance(self, pr, file_path: str, line_number: int) -> float:
        """Calculate how relevant a PR is to a specific line"""
        score = 0.0
        
        # Check if PR modified the exact file
        try:
            files = pr.get_files()
            for f in files:
                if f.filename == file_path:
                    score += 0.6
                    if f.patch:
                        import re
                        lines = re.findall(r'@@ -\d+,\d+ \+(\d+),', f.patch)
                        for line in lines:
                            if abs(int(line) - line_number) < 20:
                                score += 0.3
                                break
                    break
        except:
            pass
        
        return min(score, 1.0)
    
    async def _calculate_message_relevance(self, pr, file_path: str) -> float:
        """Calculate relevance based on PR title/body"""
        score = 0.0
        keywords = file_path.split('/')[-1].replace('.', ' ').split()
        
        title_lower = pr.title.lower()
        for kw in keywords:
            if kw.lower() in title_lower:
                score += 0.3
        
        if pr.body:
            body_lower = pr.body.lower()
            for kw in keywords:
                if kw.lower() in body_lower:
                    score += 0.2
        
        return min(score, 1.0)
    
    async def _get_pr_contributors(self, repo, pr_number: int) -> list:
        """Get ALL contributors for a PR: author, reviewers, assignees, committers"""
        try:
            logger.info(f"🔍 Fetching contributors for PR #{pr_number}")
            pr = repo.get_pull(pr_number)
            contributors = []
            added_usernames = set()
            
            if pr.user:
                contributors.append({
                    "username": pr.user.login,
                    "role": "author",
                    "avatar": pr.user.avatar_url,
                    "url": pr.user.html_url
                })
                added_usernames.add(pr.user.login)
                logger.info(f"   Author: {pr.user.login}")
            
            try:
                reviews = pr.get_reviews()
                for review in reviews:
                    if review.user and review.user.login not in added_usernames:
                        contributors.append({
                            "username": review.user.login,
                            "role": "reviewer",
                            "avatar": review.user.avatar_url,
                            "url": review.user.html_url
                        })
                        added_usernames.add(review.user.login)
                        logger.info(f"   Reviewer: {review.user.login}")
            except Exception as e:
                logger.debug(f"Error getting reviewers: {e}")
            
            for assignee in pr.assignees:
                if assignee.login not in added_usernames:
                    contributors.append({
                        "username": assignee.login,
                        "role": "assignee",
                        "avatar": assignee.avatar_url,
                        "url": assignee.html_url
                    })
                    added_usernames.add(assignee.login)
                    logger.info(f"   Assignee: {assignee.login}")
            
            try:
                commits = pr.get_commits()
                for commit in commits:
                    if commit.author and commit.author.login not in added_usernames:
                        contributors.append({
                            "username": commit.author.login,
                            "role": "committer",
                            "avatar": commit.author.avatar_url,
                            "url": commit.author.html_url
                        })
                        added_usernames.add(commit.author.login)
                        logger.info(f"   Committer: {commit.author.login}")
            except Exception as e:
                logger.debug(f"Error getting commit authors: {e}")
            
            logger.info(f"✅ Found {len(contributors)} contributors for PR #{pr_number}")
            return contributors
            
        except Exception as e:
            logger.error(f"Error getting PR contributors: {e}")
            return []
    
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
        
    async def get_file_content(self, repo_name: str, file_path: str, line_number: int, context_lines: int = 5) -> dict:
        """Fetch the actual code around the error line from GitHub"""
        if not self.client:
            return {}
        
        try:
            repo = await self._get_repo(repo_name)
            if not repo:
                return {}
            
            content = repo.get_contents(file_path)
            lines = content.decoded_content.decode().split('\n')
            
            start = max(0, line_number - context_lines - 1)
            end = min(len(lines), line_number + context_lines)
            
            code_snippet = []
            for i in range(start, end):
                line_num = i + 1
                marker = ">>> " if i == line_number - 1 else "    "
                code_snippet.append(f"{line_num:4d} {marker}{lines[i]}")
            
            return {
                "file_path": file_path,
                "line_number": line_number,
                "total_lines": len(lines),
                "code_snippet": "\n".join(code_snippet),
                "full_file": "\n".join(lines) if len(lines) < 100 else None
            }
            
        except Exception as e:
            logger.error(f"Error fetching file content: {e}")
            return {}
