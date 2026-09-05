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
            
            seen_prs = set()
            candidates = []
            
            # Get PRs that modified this file (from commit history)
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
            
            # If not enough candidates, get recent PRs from the repo
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
            
            # Score candidates using LLM - USE THE LLM SERVICE!
            scored = await self._score_candidates_with_llm_service(candidates, file_path, line_number)
            
            # Filter and return top 5
            scored = [c for c in scored if c.get('relevance_score', 0) > 0.3]
            return scored[:limit]
            
        except Exception as e:
            logger.error(f"Error getting related PRs: {e}")
            return []
    
    async def _score_candidates_with_llm_service(self, candidates: list, file_path: str, line_number: int) -> list:
        """Score candidates using the LLM service (which handles fallbacks)"""
        
        if not self.llm:
            logger.warning("LLM service not available, using heuristics")
            return self._score_with_heuristics(candidates, file_path)
        
        try:
            # Build PR list for scoring
            pr_list = []
            for p in candidates[:6]:
                pr_list.append({
                    "number": p["number"],
                    "title": p["title"][:200],
                    "files": p["files"][:3],
                    "author": p.get("author", "unknown")
                })
            
            prompt = f"""
You are a senior software engineer analyzing which GitHub Pull Request most likely caused a NullPointerException.

**Error Location:** {file_path}, line {line_number}

**Context:** A NullPointerException means code tried to access a method or property on a null object at line {line_number} in {file_path}.

**PRs that modified this file or related files:**
{json.dumps(pr_list, indent=2)}

**Analyze each PR based on:**
1. Did it modify the exact file `{file_path}`?
2. Did it change code around line {line_number} specifically?
3. Did it remove, add, or modify null checks?
4. Did it change data structures, imports, or initialization?
5. How large was the change? (additions/deletions)

**Scoring Guidelines:**
- 0.90-1.00: Directly modified the exact line or function where error occurred
- 0.70-0.89: Modified the same file but different function/area
- 0.50-0.69: Modified a related file or dependency
- 0.30-0.49: Touched same repo but seems unrelated

**Return ONLY JSON array with ALL PRs scored. Use exact scores (e.g., 0.87, 0.93, 0.76):**
[
    {{"number": 123, "score": 0.87, "reason": "PR #123 modified the exact file {file_path} at line {line_number} and removed a critical null check, directly causing the NullPointerException."}},
    {{"number": 456, "score": 0.73, "reason": "PR #456 modified the same file {file_path} but in a different function. The change likely affected the data structure used at line {line_number}, making the null check fail."}}
]

Provide specific, detailed reasons for each PR. Mention the file name, line number, and what specifically changed.
"""
            
            # Try Gemini first (if available)
            if self.llm.gemini_client:
                logger.info("Using Google Gemini for PR scoring...")
                try:
                    response = self.llm.gemini_client.generate_content(prompt)
                    content = response.text
                    json_match = re.search(r'\[.*\]', content, re.DOTALL)
                    if json_match:
                        result = json.loads(json_match.group())
                        logger.info("✅ Gemini PR scoring succeeded")
                        return self._process_llm_result(candidates, result)
                except Exception as e:
                    logger.warning(f"Gemini PR scoring failed: {e}")
            
            # Try OpenRouter
            if self.llm.openrouter_api_key:
                logger.info("Using OpenRouter for PR scoring...")
                result = await self._call_openrouter_for_scoring(prompt)
                if result:
                    return self._process_llm_result(candidates, result)
            
            # Fallback to Groq
            if self.llm.client:
                logger.info("Using Groq for PR scoring...")
                result = await self._call_groq_for_scoring(prompt)
                if result:
                    return self._process_llm_result(candidates, result)
            
            # Final fallback to heuristics
            logger.info("Using heuristic fallback for relevance scoring")
            return self._score_with_heuristics(candidates, file_path)
            
        except Exception as e:
            logger.error(f"LLM scoring error: {e}")
            return self._score_with_heuristics(candidates, file_path)
    
    async def _call_openrouter_for_scoring(self, prompt):
        """Call OpenRouter for PR scoring"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.llm.openrouter_api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "http://localhost:8000",
                        "X-Title": "AEGIS PRO"
                    },
                    json={
                        "model": self.llm.openrouter_model,
                        "messages": [
                            {"role": "system", "content": "You are a senior software engineer. Return ONLY valid JSON array with specific, detailed reasons for each score."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.3,
                        "max_tokens": 800
                    }
                )
                if response.status_code == 200:
                    data = response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    json_match = re.search(r'\[.*\]', content, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group())
        except Exception as e:
            logger.warning(f"OpenRouter scoring failed: {e}")
        return None
    
    async def _call_groq_for_scoring(self, prompt):
        """Call Groq for PR scoring through LLM service"""
        try:
            for model in self.llm.models:
                try:
                    response = self.llm.client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": "Return ONLY valid JSON array with specific, detailed reasons."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.3,
                        max_tokens=800
                    )
                    content = response.choices[0].message.content
                    json_match = re.search(r'\[.*\]', content, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group())
                except Exception as e:
                    continue
        except Exception as e:
            logger.warning(f"Groq scoring failed: {e}")
        return None
    
    def _process_llm_result(self, candidates, scores):
        """Process LLM result and update candidates"""
        if not scores:
            return self._score_with_heuristics(candidates, "")
        
        score_map = {s["number"]: s for s in scores if "number" in s}
        
        for candidate in candidates:
            if candidate["number"] in score_map:
                sc = score_map[candidate["number"]]
                candidate["relevance_score"] = float(sc.get("score", 0.5))
                candidate["reason"] = sc.get("reason", "LLM analyzed")[:400]
            else:
                candidate["relevance_score"] = 0.3
                candidate["reason"] = "Not scored by LLM"
        
        candidates.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
        return candidates
    
    def _score_with_heuristics(self, candidates: list, file_path: str) -> list:
        """Fallback heuristic scoring"""
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
