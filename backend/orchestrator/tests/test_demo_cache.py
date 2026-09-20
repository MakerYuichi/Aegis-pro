import pytest
from src.demo import cache


@pytest.mark.asyncio
async def test_cache_set_and_get_roundtrip():
    key = "test:cache:roundtrip"
    value = {"hello": "world", "n": 42}
    await cache.cache_set(key, value, ttl=60)
    got = await cache.cache_get(key)
    assert got == value
    # Cleanup
    import redis.asyncio as redis
    from src.config import settings
    client = redis.from_url(settings.REDIS_URL)
    await client.delete(key)
    await client.aclose()


@pytest.mark.asyncio
async def test_cache_get_missing_returns_none():
    got = await cache.cache_get("test:cache:definitely-missing")
    assert got is None


@pytest.mark.asyncio
async def test_cache_fails_open_on_bad_redis_url(monkeypatch):
    """If Redis URL is unreachable, get returns None and set is a no-op."""
    from src.config import settings
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:1/0")
    # get
    assert await cache.cache_get("any-key") is None
    # set should not raise
    await cache.cache_set("any-key", {"x": 1}, ttl=60)


def test_key_builders_are_stable():
    assert cache.key_repo("uber", "ride-dispatch") == "demo:repo:uber/ride-dispatch"
    assert cache.key_tree("uber", "ride-dispatch", "main") == "demo:tree:uber/ride-dispatch:main"
    assert cache.key_prs("uber", "ride-dispatch") == "demo:prs:uber/ride-dispatch"
    assert cache.key_issues("uber", "ride-dispatch") == "demo:issues:uber/ride-dispatch"
    assert cache.key_file("uber", "ride-dispatch", "src/a/b.py") == "demo:file:uber/ride-dispatch:src/a/b.py"
    assert cache.key_commits("uber", "ride-dispatch", "src/a.py") == "demo:commits:uber/ride-dispatch:src/a.py"
    assert cache.key_contributors("uber", "ride-dispatch") == "demo:contributors:uber/ride-dispatch"
