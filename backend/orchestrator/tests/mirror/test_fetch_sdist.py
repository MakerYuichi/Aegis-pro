"""Tests for fetch_sdist. All network is mocked."""
from __future__ import annotations

import hashlib
import io
from unittest.mock import patch

import pytest

from src.agents.mirror.fetch_sdist import (
    SdistFetchError,
    fetch_sdist,
)
from src.agents.mirror.types import SdistRef


def _ref(url: str = "https://files.pythonhosted.org/pkg.tar.gz",
         sha: str | None = None) -> SdistRef:
    if sha is None:
        sha = "sha256:" + hashlib.sha256(b"contents").hexdigest()
    return SdistRef(
        url=url, filename="pkg.tar.gz", sha256=sha,
        upload_time="2023-01-01T00:00:00Z",
        name="pkg", version="1.0",
    )


class _FakeResp:
    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            out = self._data[self._pos:]
            self._pos = len(self._data)
            return out
        out = self._data[self._pos:self._pos + n]
        self._pos += len(out)
        return out

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_fetch_verifies_hash():
    body = b"contents"
    ref = _ref(sha="sha256:" + hashlib.sha256(body).hexdigest())
    with patch(
        "src.agents.mirror.fetch_sdist.urllib.request.urlopen",
        return_value=_FakeResp(body),
    ):
        out = fetch_sdist(ref)
    assert out == body


def test_hash_mismatch_raises():
    ref = _ref(sha="sha256:" + "0" * 64)
    with patch(
        "src.agents.mirror.fetch_sdist.urllib.request.urlopen",
        return_value=_FakeResp(b"contents"),
    ):
        with pytest.raises(SdistFetchError) as exc:
            fetch_sdist(ref)
    assert exc.value.reason == "sdist_hash_mismatch"


def test_http_host_refused():
    ref = _ref(url="http://files.pythonhosted.org/pkg.tar.gz")
    with pytest.raises(SdistFetchError) as exc:
        fetch_sdist(ref)
    assert exc.value.reason == "sdist_url_not_https"


def test_wrong_host_refused():
    ref = _ref(url="https://evil.example/pkg.tar.gz")
    with pytest.raises(SdistFetchError) as exc:
        fetch_sdist(ref)
    assert exc.value.reason == "sdist_url_host_not_allowed"
