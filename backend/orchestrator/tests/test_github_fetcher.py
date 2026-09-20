import base64
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.demo import github_fetcher as gh
from src.demo.github_fetcher import (
    GitHubRepoNotFoundError,
    GitHubRateLimitError,
    GitHubFetchError,
    GitHubNetworkError,
)


def _mock_response(status_code: int, json_data=None, headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data or {})
    resp.headers = headers or {}
    return resp


@pytest.fixture(autouse=True)
def _bypass_cache(monkeypatch):
    """Every fetcher test bypasses the cache so we hit the mocked API."""
    async def _get(_key):
        return None
    async def _set(_key, _value, _ttl):
        return None
    monkeypatch.setattr(gh.cache, "cache_get", _get)
    monkeypatch.setattr(gh.cache, "cache_set", _set)


def _patch_httpx(response):
    """Patch httpx.AsyncClient(...).get() to return the given response."""
    async def fake_get(self, url, headers=None):
        return response
    async def fake_aenter(self):
        return self
    async def fake_aexit(self, *args):
        return None
    return patch.multiple(
        "httpx.AsyncClient",
        __aenter__=fake_aenter,
        __aexit__=fake_aexit,
        get=fake_get,
    )


# ── Repo metadata ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_repo_metadata_shapes_response():
    payload = {
        "full_name": "uber/ride-dispatch",
        "default_branch": "main",
        "language": "Java",
        "description": "Ride dispatch service",
        "stargazers_count": 1234,
        "forks_count": 56,
        "open_issues_count": 7,
        "size": 4096,
        "pushed_at": "2026-09-19T10:00:00Z",
        "html_url": "https://github.com/uber/ride-dispatch",
    }
    with _patch_httpx(_mock_response(200, payload)):
        result = await gh.fetch_repo_metadata("uber", "ride-dispatch")
    assert result["full_name"] == "uber/ride-dispatch"
    assert result["language"] == "Java"
    assert result["stars"] == 1234


@pytest.mark.asyncio
async def test_fetch_repo_metadata_404_raises():
    with _patch_httpx(_mock_response(404)):
        with pytest.raises(GitHubRepoNotFoundError):
            await gh.fetch_repo_metadata("nope", "nope")


# ── Tree ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_tree_filters_to_blobs_only():
    payload = {
        "tree": [
            {"path": "src", "type": "tree"},
            {"path": "src/main.py", "type": "blob", "size": 1200},
            {"path": "README.md", "type": "blob", "size": 400},
        ]
    }
    with _patch_httpx(_mock_response(200, payload)):
        blobs = await gh.fetch_tree("uber", "ride-dispatch", "main")
    assert [b["path"] for b in blobs] == ["src/main.py", "README.md"]
    assert all(b["type"] == "blob" for b in blobs)


# ── Rate limit ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_rate_limited_403_raises():
    resp = _mock_response(
        403,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1799999999"},
    )
    with _patch_httpx(resp):
        with pytest.raises(GitHubRateLimitError) as exc:
            await gh.fetch_repo_metadata("uber", "ride-dispatch")
    assert exc.value.reset_epoch == 1799999999


@pytest.mark.asyncio
async def test_fetch_403_without_rate_limit_is_generic_error():
    resp = _mock_response(403, headers={"X-RateLimit-Remaining": "55"})
    with _patch_httpx(resp):
        with pytest.raises(GitHubFetchError):
            await gh.fetch_repo_metadata("uber", "ride-dispatch")


# ── PRs and issues ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_recent_prs_shapes_response():
    payload = [
        {
            "number": 127,
            "title": "refactor(upi): simplify response handling",
            "user": {"login": "alice"},
            "html_url": "https://github.com/uber/ride-dispatch/pull/127",
            "merged_at": "2026-09-14T18:32:00Z",
            "state": "closed",
        }
    ]
    with _patch_httpx(_mock_response(200, payload)):
        prs = await gh.fetch_recent_prs("uber", "ride-dispatch")
    assert prs[0]["number"] == 127
    assert prs[0]["author"] == "alice"


@pytest.mark.asyncio
async def test_fetch_recent_issues_filters_out_pull_requests():
    payload = [
        {"number": 1, "title": "Real issue", "user": {"login": "a"}, "html_url": "u1",
         "state": "open", "created_at": "2026-09-01T00:00:00Z", "labels": []},
        {"number": 2, "title": "PR disguised as issue", "user": {"login": "b"},
         "html_url": "u2", "state": "open", "created_at": "2026-09-01T00:00:00Z",
         "labels": [], "pull_request": {"url": "x"}},
    ]
    with _patch_httpx(_mock_response(200, payload)):
        issues = await gh.fetch_recent_issues("uber", "ride-dispatch")
    assert len(issues) == 1
    assert issues[0]["number"] == 1


# ── File content ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_file_content_decodes_base64():
    raw = "def hello():\n    return 1\n"
    encoded = base64.b64encode(raw.encode()).decode()
    payload = {"path": "src/x.py", "content": encoded, "size": len(raw)}
    with _patch_httpx(_mock_response(200, payload)):
        result = await gh.fetch_file_content("uber", "ride-dispatch", "src/x.py")
    assert result["content"] == raw
    assert result["path"] == "src/x.py"


@pytest.mark.asyncio
async def test_fetch_file_content_directory_raises():
    payload = [{"path": "a"}, {"path": "b"}]
    with _patch_httpx(_mock_response(200, payload)):
        with pytest.raises(GitHubFetchError):
            await gh.fetch_file_content("uber", "ride-dispatch", "src")


# ── Contributors ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_contributors_shapes_response():
    payload = [
        {"login": "alice", "avatar_url": "https://a", "contributions": 500, "html_url": "u"},
        {"login": "bob", "avatar_url": "https://b", "contributions": 200, "html_url": "u"},
    ]
    with _patch_httpx(_mock_response(200, payload)):
        cs = await gh.fetch_contributors("uber", "ride-dispatch")
    assert cs[0]["username"] == "alice"
    assert cs[0]["contributions"] == 500


# ── Commits ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_file_commits_shapes_response():
    payload = [
        {
            "sha": "a3f9d21c00000000000000000000000000000000",
            "author": {"login": "alice"},
            "commit": {
                "message": "refactor(upi): simplify response handling\n\nLonger body.",
                "committer": {"date": "2026-09-14T18:32:00Z"},
            },
        }
    ]
    with _patch_httpx(_mock_response(200, payload)):
        commits = await gh.fetch_file_commits("uber", "ride-dispatch", "src/x.py")
    assert commits[0]["sha"] == "a3f9d21c"
    assert commits[0]["author"] == "alice"
    assert commits[0]["message"] == "refactor(upi): simplify response handling"
