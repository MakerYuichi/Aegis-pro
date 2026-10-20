"""
Tests for the hostile wheel fixtures.

Each test builds a hostile wheel via the builder, then calls
smoke_test and asserts the specific refusal reason. No build
container is needed for most — the smoke test's structural
checks run in the orchestrator process. The RECORD verification
is where the hostile wheels are refused, before the container
import check would run.
"""
from __future__ import annotations

import pytest

from src.agents.mirror import smoke
from src.agents.mirror.smoke import SmokeError, smoke_test
from tests.mirror.hostile import wheels


@pytest.fixture(autouse=True)
def _mock_tags(monkeypatch):
    async def fake_get_supported_tags():
        return frozenset({"py3-none-any"})
    monkeypatch.setattr(
        "src.agents.mirror.smoke.get_supported_tags",
        fake_get_supported_tags,
    )


@pytest.fixture(autouse=True)
def _mock_container(monkeypatch):
    """For hostile wheels refused at the structural level, the
    container import check never runs. Mock it anyway in case a
    test accidentally gets past the structural checks."""
    from unittest.mock import AsyncMock, MagicMock
    async def fake_exec(*argv, **kwargs):
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", None))
        return proc
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec", fake_exec,
    )


def _write_wheel(tmp_path, wheel_bytes, filename):
    path = tmp_path / filename
    path.write_bytes(wheel_bytes)
    return path


@pytest.mark.asyncio
async def test_zip_bomb_wheel_refused(tmp_path):
    wheel_bytes = wheels.zip_bomb_wheel()
    filename = "aegis_hostile-0.0.1-py3-none-any.whl"
    wheel_path = _write_wheel(tmp_path, wheel_bytes, filename)

    with pytest.raises(SmokeError) as exc:
        await smoke_test(
            wheel_container_path=wheel_path,
            wheel_host_path=wheel_path,
            expected_name="aegis-hostile",
            expected_version="0.0.1",
        )
    assert exc.value.reason == "record_member_too_large"


@pytest.mark.asyncio
async def test_duplicate_member_wheel_refused(tmp_path):
    wheel_bytes = wheels.duplicate_member_wheel()
    filename = "aegis_hostile-0.0.1-py3-none-any.whl"
    wheel_path = _write_wheel(tmp_path, wheel_bytes, filename)

    with pytest.raises(SmokeError) as exc:
        await smoke_test(
            wheel_container_path=wheel_path,
            wheel_host_path=wheel_path,
            expected_name="aegis-hostile",
            expected_version="0.0.1",
        )
    # Depending on zipfile's resolution of the duplicate, either
    # the RECORD hash doesn't match the returned content
    # (record_hash_mismatch), or the duplicate appears in the
    # namelist twice and one entry isn't matched by RECORD
    # (record_unlisted_file).
    assert exc.value.reason in (
        "record_hash_mismatch", "record_unlisted_file",
    )


@pytest.mark.asyncio
async def test_unlisted_pth_wheel_refused(tmp_path):
    wheel_bytes = wheels.unlisted_pth_wheel()
    filename = "aegis_hostile-0.0.1-py3-none-any.whl"
    wheel_path = _write_wheel(tmp_path, wheel_bytes, filename)

    with pytest.raises(SmokeError) as exc:
        await smoke_test(
            wheel_container_path=wheel_path,
            wheel_host_path=wheel_path,
            expected_name="aegis-hostile",
            expected_version="0.0.1",
        )
    assert exc.value.reason == "record_unlisted_file"
    assert "import_hook.pth" in exc.value.detail
