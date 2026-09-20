from dataclasses import dataclass
from typing import Any, Optional

import httpx
from loguru import logger

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
