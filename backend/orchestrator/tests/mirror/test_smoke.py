"""
Tests for smoke.

The tests construct real wheel files in memory via zipfile for
the structural checks. The container import check is mocked —
no docker needed to run these tests.

Each test asserts one specific SmokeError reason. A test that
produces a different reason has either a fixture that doesn't
match its intent or a smoke check that fires too early.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.mirror import smoke
from src.agents.mirror.smoke import (
    SmokeError,
    smoke_test,
)


def _sha256_b64(data: bytes) -> str:
    """RECORD's hash format: sha256=<urlsafe-base64, no padding>."""
    return base64.urlsafe_b64encode(
        hashlib.sha256(data).digest()
    ).rstrip(b"=").decode()


def _make_wheel(
    *,
    name: str = "sentence-transformers",
    version: str = "2.2.2",
    dist_info_name: str | None = None,
    metadata_name: str | None = None,
    metadata_version: str | None = None,
    wheel_tags: list[str] | None = None,
    filename_tags: list[str] | None = None,
    extra_files: dict[str, bytes] | None = None,
    omit_record_entries: list[str] | None = None,
    bad_hashes: dict[str, str] | None = None,
    pth_content: bytes | None = None,
    two_dist_infos: bool = False,
) -> bytes:
    """
    Build a minimal wheel with configurable violations.

    Defaults produce a valid wheel named
    sentence_transformers-2.2.2-py3-none-any.whl with:
      - one .dist-info directory
      - METADATA matching the pin
      - WHEEL Tag: py3-none-any
      - a sentence_transformers/__init__.py module
      - a valid RECORD

    Any keyword argument overrides one aspect, usually to make
    the wheel invalid in that specific way.
    """
    if dist_info_name is None:
        dist_info_name = f"{name.replace('-', '_')}-{version}.dist-info"
    if metadata_name is None:
        metadata_name = name
    if metadata_version is None:
        metadata_version = version
    if filename_tags is None:
        filename_tags = ["py3-none-any"]
    if wheel_tags is None:
        wheel_tags = ["py3-none-any"]

    files: dict[str, bytes] = {}

    # A top-level module.
    module_dir = name.replace("-", "_")
    files[f"{module_dir}/__init__.py"] = b"# module init\n"
    files[f"{module_dir}/core.py"] = b"VERSION = '1.0'\n"

    # Extra files (used for tests that add unlisted files).
    for path, content in (extra_files or {}).items():
        files[path] = content

    # METADATA.
    meta_lines = [
        f"Metadata-Version: 2.1",
        f"Name: {metadata_name}",
        f"Version: {metadata_version}",
    ]
    files[f"{dist_info_name}/METADATA"] = (
        "\n".join(meta_lines) + "\n"
    ).encode()

    # WHEEL.
    wheel_lines = ["Wheel-Version: 1.0"]
    for tag in wheel_tags:
        wheel_lines.append(f"Tag: {tag}")
    files[f"{dist_info_name}/WHEEL"] = (
        "\n".join(wheel_lines) + "\n"
    ).encode()

    # Optional .pth file.
    if pth_content is not None:
        files[f"{module_dir}/import_hook.pth"] = pth_content

    # Optional second dist-info for the confusion test.
    if two_dist_infos:
        files["evil-1.0.dist-info/METADATA"] = (
            b"Metadata-Version: 2.1\nName: evil\nVersion: 1.0\n"
        )
        files["evil-1.0.dist-info/WHEEL"] = (
            b"Wheel-Version: 1.0\nTag: py3-none-any\n"
        )

    # Build RECORD.
    record_lines = []
    for path, content in files.items():
        if path == f"{dist_info_name}/RECORD":
            continue
        if omit_record_entries and path in omit_record_entries:
            continue
        if bad_hashes and path in bad_hashes:
            digest = bad_hashes[path]
        else:
            digest = _sha256_b64(content)
        record_lines.append(f"{path},sha256={digest},{len(content)}")
    record_lines.append(f"{dist_info_name}/RECORD,,")
    files[f"{dist_info_name}/RECORD"] = (
        "\n".join(record_lines) + "\n"
    ).encode()

    # Build the zip in memory.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _wheel_filename(
    name: str = "sentence-transformers",
    version: str = "2.2.2",
    tags: list[str] | None = None,
) -> str:
    """Construct a wheel filename per PEP 427."""
    if tags is None:
        tags = ["py3-none-any"]
    normalized = name.replace("-", "_")
    # PEP 427: <name>-<version>-<python>-<abi>-<platform>.whl
    # For multiple tags, join with dots.
    tag_parts = tags[0].split("-")
    return f"{normalized}-{version}-{'-'.join(tag_parts)}.whl"


@pytest.fixture(autouse=True)
def _mock_container(monkeypatch):
    """Every test gets a mocked container import check by default.
    Tests that exercise the container path override it."""
    async def fake_exec(*argv, **kwargs):
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", None))
        return proc
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec", fake_exec,
    )


@pytest.fixture(autouse=True)
def _mock_tags(monkeypatch):
    """Every test gets a mocked tag set including py3-none-any."""
    async def fake_get_supported_tags():
        return frozenset({
            "py3-none-any", "cp311-cp311-manylinux_aarch64",
        })
    monkeypatch.setattr(
        "src.agents.mirror.smoke.get_supported_tags",
        fake_get_supported_tags,
    )


def _write_wheel(tmp_path, wheel_bytes, filename):
    path = tmp_path / filename
    path.write_bytes(wheel_bytes)
    return path


# ── happy path ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_valid_wheel_passes(tmp_path):
    filename = _wheel_filename()
    wheel_path = _write_wheel(tmp_path, _make_wheel(), filename)
    await smoke_test(
        wheel_container_path=wheel_path,
        wheel_host_path=wheel_path,
        expected_name="sentence-transformers",
        expected_version="2.2.2",
    )


# ── filename and pin matching ──────────────────────────────────

@pytest.mark.asyncio
async def test_filename_name_mismatch_refused(tmp_path):
    filename = _wheel_filename(name="evil")
    wheel_path = _write_wheel(tmp_path, _make_wheel(), filename)
    with pytest.raises(SmokeError) as exc:
        await smoke_test(
            wheel_container_path=wheel_path,
            wheel_host_path=wheel_path,
            expected_name="sentence-transformers",
            expected_version="2.2.2",
        )
    assert exc.value.reason == "pin_name_mismatch"


@pytest.mark.asyncio
async def test_filename_version_mismatch_refused(tmp_path):
    filename = _wheel_filename(version="9.9.9")
    wheel_path = _write_wheel(tmp_path, _make_wheel(), filename)
    with pytest.raises(SmokeError) as exc:
        await smoke_test(
            wheel_container_path=wheel_path,
            wheel_host_path=wheel_path,
            expected_name="sentence-transformers",
            expected_version="2.2.2",
        )
    assert exc.value.reason == "pin_version_mismatch"


@pytest.mark.asyncio
async def test_invalid_filename_refused(tmp_path):
    wheel_path = _write_wheel(tmp_path, _make_wheel(), "garbage.whl")
    with pytest.raises(SmokeError) as exc:
        await smoke_test(
            wheel_container_path=wheel_path,
            wheel_host_path=wheel_path,
            expected_name="sentence-transformers",
            expected_version="2.2.2",
        )
    assert exc.value.reason == "invalid_filename"


# ── metadata checks ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_metadata_name_mismatch_refused(tmp_path):
    filename = _wheel_filename()
    wheel = _make_wheel(metadata_name="evil")
    wheel_path = _write_wheel(tmp_path, wheel, filename)
    with pytest.raises(SmokeError) as exc:
        await smoke_test(
            wheel_container_path=wheel_path,
            wheel_host_path=wheel_path,
            expected_name="sentence-transformers",
            expected_version="2.2.2",
        )
    assert exc.value.reason == "metadata_name_mismatch"


@pytest.mark.asyncio
async def test_metadata_version_mismatch_refused(tmp_path):
    filename = _wheel_filename()
    wheel = _make_wheel(metadata_version="9.9.9")
    wheel_path = _write_wheel(tmp_path, wheel, filename)
    with pytest.raises(SmokeError) as exc:
        await smoke_test(
            wheel_container_path=wheel_path,
            wheel_host_path=wheel_path,
            expected_name="sentence-transformers",
            expected_version="2.2.2",
        )
    assert exc.value.reason == "metadata_version_mismatch"


@pytest.mark.asyncio
async def test_two_dist_info_dirs_refused(tmp_path):
    filename = _wheel_filename()
    wheel = _make_wheel(two_dist_infos=True)
    wheel_path = _write_wheel(tmp_path, wheel, filename)
    with pytest.raises(SmokeError) as exc:
        await smoke_test(
            wheel_container_path=wheel_path,
            wheel_host_path=wheel_path,
            expected_name="sentence-transformers",
            expected_version="2.2.2",
        )
    assert exc.value.reason == "multiple_dist_info"


# ── tag checks ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unsupported_tag_refused(tmp_path):
    filename = _wheel_filename(tags=["cp999-cp999-win_amd64"])
    wheel = _make_wheel(wheel_tags=["cp999-cp999-win_amd64"])
    wheel_path = _write_wheel(tmp_path, wheel, filename)
    with pytest.raises(SmokeError) as exc:
        await smoke_test(
            wheel_container_path=wheel_path,
            wheel_host_path=wheel_path,
            expected_name="sentence-transformers",
            expected_version="2.2.2",
        )
    assert exc.value.reason == "unsupported_wheel"


@pytest.mark.asyncio
async def test_wheel_metadata_tag_mismatch_refused(tmp_path):
    # Filename says py3-none-any, WHEEL says cp999-win_amd64.
    filename = _wheel_filename()
    wheel = _make_wheel(wheel_tags=["cp999-cp999-win_amd64"])
    wheel_path = _write_wheel(tmp_path, wheel, filename)
    with pytest.raises(SmokeError) as exc:
        await smoke_test(
            wheel_container_path=wheel_path,
            wheel_host_path=wheel_path,
            expected_name="sentence-transformers",
            expected_version="2.2.2",
        )
    assert exc.value.reason == "wheel_tag_mismatch"


# ── RECORD checks ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unlisted_file_refused(tmp_path):
    """A file in the zip but not in RECORD is a classic attack:
    an unlisted .pth runs import at interpreter start."""
    filename = _wheel_filename()
    wheel = _make_wheel(
        extra_files={"sentence_transformers/evil.pth": b"import os\n"},
        omit_record_entries=["sentence_transformers/evil.pth"],
    )
    wheel_path = _write_wheel(tmp_path, wheel, filename)
    with pytest.raises(SmokeError) as exc:
        await smoke_test(
            wheel_container_path=wheel_path,
            wheel_host_path=wheel_path,
            expected_name="sentence-transformers",
            expected_version="2.2.2",
        )
    assert exc.value.reason == "record_unlisted_file"


@pytest.mark.asyncio
async def test_hash_mismatch_refused(tmp_path):
    """A file listed in RECORD whose hash doesn't match."""
    filename = _wheel_filename()
    wheel = _make_wheel(
        bad_hashes={"sentence_transformers/core.py": "0" * 43},
    )
    wheel_path = _write_wheel(tmp_path, wheel, filename)
    with pytest.raises(SmokeError) as exc:
        await smoke_test(
            wheel_container_path=wheel_path,
            wheel_host_path=wheel_path,
            expected_name="sentence-transformers",
            expected_version="2.2.2",
        )
    assert exc.value.reason == "record_hash_mismatch"


@pytest.mark.asyncio
async def test_pth_import_line_refused(tmp_path):
    """A .pth file with an import line runs code at interpreter
    start. Refuse even if the .pth is in RECORD with a valid
    hash."""
    filename = _wheel_filename()
    wheel = _make_wheel(
        pth_content=b"import os\nos.system('touch /tmp/pwned')\n",
    )
    wheel_path = _write_wheel(tmp_path, wheel, filename)
    with pytest.raises(SmokeError) as exc:
        await smoke_test(
            wheel_container_path=wheel_path,
            wheel_host_path=wheel_path,
            expected_name="sentence-transformers",
            expected_version="2.2.2",
        )
    assert exc.value.reason == "pth_import_line"


# ── import check ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_module_not_importable_refused(tmp_path, monkeypatch):
    """If the container can't find_spec the module, refuse."""
    filename = _wheel_filename()
    wheel_path = _write_wheel(tmp_path, _make_wheel(), filename)

    async def fake_exec(*argv, **kwargs):
        proc = MagicMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(
            return_value=(b"MISSING:sentence_transformers\n", None),
        )
        return proc

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec", fake_exec,
    )
    with pytest.raises(SmokeError) as exc:
        await smoke_test(
            wheel_container_path=wheel_path,
            wheel_host_path=wheel_path,
            expected_name="sentence-transformers",
            expected_version="2.2.2",
        )
    assert exc.value.reason == "module_not_importable"
    assert "sentence_transformers" in exc.value.detail


@pytest.mark.asyncio
async def test_import_timeout_refused(tmp_path, monkeypatch):
    import asyncio as _aio
    filename = _wheel_filename()
    wheel_path = _write_wheel(tmp_path, _make_wheel(), filename)

    async def fake_exec(*argv, **kwargs):
        proc = MagicMock()
        proc.communicate = AsyncMock(side_effect=_aio.TimeoutError)
        proc.kill = MagicMock()
        proc.wait = AsyncMock()
        return proc

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec", fake_exec,
    )
    with pytest.raises(SmokeError) as exc:
        await smoke_test(
            wheel_container_path=wheel_path,
            wheel_host_path=wheel_path,
            expected_name="sentence-transformers",
            expected_version="2.2.2",
        )
    assert exc.value.reason == "import_timeout"
