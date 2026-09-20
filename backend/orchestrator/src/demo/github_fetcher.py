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
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    }


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
    (e.g. a direct push), it's empty.

    Errors are swallowed — a missing PR for one commit must not fail
    the whole related-PRs lookup.
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
    Return PRs that merged commits to this file, scored by an LLM for
    relevance to the failing line.

    Pipeline:
      1. Fetch the file's commit history (cached separately).
      2. Take the most recent `per_commit_prs` commits.
      3. Look up the PR that merged each, in parallel.
      4. Filter out commits with no associated PR.
      5. Score the survivors with the LLM chain against (file_path,
         line_number). Falls back to a constant 1.0 on every PR if the
         LLM is unavailable.
      6. Cache the whole list for 1 hour.

    Cached under demo:fileprs:{owner}/{repo}:{file_path}.
    """
    cached = await cache.cache_get(cache.key_file_prs(owner, repo, file_path))
    if cached is not None:
        logger.debug(f"cache hit: file PRs {owner}/{repo}:{file_path}")
        return cached

    commits = await fetch_file_commits(owner, repo, file_path, per_page=per_commit_prs)
    if not commits:
        await cache.cache_set(
            cache.key_file_prs(owner, repo, file_path), [], cache.TTL_PRS
        )
        return []

    sha_list = [c["sha"] for c in commits if c.get("sha") and c["sha"] != "unknown"]
    results = await asyncio.gather(
        *(_fetch_pr_for_commit(owner, repo, sha) for sha in sha_list),
        return_exceptions=False,
    )

    prs: list[dict] = []
    seen: set[int] = set()
    for pr in results:
        if not pr or pr.get("number") in seen:
            continue
        seen.add(pr["number"])
        prs.append(pr)

    if not prs:
        await cache.cache_set(
            cache.key_file_prs(owner, repo, file_path), [], cache.TTL_PRS
        )
        return []

    # Score the PRs against the failing line. Falls back to a constant
    # if the LLM chain is unavailable.
    scored = await _score_prs_with_llm(prs, file_path, line_number)

    await cache.cache_set(
        cache.key_file_prs(owner, repo, file_path), scored, cache.TTL_PRS
    )
    logger.info(
        f"Found {len(scored)} file-related PRs for {owner}/{repo}:{file_path}"
    )
    return scored


async def _score_prs_with_llm(
    prs: list[dict],
    file_path: str,
    line_number: int,
) -> list[dict]:
    """
    Score each PR for how likely it is to be related to the failing
    line. Uses LLMService.complete_raw with response_format='json_array',
    so the chain handles provider selection and fallback.

    Returns a copy of the input list with relevance_score and reason
    fields added. On any failure, sets relevance_score=1.0 and a
    generic reason — the caller never sees an unscored list.
    """
    # Import here to avoid a circular import at module load time:
    # llm_service imports github_service, which imports this module.
    from src.services.llm_service import LLMService

    # Compact the PR list for the prompt.
    pr_list = [
        {
            "number": p["number"],
            "title": (p.get("title") or "")[:200],
            "author": p.get("author"),
        }
        for p in prs[:10]
    ]

    prompt = f"""You are a senior software engineer analyzing which GitHub Pull Request most likely introduced a bug.

Error location: {file_path}, line {line_number}

The failing line is at line {line_number} of {file_path}.

PRs that merged commits into this file (most recent first):
{json.dumps(pr_list, indent=2)}

Score each PR from 0.0 to 1.0 based on how likely it is to be the
cause of a failure at line {line_number}:

- 0.90-1.00: modified the exact line or function where the error occurs
- 0.70-0.89: modified the same file near the error line
- 0.50-0.69: modified the same file in a different area
- 0.30-0.49: touched a related file but seems unlikely
- 0.00-0.29: unrelated

Give exact float scores with two decimal places (e.g. 0.73, 0.86, 0.42). Do not round to 0.1 intervals.

Return ONLY a JSON array with one object per PR:
[{{"number": 123, "score": 0.87, "reason": "PR #123 modified line {line_number} and removed a null check."}}]
"""

    system = (
        "You are a senior software engineer. Return ONLY a valid JSON "
        "array. Reference the file name and line number in each reason."
    )

    try:
        llm = LLMService()
        content = await llm.complete_raw(
            prompt=prompt,
            system=system,
            temperature=0.3,
            max_tokens=800,
            response_format="json_array",
        )
    except Exception as e:
        logger.warning(f"LLM PR scoring failed: {e}")
        return _fallback_scores(prs, file_path)

    if not content:
        logger.warning("LLM PR scoring returned no content; using fallback")
        return _fallback_scores(prs, file_path)

    try:
        scores = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("LLM PR scoring returned invalid JSON; using fallback")
        return _fallback_scores(prs, file_path)

    if not isinstance(scores, list):
        return _fallback_scores(prs, file_path)

    score_map: dict[int, dict] = {}
    for s in scores:
        if not isinstance(s, dict):
            continue
        num = s.get("number")
        if not isinstance(num, int):
            continue
        score_map[num] = s

    out = []
    for pr in prs:
        s = score_map.get(pr["number"])
        if s and isinstance(s.get("score"), (int, float)):
            try:
                score = float(s["score"])
            except (TypeError, ValueError):
                score = 1.0
            reason = str(s.get("reason") or f"PR #{pr['number']} touched {file_path}.")
        else:
            score = 1.0
            reason = f"PR #{pr['number']} touched {file_path}."
        out.append({
            **pr,
            "relevance_score": max(0.0, min(1.0, score)),
            "reason": reason[:400],
        })

    out.sort(key=lambda p: p.get("relevance_score", 0), reverse=True)
    return out


def _fallback_scores(prs: list[dict], file_path: str) -> list[dict]:
    """
    Return the PRs with a constant relevance_score=1.0 and a generic
    reason. Used when the LLM is unavailable, so the frontend still has
    something to render.
    """
    return [
        {
            **pr,
            "relevance_score": 1.0,
            "reason": f"PR #{pr['number']} was merged into {file_path}.",
        }
        for pr in prs
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
