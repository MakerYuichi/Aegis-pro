import json
from typing import Any, Optional

import redis.asyncio as redis
from loguru import logger

from src import config


TTL_REPO = 60 * 60          # 1 hour
TTL_TREE = 60 * 60          # 1 hour
TTL_PRS = 60 * 15           # 15 minutes
TTL_ISSUES = 60 * 15        # 15 minutes
TTL_FILE = 60 * 30          # 30 minutes
TTL_COMMITS = 60 * 30       # 30 minutes
TTL_CONTRIBUTORS = 60 * 60  # 1 hour


def _client() -> redis.Redis:
    return redis.from_url(config.settings.REDIS_URL)


async def cache_get(key: str) -> Optional[Any]:
    """Return the cached value as parsed JSON, or None if missing/unavailable."""
    try:
        client = _client()
        try:
            raw = await client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        finally:
            await client.aclose()
    except Exception as e:
        logger.debug(f"Cache get miss ({key}): {e}")
        return None


async def cache_set(key: str, value: Any, ttl: int) -> None:
    """Store value as JSON with a TTL. Never raises."""
    try:
        client = _client()
        try:
            await client.set(key, json.dumps(value), ex=ttl)
        finally:
            await client.aclose()
    except Exception as e:
        logger.debug(f"Cache set skipped ({key}): {e}")


# ── Key builders ───────────────────────────────────────────────────────
# Centralised so a future schema change touches one place.

def key_repo(owner: str, repo: str) -> str:
    return f"demo:repo:{owner}/{repo}"


def key_tree(owner: str, repo: str, branch: str) -> str:
    return f"demo:tree:{owner}/{repo}:{branch}"


def key_prs(owner: str, repo: str) -> str:
    return f"demo:prs:{owner}/{repo}"


def key_issues(owner: str, repo: str) -> str:
    return f"demo:issues:{owner}/{repo}"


def key_file(owner: str, repo: str, path: str) -> str:
    # Path may contain slashes; Redis keys accept them fine.
    return f"demo:file:{owner}/{repo}:{path}"


def key_commits(owner: str, repo: str, path: str) -> str:
    return f"demo:commits:{owner}/{repo}:{path}"


def key_contributors(owner: str, repo: str) -> str:
    return f"demo:contributors:{owner}/{repo}"
