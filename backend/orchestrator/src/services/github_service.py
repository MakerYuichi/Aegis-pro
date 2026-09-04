from github import Github, Auth
from src.config import settings
from src.services.llm_service import LLMService
from loguru import logger
import httpx
import re
import json

class GitHubService:
    def __init__(self):
        self.client = None
        self.llm = None
        
        # Initialize LLM
        try:
            self.llm = LLMService()
            if self.llm.client:
                logger.info("✅ GitHub service initialized with LLM")
            else:
                logger.warning("⚠️ LLM client not available")
        except Exception as e:
            logger.warning(f"⚠️ LLM not available: {e}")
            self.llm = None
            
        # Initialize GitHub
        if settings.GITHUB_TOKEN:
            try:
                auth = Auth.Token(settings.GITHUB_TOKEN)
                self.client = Github(auth=auth)
                logger.info("✅ GitHub client initialized")
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
        """Find TOP 5 PRs related to a specific file/line using LLM scoring"""
        try:
            repo = await self._get_repo(repo_name)
            if not repo:
                return []
            
            related_prs = []
            seen_prs = set()
            candidates = []
            
            # Get PRs that modified this file (from commit history) - LIMIT TO 10
            try:
                commits = repo.get_commits(path=file_path)
                for commit in commits[:10]:
                    prs = commit.get_pulls()
                    for pr in prs:
                        if pr.number not in seen_prs:
                            seen_prs.add(pr.number)
                            candidates.append({
                                "number": pr.number,
                                "title": pr.title,
                                "author": pr.user.login,
                                "url": pr.html_url,
                                "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
                                "files": [f.filename for f in pr.get_files()[:5]]
                            })
            except Exception as e:
                logger.debug(f"Error getting file PRs: {e}")
            
            # If not enough candidates, get recent PRs from the repo - LIMIT TO 15
            if len(candidates) < 3:
                try:
                    for pr in repo.get_pulls(state='closed', sort='updated', direction='desc')[:15]:
                        if pr.number in seen_prs:
                            continue
                        seen_prs.add(pr.number)
                        candidates.append({
                            "number": pr.number,
                            "title": pr.title,
                            "author": pr.user.login,
                            "url": pr.html_url,
                            "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
                            "files": [f.filename for f in pr.get_files()[:5]]
                        })
                        if len(candidates) >= 8:
                            break
                except:
                    pass
            
            if not candidates:
                return []
            
            # If too many candidates, filter to only those that modified the target file
            if len(candidates) > 8:
                filtered = [c for c in candidates if any(f == file_path for f in c.get('files', []))]
                if len(filtered) >= 3:
                    candidates = filtered[:8]
                else:
                    candidates = candidates[:8]
            
            # Score candidates using LLM
            scored = await self._score_candidates(candidates, file_path, line_number)
            
            # Filter and return top 5
            scored = [c for c in scored if c.get('relevance_score', 0) > 0.3]
            return scored[:limit]
            
        except Exception as e:
            logger.error(f"Error getting related PRs: {e}")
            return []
    
    async def _score_candidates(self, candidates: list, file_path: str, line_number: int) -> list:
        """Score candidates using LLM first, then fallback to heuristics"""
        
        # Try LLM if available
        if self.llm and self.llm.client:
            try:
                scored = await self._score_with_llm(candidates, file_path, line_number)
                if scored:
                    logger.info(f"✅ LLM scored {len(scored)} PRs")
                    return scored
            except Exception as e:
                logger.warning(f"⚠️ LLM scoring failed: {e}")
        
        # Fallback to heuristics
        logger.info("Using heuristic fallback for relevance scoring")
        return self._score_with_heuristics(candidates, file_path)
    
    async def _score_with_llm(self, candidates: list, file_path: str, line_number: int) -> list:
        """Score PRs using LLM with detailed context and specific reasons"""
        try:
            # Limit to 6 candidates for LLM to avoid timeout
            candidates_small = candidates[:6]
            
            # Build detailed PR list with more context
            pr_list = []
            for p in candidates_small:
                pr_details = {
                    "number": p["number"],
                    "title": p["title"][:200],
                    "files": p["files"][:5],
                    "author": p.get("author", "unknown")
                }
                
                # Try to get PR description and more details
                try:
                    repo = await self._get_repo("fastapi/fastapi")
                    if repo:
                        pr = repo.get_pull(p["number"])
                        pr_details["description"] = pr.body[:500] if pr.body else "No description provided"
                        pr_details["additions"] = pr.additions
                        pr_details["deletions"] = pr.deletions
                        pr_details["changed_files"] = [f.filename for f in pr.get_files()[:5]]
                        pr_details["modified_target_file"] = any(f.filename == file_path for f in pr.get_files()[:10])
                except Exception as e:
                    logger.debug(f"Could not fetch PR details for #{p['number']}: {e}")
                
                pr_list.append(pr_details)
            
            prompt = f"""
You are a senior software engineer analyzing which GitHub Pull Request (PR) most likely caused a NullPointerException.

**Error Location:** {file_path}, line {line_number}

**What happened:** A NullPointerException occurred at line {line_number} in {file_path}. This means code tried to access a method/property on an object that was null.

**PRs that modified this file or related files:**
{json.dumps(pr_list, indent=2)}

**Analysis Criteria:**
1. Did the PR modify the exact file `{file_path}`?
2. Did the PR change code around line {line_number} specifically?
3. Did the PR remove a null check, add a new dependency, or change data structures?
4. Did the PR introduce new code that could create null values?
5. How large was the change? (additions/deletions)

**Scoring Guidelines:**
- **0.90-1.00**: PR directly modified the exact line or function where the error occurred
- **0.70-0.89**: PR modified the same file but different function/area
- **0.50-0.69**: PR modified a related file or dependency
- **0.30-0.49**: PR touched the same repo but seems unrelated
- **0.00-0.29**: PR is completely unrelated

**Return ONLY JSON array with ALL PRs scored. Include specific, detailed reasons:**

[
    {{"number": 123, "score": 0.95, "reason": "This PR modified the exact file {file_path} at line {line_number}, removing a null check that was critical. This directly caused the NullPointerException."}},
    {{"number": 456, "score": 0.78, "reason": "This PR modified {file_path} but in a different function. It likely changed the data structure used at line {line_number}, making the null check fail."}},
    {{"number": 789, "score": 0.45, "reason": "This PR modified a different file but the change affects how the function at line {line_number} is called."}}
]

Score ALL {len(pr_list)} PRs. Be specific about what changed and why it might cause the error. Include the file name and line number in your reasoning.
"""
            
            # Use groq/compound which we know works
            response = self.llm.client.chat.completions.create(
                model="groq/compound",
                messages=[
                    {"role": "system", "content": "You are a senior software engineer analyzing code changes. Return ONLY valid JSON array with specific, detailed reasons. Include file names and line numbers in your reasoning. No other text."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1500
            )
            
            content = response.choices[0].message.content
            logger.info(f"LLM response length: {len(content)}")
            
            # Try to parse JSON
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                try:
                    scores = json.loads(json_match.group())
                    if not isinstance(scores, list):
                        raise ValueError("Not a list")
                    
                    score_map = {s["number"]: s for s in scores if "number" in s}
                    
                    for candidate in candidates:
                        if candidate["number"] in score_map:
                            sc = score_map[candidate["number"]]
                            candidate["relevance_score"] = round(max(0.1, min(1.0, float(sc.get("score", 0.5)))), 2)
                            candidate["reason"] = sc.get("reason", "LLM analyzed")[:300]
                        else:
                            candidate["relevance_score"] = 0.3
                            candidate["reason"] = "Not scored by LLM"
                    
                    candidates.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
                    return candidates
                    
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error: {e}")
                    logger.error(f"Content: {content[:500]}")
                    return None
            else:
                logger.warning(f"No JSON array found in: {content[:100] if content else 'empty'}")
                return None
            
        except Exception as e:
            logger.error(f"LLM scoring error: {e}")
            return None
    
    def _score_with_heuristics(self, candidates: list, file_path: str) -> list:
        """Fallback heuristic scoring - only used when LLM fails"""
        file_name = file_path.split('/')[-1]
        file_base = file_name.split('.')[0]
        
        for c in candidates:
            score = 0.3
            reason = "General relevance"
            
            if any(f == file_path for f in c.get('files', [])):
                score = 0.7
                reason = f"Modified {file_path}"
                
                if file_base in c.get('title', ''):
                    score = 0.85
                    reason = f"Modified {file_path} and title mentions {file_base}"
            
            elif any(file_base in f for f in c.get('files', [])):
                score = 0.5
                reason = f"Modified related file (contains {file_base})"
            
            elif file_base in c.get('title', ''):
                score = 0.45
                reason = f"Title mentions {file_base}"
            
            c['relevance_score'] = score
            c['reason'] = reason
        
        candidates.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
        return candidates
    
    async def _get_pr_contributors(self, repo, pr_number: int) -> list:
        """Get ALL contributors for a PR"""
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
            except:
                pass
            
            for assignee in pr.assignees:
                if assignee.login not in added_usernames:
                    contributors.append({
                        "username": assignee.login,
                        "role": "assignee",
                        "avatar": assignee.avatar_url,
                        "url": assignee.html_url
                    })
                    added_usernames.add(assignee.login)
            
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
            except:
                pass
            
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