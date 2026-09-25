from dataclasses import dataclass
from typing import Any, Optional

import httpx
from loguru import logger
import json
import asyncio

from src.demo import cache


GITHUB_API = "https://api.github.com"
USER_AGENT = "AEGIS-PRO-Demo/1.0 (+https://github.com/MakerYuichi/Aegis-pro)"
DEFAULT_TIMEOUT = 10.0


# ── Errors ─────────────────────────────────────────────────────────────

class GitHubFetchError(Exception):
    """Base class for GitHub fetcher errors."""


class GitHubRepoNotFoundError(GitHubFetchError):
    """Repo does not exist, or is private and inaccessible unauthenticated."""


class GitHubRateLimitError(GitHubFetchError):
    """GitHub's unauthenticated rate limit has been hit."""

    def __init__(self, reset_epoch: Optional[int] = None):
        self.reset_epoch = reset_epoch
        super().__init__("GitHub API rate limit exceeded")


class GitHubNetworkError(GitHubFetchError):
    """Network failure reaching GitHub."""


# ── Response shapes (documented, not enforced) ─────────────────────────
#
# fetch_repo_metadata returns:
#   {full_name, default_branch, language, description, stars, forks,
#    open_issues, size_kb, pushed_at, html_url}
#
# fetch_tree returns:
#   [{path, type, size}]  — every blob in the tree, filtered to type=blob
#
# fetch_recent_prs returns:
#   [{number, title, author, url, merged_at, files?}]
#
# fetch_recent_issues returns:
#   [{number, title, author, url, state, created_at, labels}]
#
# fetch_file_commits returns:
#   [{sha, author, message, committed_at}]
#
# fetch_file_content returns:
#   {path, content, size}
#
# fetch_contributors returns:
#   [{username, avatar_url, contributions, url}]


def _headers() -> dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    }
    from src.config import settings
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
    return headers


def _handle_response(resp: httpx.Response, owner: str, repo: str) -> None:
    """Raise typed errors for common non-200 cases."""
    if resp.status_code == 200:
        return

    if resp.status_code == 404:
        raise GitHubRepoNotFoundError(
            f"{owner}/{repo} not found or is private"
        )

    if resp.status_code == 403:
        # 403 with rate-limit headers means we're throttled.
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining == "0":
            reset = resp.headers.get("X-RateLimit-Reset")
            raise GitHubRateLimitError(
                reset_epoch=int(reset) if reset and reset.isdigit() else None
            )
        raise GitHubFetchError(f"GitHub returned 403 for {owner}/{repo}")

    raise GitHubFetchError(
        f"GitHub returned {resp.status_code} for {owner}/{repo}"
    )


async def _get(url: str, owner: str, repo: str) -> Any:
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(url, headers=_headers())
            _handle_response(resp, owner, repo)
            return resp.json()
    except (GitHubRepoNotFoundError, GitHubRateLimitError, GitHubFetchError):
        raise
    except httpx.HTTPError as e:
        raise GitHubNetworkError(f"Network error talking to GitHub: {e}") from e


# ── Public API ─────────────────────────────────────────────────────────

async def fetch_repo_metadata(owner: str, repo: str) -> dict[str, Any]:
    cached = await cache.cache_get(cache.key_repo(owner, repo))
    if cached is not None:
        logger.debug(f"cache hit: repo metadata {owner}/{repo}")
        return cached

    data = await _get(f"{GITHUB_API}/repos/{owner}/{repo}", owner, repo)
    result = {
        "full_name": data.get("full_name"),
        "default_branch": data.get("default_branch") or "main",
        "language": data.get("language"),
        "description": data.get("description"),
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "open_issues": data.get("open_issues_count", 0),
        "size_kb": data.get("size", 0),
        "pushed_at": data.get("pushed_at"),
        "html_url": data.get("html_url"),
    }
    await cache.cache_set(cache.key_repo(owner, repo), result, cache.TTL_REPO)
    return result


async def fetch_tree(
    owner: str, repo: str, branch: str
) -> list[dict[str, Any]]:
    cached = await cache.cache_get(cache.key_tree(owner, repo, branch))
    if cached is not None:
        logger.debug(f"cache hit: tree {owner}/{repo}@{branch}")
        return cached

    data = await _get(
        f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
        owner,
        repo,
    )
    blobs = [
        {
            "path": item.get("path"),
            "type": item.get("type"),
            "size": item.get("size", 0),
        }
        for item in data.get("tree", [])
        if item.get("type") == "blob"
    ]
    await cache.cache_set(
        cache.key_tree(owner, repo, branch), blobs, cache.TTL_TREE
    )
    return blobs


async def fetch_recent_prs(
    owner: str, repo: str, per_page: int = 20
) -> list[dict[str, Any]]:
    cached = await cache.cache_get(cache.key_prs(owner, repo))
    if cached is not None:
        logger.debug(f"cache hit: PRs {owner}/{repo}")
        return cached

    data = await _get(
        f"{GITHUB_API}/repos/{owner}/{repo}/pulls"
        f"?state=closed&sort=updated&direction=desc&per_page={per_page}",
        owner,
        repo,
    )
    prs = [
        {
            "number": pr.get("number"),
            "title": pr.get("title"),
            "author": (pr.get("user") or {}).get("login"),
            "url": pr.get("html_url"),
            "merged_at": pr.get("merged_at"),
            "state": pr.get("state"),
        }
        for pr in data
    ]
    await cache.cache_set(cache.key_prs(owner, repo), prs, cache.TTL_PRS)
    return prs


async def fetch_recent_issues(
    owner: str, repo: str, per_page: int = 20
) -> list[dict[str, Any]]:
    cached = await cache.cache_get(cache.key_issues(owner, repo))
    if cached is not None:
        logger.debug(f"cache hit: issues {owner}/{repo}")
        return cached

    data = await _get(
        f"{GITHUB_API}/repos/{owner}/{repo}/issues"
        f"?state=all&sort=updated&direction=desc&per_page={per_page}",
        owner,
        repo,
    )
    # GitHub's issues endpoint returns PRs too — filter them out.
    issues = [
        {
            "number": it.get("number"),
            "title": it.get("title"),
            "author": (it.get("user") or {}).get("login"),
            "url": it.get("html_url"),
            "state": it.get("state"),
            "created_at": it.get("created_at"),
            "labels": [lb.get("name") for lb in it.get("labels", [])],
        }
        for it in data
        if "pull_request" not in it
    ]
    await cache.cache_set(cache.key_issues(owner, repo), issues, cache.TTL_ISSUES)
    return issues


async def fetch_file_commits(
    owner: str, repo: str, path: str, per_page: int = 10
) -> list[dict[str, Any]]:
    cached = await cache.cache_get(cache.key_commits(owner, repo, path))
    if cached is not None:
        logger.debug(f"cache hit: commits for {owner}/{repo}:{path}")
        return cached

    data = await _get(
        f"{GITHUB_API}/repos/{owner}/{repo}/commits"
        f"?path={path}&per_page={per_page}",
        owner,
        repo,
    )
    commits = [
        {
            "sha": (c.get("sha") or "")[:8],
            "author": ((c.get("author") or {}).get("login")),
            "message": (c.get("commit", {}).get("message") or "").split("\n")[0][:120],
            "committed_at": c.get("commit", {}).get("committer", {}).get("date"),
        }
        for c in data
    ]
    await cache.cache_set(
        cache.key_commits(owner, repo, path), commits, cache.TTL_COMMITS
    )
    return commits

async def _fetch_pr_for_commit(
    owner: str, repo: str, sha: str
) -> Optional[dict]:
    """
    Return the PR that merged a given commit, or None.

    GitHub's /commits/{sha}/pulls endpoint returns an array. For a
    merge commit, it's usually one entry. For a non-merge commit
    (e.g. a direct push or squash merge), it's empty.

    Errors are swallowed — a missing PR for one commit must not fail
    the whole changes lookup. The caller treats None as "commit has
    no associated PR" and still includes it in the list.
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/commits/{sha}/pulls"
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(
                url,
                headers={
                    **_headers(),
                    "Accept": "application/vnd.github.groot-preview+json",
                },
            )
            if resp.status_code == 404:
                return None
            if resp.status_code != 200:
                logger.debug(
                    f"PR lookup for {sha} returned {resp.status_code}"
                )
                return None
            data = resp.json()
            if not isinstance(data, list) or not data:
                return None
            pr = data[0]
            return {
                "number": pr.get("number"),
                "title": pr.get("title"),
                "author": (pr.get("user") or {}).get("login"),
                "url": pr.get("html_url"),
                "merged_at": pr.get("merged_at"),
                "state": pr.get("state"),
            }
    except httpx.HTTPError as e:
        logger.debug(f"PR lookup for {sha} failed: {e}")
        return None
    

async def fetch_related_prs(
    owner: str,
    repo: str,
    file_path: str,
    line_number: int,
    per_commit_prs: int = 10,
) -> list[dict]:
    """
    Return changes that touched this file, scored by an LLM for
    relevance to the failing line.

    Each entry is a commit. If the commit was merged by a PR, the PR
    number and URL are attached. If not, the entry is commit-only.
    The LLM scores both kinds identically.

    Pipeline:
      1. Fetch the file's commit history (cached separately).
      2. Take the most recent `per_commit_prs` commits.
      3. For each commit, look up the merging PR (parallel).
      4. Merge commit + optional PR into one item.
      5. Score every item with the LLM against (file_path, line_number).
      6. Cache the scored list for 1 hour.

    Cached under demo:fileprs:{owner}/{repo}:{file_path}.
    """
    cached = await cache.cache_get(cache.key_file_prs(owner, repo, file_path))
    if cached is not None:
        logger.debug(f"cache hit: file changes {owner}/{repo}:{file_path}")
        return cached

    commits = await fetch_file_commits(owner, repo, file_path, per_page=per_commit_prs)
    if not commits:
        await cache.cache_set(
            cache.key_file_prs(owner, repo, file_path), [], cache.TTL_PRS
        )
        return []

    # Look up PRs in parallel. Commits without PRs still come through —
    # they're the majority on many repos.
    results = await asyncio.gather(
        *(_fetch_pr_for_commit(owner, repo, c["sha"])
          for c in commits if c.get("sha") and c["sha"] != "unknown"),
        return_exceptions=False,
    )

    # Zip commits (that had valid shas) back with their PR lookups.
    valid_commits = [
        c for c in commits if c.get("sha") and c["sha"] != "unknown"
    ]
    items: list[dict] = []
    for commit, pr in zip(valid_commits, results):
        item: dict[str, Any] = {
            "sha": commit.get("sha"),
            "commit_message": commit.get("message"),
            "commit_date": commit.get("committed_at"),
            "author": commit.get("author"),
        }
        if pr:
            item["number"] = pr.get("number")
            item["title"] = pr.get("title")
            item["url"] = pr.get("url")
            item["merged_at"] = pr.get("merged_at")
            # The commit's author may differ from the PR's author.
            # Prefer the PR author when we have one — it's the more
            # relevant name for attribution.
            if pr.get("author"):
                item["author"] = pr["author"]
        items.append(item)

    scored = await _score_prs_with_llm(items, file_path, line_number)

    await cache.cache_set(
        cache.key_file_prs(owner, repo, file_path), scored, cache.TTL_PRS
    )
    logger.info(
        f"Found {len(scored)} file-related changes for {owner}/{repo}:{file_path}"
    )
    return scored


async def _score_prs_with_llm(
    items: list[dict],
    file_path: str,
    line_number: int,
) -> list[dict]:
    """
    Score each change (commit or PR) for how likely it is to be related
    to the failing line. Uses LLMService.complete_raw with
    response_format='json_array'.

    Items are scored by their index in the list, since commits have no
    PR number. Returns a copy of the input list with relevance_score
    and reason added.
    """
    from src.services.llm_service import LLMService

    # Build the prompt list. Each entry has an index, the commit message,
    # and optionally the PR number and title.
    prompt_items = []
    for i, it in enumerate(items[:10]):
        entry: dict[str, Any] = {
            "index": i,
            "commit_message": (it.get("commit_message") or "")[:200],
            "commit_date": it.get("commit_date"),
            "author": it.get("author"),
        }
        if it.get("number"):
            entry["pr_number"] = it["number"]
            entry["pr_title"] = (it.get("title") or "")[:200]
        prompt_items.append(entry)

    prompt = f"""You are a senior software engineer analyzing which change most likely introduced a bug.

Error location: {file_path}, line {line_number}

The failing line is at line {line_number} of {file_path}.

Changes that touched this file (most recent first):
{json.dumps(prompt_items, indent=2)}

Score each change from 0.0000 to 1.0000 based on how likely it is to be the
cause of a failure at line {line_number}:

- 0.9000-1.0000: the commit message or PR title indicates a change at the failing line
- 0.7000-0.8999: the change is clearly related to the code around line {line_number}
- 0.5000-0.6999: the change touched the same file but in a different area
- 0.3000-0.4999: same file, unclear relation
- 0.0000-0.2999: unrelated

Score each change with four decimal places (e.g. 0.7245, 0.9312, 0.6187,
0.4501, 0.3999). Do not round to two decimals or whole percentages. A
score of "0.92" is invalid — write "0.9200" or a more precise value
like "0.9187".

For each reason, reference the commit message or PR title. Do NOT
invent line numbers or describe changes you cannot see. If the commit
message does not describe a change near line {line_number}, say so and
score it accordingly.

Return ONLY a JSON array with one object per change:
[{{"index": 0, "score": 0.8743, "reason": "Commit 'refactor: fix null check' touches the area around line {line_number}."}}]
"""

    system = (
        "You are a senior software engineer. Return ONLY a valid JSON "
        "array. Reference the commit message or PR title in each reason."
    )

    try:
        llm = LLMService()
        content = await llm.complete_raw(
            prompt=prompt,
            system=system,
            temperature=0.3,
            max_tokens=1000,
            response_format="json_array",
        )
    except Exception as e:
        logger.warning(f"LLM change scoring failed: {e}")
        return _fallback_scores(items, file_path)

    if not content:
        logger.warning("LLM change scoring returned no content; using fallback")
        return _fallback_scores(items, file_path)

    try:
        scores = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("LLM change scoring returned invalid JSON; using fallback")
        return _fallback_scores(items, file_path)

    if not isinstance(scores, list):
        return _fallback_scores(items, file_path)

    score_map: dict[int, dict] = {}
    for s in scores:
        if not isinstance(s, dict):
            continue
        idx = s.get("index")
        if not isinstance(idx, int):
            continue
        score_map[idx] = s

    out = []
    for i, it in enumerate(items):
        s = score_map.get(i)
        if s and isinstance(s.get("score"), (int, float)):
            try:
                score = float(s["score"])
            except (TypeError, ValueError):
                score = 0.0
            reason = str(s.get("reason") or _default_reason(it, file_path))
        else:
            score = 0.0
            reason = "Not scored by model."
        out.append({
            **it,
            "relevance_score": max(0.0, min(1.0, score)),
            "reason": reason[:400],
        })

    out.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    return out


def _default_reason(item: dict, file_path: str) -> str:
    if item.get("number"):
        return f"PR #{item['number']} merged a commit into {file_path}."
    return f"Commit {item.get('sha', 'unknown')} touched {file_path}."


def _fallback_scores(items: list[dict], file_path: str) -> list[dict]:
    """
    Return the items with a constant relevance_score=1.0 and a generic
    reason. Used when the LLM is unavailable so the frontend still has
    something to render.
    """
    return [
        {
            **it,
            "relevance_score": 0.0,
            "reason": "Not scored — LLM unavailable.",
        }
        for it in items
    ]



async def fetch_file_content(
    owner: str, repo: str, path: str
) -> dict[str, Any]:
    cached = await cache.cache_get(cache.key_file(owner, repo, path))
    if cached is not None:
        logger.debug(f"cache hit: file {owner}/{repo}:{path}")
        return cached

    data = await _get(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}", owner, repo
    )
    if isinstance(data, list):
        raise GitHubFetchError(f"{path} is a directory, not a file")

    import base64

    content_b64 = data.get("content", "")
    try:
        content = base64.b64decode(content_b64).decode("utf-8", errors="replace")
    except Exception as e:
        raise GitHubFetchError(f"Could not decode {path}: {e}") from e

    result = {
        "path": path,
        "content": content,
        "size": data.get("size", len(content)),
    }
    await cache.cache_set(cache.key_file(owner, repo, path), result, cache.TTL_FILE)
    return result


async def fetch_contributors(
    owner: str, repo: str, per_page: int = 10
) -> list[dict[str, Any]]:
    cached = await cache.cache_get(cache.key_contributors(owner, repo))
    if cached is not None:
        logger.debug(f"cache hit: contributors {owner}/{repo}")
        return cached

    data = await _get(
        f"{GITHUB_API}/repos/{owner}/{repo}/contributors?per_page={per_page}",
        owner,
        repo,
    )
    contributors = [
        {
            "username": c.get("login"),
            "avatar_url": c.get("avatar_url"),
            "contributions": c.get("contributions", 0),
            "url": c.get("html_url"),
        }
        for c in data
    ]
    await cache.cache_set(
        cache.key_contributors(owner, repo), contributors, cache.TTL_CONTRIBUTORS
    )
    return contributors
