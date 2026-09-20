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


# ── Related PRs ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_related_prs_empty_commits_returns_empty(monkeypatch):
    async def _empty_commits(*a, **kw):
        return []
    monkeypatch.setattr(gh, "fetch_file_commits", _empty_commits)

    changes = await gh.fetch_related_prs("owner", "repo", "src/x.py", 42)
    assert changes == []



@pytest.mark.asyncio
async def test_fetch_related_prs_dedupes_prs(monkeypatch):
    async def _commits(*a, **kw):
        return [
            {"sha": "a1b2c3d4", "author": "x", "message": "m1",
             "committed_at": "2026-01-01T00:00:00Z"},
            {"sha": "e5f6a7b8", "author": "y", "message": "m2",
             "committed_at": "2026-01-02T00:00:00Z"},
        ]
    monkeypatch.setattr(gh, "fetch_file_commits", _commits)

    async def _pr_for(owner, repo, sha):
        # Both commits map to the same PR.
        return {"number": 42, "title": "Same PR", "author": "z",
                "url": "u", "merged_at": None, "state": "closed"}
    monkeypatch.setattr(gh, "_fetch_pr_for_commit", _pr_for)

    # Stub out the LLM scorer so we don't hit the network.
    async def _no_score(items, file_path, line_number):
        return [{**it, "relevance_score": 0.5, "reason": "stub"} for it in items]
    monkeypatch.setattr(gh, "_score_prs_with_llm", _no_score)

    changes = await gh.fetch_related_prs("o", "r", "src/x.py", 42)
    # Two commits, two items, even though both map to the same PR.
    assert len(changes) == 2
    assert all(c.get("number") == 42 for c in changes)
    assert changes[0]["sha"] in ("a1b2c3d4", "e5f6a7b8")


@pytest.mark.asyncio
async def test_fetch_related_prs_keeps_commits_without_pr(monkeypatch):
    """A commit with no associated PR still appears in the list."""
    async def _commits(*a, **kw):
        return [{"sha": "aaaa1111", "author": "x", "message": "direct push",
                 "committed_at": "2026-01-01T00:00:00Z"}]
    monkeypatch.setattr(gh, "fetch_file_commits", _commits)

    async def _no_pr(*a, **kw):
        return None
    monkeypatch.setattr(gh, "_fetch_pr_for_commit", _no_pr)

    async def _no_score(items, file_path, line_number):
        return [{**it, "relevance_score": 0.5, "reason": "stub"} for it in items]
    monkeypatch.setattr(gh, "_score_prs_with_llm", _no_score)

    changes = await gh.fetch_related_prs("o", "r", "src/x.py", 42)
    assert len(changes) == 1
    assert changes[0]["sha"] == "aaaa1111"
    assert changes[0]["commit_message"] == "direct push"
    assert "number" not in changes[0]   # no PR attached

    
@pytest.mark.asyncio
async def test_fetch_related_prs_scores_with_llm(monkeypatch):
    """The LLM scorer is called and its output is used."""
    async def _commits(*a, **kw):
        return [{"sha": "aaaa1111", "author": "x", "message": "fix null check",
                 "committed_at": "2026-01-01T00:00:00Z"}]
    monkeypatch.setattr(gh, "fetch_file_commits", _commits)

    async def _pr_for(*a, **kw):
        return {"number": 42, "title": "Fix null check", "author": "z",
                "url": "u", "merged_at": None, "state": "closed"}
    monkeypatch.setattr(gh, "_fetch_pr_for_commit", _pr_for)

    async def _complete_raw(*a, **kw):
        return '[{"index": 0, "score": 0.91, "reason": "removed the null guard"}]'

    class _FakeLLM:
        async def complete_raw(self, *a, **kw):
            return await _complete_raw()

    import src.services.llm_service as llm_mod
    monkeypatch.setattr(llm_mod, "LLMService", lambda: _FakeLLM())

    changes = await gh.fetch_related_prs("o", "r", "src/x.py", 42)
    assert len(changes) == 1
    assert changes[0]["relevance_score"] == 0.91
    assert "null guard" in changes[0]["reason"]


@pytest.mark.asyncio
async def test_fetch_related_prs_falls_back_when_llm_fails(monkeypatch):
    """LLM failure → constant 1.0 on every change, no crash."""
    async def _commits(*a, **kw):
        return [{"sha": "aaaa1111", "author": "x", "message": "m",
                 "committed_at": "2026-01-01T00:00:00Z"}]
    monkeypatch.setattr(gh, "fetch_file_commits", _commits)

    async def _pr_for(*a, **kw):
        return {"number": 42, "title": "t", "author": "z",
                "url": "u", "merged_at": None, "state": "closed"}
    monkeypatch.setattr(gh, "_fetch_pr_for_commit", _pr_for)

    class _BrokenLLM:
        async def complete_raw(self, *a, **kw):
            raise RuntimeError("boom")

    import src.services.llm_service as llm_mod
    monkeypatch.setattr(llm_mod, "LLMService", lambda: _BrokenLLM())

    changes = await gh.fetch_related_prs("o", "r", "src/x.py", 42)
    assert len(changes) == 1
    assert changes[0]["relevance_score"] == 1.0
