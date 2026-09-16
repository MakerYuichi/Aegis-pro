from github import Github, Auth
from src.config import settings
from src.services.llm_service import LLMService
from loguru import logger
import re
import json
# NOTE: httpx import removed — no longer needed after LLM chain refactor


class GitHubService:
    def __init__(self):
        self.client = None
        self.llm = None

        # Initialize LLM
        try:
            self.llm = LLMService()
            # CHANGED: was `if self.llm.client:` — that attribute no longer exists.
            # LLMService now exposes a `chain` attribute (LLMChain | None).
            if self.llm.chain:
                logger.info(f"✅ GitHub service initialized with LLM chain: "
                            f"{self.llm.chain.provider_names()}")
            else:
                logger.warning("⚠️ LLM chain not available")
        except Exception as e:
            logger.warning(f"⚠️ LLM not available: {e}")
            self.llm = None

        # Initialize GitHub (unchanged)
        if settings.GITHUB_TOKEN:
            try:
                auth = Auth.Token(settings.GITHUB_TOKEN)
                self.client = Github(auth=auth)
                logger.info("✅ GitHub client initialized")
            except Exception as e:
                logger.error(f"GitHub init error: {e}")
        else:
            logger.warning("⚠️ GitHub token not configured")

    # ... _get_repo, get_recent_prs, get_blame_with_pr, get_related_prs unchanged ...

    async def _score_candidates_with_llm_service(
        self, candidates: list, file_path: str, line_number: int
    ) -> list:
        """Score PR candidates using the LLM chain. Falls back to heuristics."""

        if not self.llm or not self.llm.chain:
            logger.warning("LLM chain not available, using heuristics")
            return self._score_with_heuristics(candidates, file_path)

        # Build PR list for scoring
        pr_list = []
        for p in candidates[:6]:
            pr_list.append({
                "number": p["number"],
                "title": p["title"][:200],
                "files": p["files"][:3],
                "author": p.get("author", "unknown"),
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

        system = (
            "You are a senior software engineer. "
            "Return ONLY a valid JSON array with specific, detailed reasons for each score."
        )

        try:
            # Single call — the chain handles provider fallback internally.
            content = await self.llm.complete_raw(
                prompt=prompt,
                system=system,
                temperature=0.3,
                max_tokens=800,
            )
            if not content:
                logger.warning("LLM chain returned no content; using heuristics")
                return self._score_with_heuristics(candidates, file_path)

            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if not json_match:
                logger.warning("LLM response contained no JSON array; using heuristics")
                return self._score_with_heuristics(candidates, file_path)

            scores = json.loads(json_match.group())
            logger.info(f"✅ LLM PR scoring succeeded ({len(scores)} scores)")
            return self._process_llm_result(candidates, scores)

        except Exception as e:
            logger.error(f"LLM scoring error: {e}")
            return self._score_with_heuristics(candidates, file_path)
    
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
