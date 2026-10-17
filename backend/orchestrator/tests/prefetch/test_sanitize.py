"""
Tests for src.agents.prefetch.sanitize.

The sanitizer's contract: read a manifest, return a list of
PackagePin, or raise SanitizeError naming the offending line. Every
test either asserts a shape or asserts a specific rejection reason.

The fixture corpus is shared with the container-side sanitizer (see
scripts/prefetch_entrypoint.py) via an agreement test at the bottom
of this file. If the two implementations ever drift, that test fails.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.prefetch.sanitize import (
    PackagePin,
    SanitizeError,
    normalize_name,
    sanitize_manifest,
)


FIXTURES = Path(__file__).parent / "fixtures"


# ── normalize_name ──────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("fastapi", "fastapi"),
    ("FastAPI", "fastapi"),
    ("scikit_learn", "scikit-learn"),
    ("scikit.learn", "scikit-learn"),
    ("scikit-learn", "scikit-learn"),
    ("PyGithub", "pygithub"),
    ("typing_extensions", "typing-extensions"),
])
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


# ── happy path ──────────────────────────────────────────────────

def test_pinned_manifest_parses_all_pins():
    pins = sanitize_manifest(FIXTURES / "pinned_manifest.txt")
    names = [p.name for p in pins]
    assert names == [
        "fastapi", "uvicorn", "pydantic",
        "sqlalchemy", "httpx", "loguru",
    ]


def test_pin_shape():
    pins = sanitize_manifest(FIXTURES / "pinned_manifest.txt")
    fastapi = pins[0]
    assert fastapi.name == "fastapi"
    assert fastapi.base_version == "0.115.11"
    assert fastapi.local_variant == ""
    assert fastapi.extras == ()
    assert fastapi.environment_marker is None
    assert fastapi.explicit_hashes == ()
    assert fastapi.line_number == 1


def test_extras_preserved():
    pins = sanitize_manifest(FIXTURES / "pinned_manifest.txt")
    uvicorn = next(p for p in pins if p.name == "uvicorn")
    assert uvicorn.extras == ("standard",)


# ── variants (Option C) ─────────────────────────────────────────

def test_variant_manifest_splits_base_and_variant():
    pins = sanitize_manifest(FIXTURES / "variant_manifest.txt")
    torch = next(p for p in pins if p.name == "torch")
    assert torch.base_version == "2.14.0"
    assert torch.local_variant == "cpu"
    # The original line is preserved verbatim for error messages.
    assert torch.raw_line.strip() == "torch==2.14.0+cpu"


def test_variant_and_nonvariant_coexist():
    pins = sanitize_manifest(FIXTURES / "variant_manifest.txt")
    by_name = {p.name: p for p in pins}
    assert by_name["torch"].local_variant == "cpu"
    assert by_name["numpy"].local_variant == ""


# ── directives ──────────────────────────────────────────────────

def test_extra_index_url_stripped_not_rejected():
    """--extra-index-url is stripped, not fatal. The prefetcher's
    own policy decides indexes; the manifest's opinion is discarded."""
    pins = sanitize_manifest(FIXTURES / "directive_manifest.txt")
    assert len(pins) == 3
    assert {p.name for p in pins} == {"fastapi", "torch", "numpy"}


# ── unpinned rejection ──────────────────────────────────────────

def test_unpinned_rejects_with_reason_and_line():
    with pytest.raises(SanitizeError) as exc_info:
        sanitize_manifest(FIXTURES / "unpinned_manifest.txt")
    err = exc_info.value
    assert err.reason.startswith("unpinned_dependency")
    assert err.line_number == 2
    assert "httpx>=0.28.1" in err.line_content


@pytest.mark.parametrize("line,reason_fragment", [
    ("pkg >= 1.0", "unpinned_dependency"),
    ("pkg <= 1.0", "unpinned_dependency"),
    ("pkg ~= 1.0", "unpinned_dependency"),
    ("pkg != 1.0", "unpinned_dependency"),
    ("pkg > 1.0", "unpinned_dependency"),
    ("pkg < 1.0", "unpinned_dependency"),
    ("pkg", "unpinned_dependency"),
])
def test_all_range_operators_rejected(tmp_path, line, reason_fragment):
    f = tmp_path / "req.txt"
    f.write_text(line + "\n")
    with pytest.raises(SanitizeError) as exc_info:
        sanitize_manifest(f)
    assert reason_fragment in exc_info.value.reason


# ── direct URLs and editables ───────────────────────────────────

def test_direct_url_rejected(tmp_path):
    f = tmp_path / "req.txt"
    f.write_text("evil @ https://evil.example/pkg.tar.gz\n")
    with pytest.raises(SanitizeError) as exc_info:
        sanitize_manifest(f)
    assert exc_info.value.reason == "direct_url_not_allowed"


def test_editable_rejected(tmp_path):
    f = tmp_path / "req.txt"
    f.write_text("-e git+https://example.com/repo.git#egg=pkg\n")
    with pytest.raises(SanitizeError) as exc_info:
        sanitize_manifest(f)
    assert "rejected_directive" in exc_info.value.reason


# ── environment markers ─────────────────────────────────────────

def test_environment_markers_preserved():
    pins = sanitize_manifest(FIXTURES / "env_marker_manifest.txt")
    d = next(p for p in pins if p.name == "dataclasses-json")
    assert d.environment_marker == 'python_version < "3.13"'


# ── empty and malformed ─────────────────────────────────────────

def test_empty_manifest_rejected(tmp_path):
    f = tmp_path / "req.txt"
    f.write_text("# just a comment\n\n")
    with pytest.raises(SanitizeError) as exc_info:
        sanitize_manifest(f)
    assert exc_info.value.reason == "empty_manifest"


def test_malformed_pin_rejected(tmp_path):
    f = tmp_path / "req.txt"
    f.write_text("pkg==not a valid version !!!\n")
    with pytest.raises(SanitizeError) as exc_info:
        sanitize_manifest(f)
    assert exc_info.value.reason in (
        "malformed_pin", "unpinned_dependency",
    )


def test_multiline_hash_rejected(tmp_path):
    f = tmp_path / "req.txt"
    f.write_text("pkg==1.0 \\\n    --hash=sha256:abc\n")
    with pytest.raises(SanitizeError) as exc_info:
        sanitize_manifest(f)
    assert exc_info.value.reason == "multiline_hash_not_supported"


# ── the agreement test ──────────────────────────────────────────
#
# The container's sanitizer is a separate implementation. These
# tests assert it agrees with the orchestrator's on the fixture
# corpus. If they drift, one of the two has a bug.

import importlib.util as _importlib_util

ENTRYPOINT_PATH = (
    Path(__file__).parents[2] / "scripts" / "prefetch_entrypoint.py"
)


def _load_entrypoint_module():
    """
    Load scripts/prefetch_entrypoint.py as a module.

    The entrypoint has no imports from src/ — that's the whole
    point — so exec_module works without stubbing anything.
    """
    spec = _importlib_util.spec_from_file_location(
        "prefetch_entrypoint", ENTRYPOINT_PATH,
    )
    mod = _importlib_util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_entrypoint_script_exists():
    """Guard: if the path is wrong, the agreement tests fail with a
    clearer message than FileNotFoundError inside importlib."""
    assert ENTRYPOINT_PATH.is_file(), (
        f"prefetch entrypoint not found at {ENTRYPOINT_PATH}"
    )


def test_container_sanitizer_agrees_on_pinned():
    mod = _load_entrypoint_module()
    orch_pins = sanitize_manifest(FIXTURES / "pinned_manifest.txt")
    cont_pins = mod.sanitize(FIXTURES / "pinned_manifest.txt")
    assert [p.name for p in orch_pins] == [p["name"] for p in cont_pins]
    assert [p.base_version for p in orch_pins] == [
        p["base_version"] for p in cont_pins
    ]
    assert [p.local_variant for p in orch_pins] == [
        p["local_variant"] for p in cont_pins
    ]


def test_container_sanitizer_agrees_on_variants():
    mod = _load_entrypoint_module()
    orch_pins = sanitize_manifest(FIXTURES / "variant_manifest.txt")
    cont_pins = mod.sanitize(FIXTURES / "variant_manifest.txt")
    for op, cp in zip(orch_pins, cont_pins):
        assert op.name == cp["name"]
        assert op.base_version == cp["base_version"]
        assert op.local_variant == cp["local_variant"]


def test_container_sanitizer_agrees_on_directives():
    """--extra-index-url is stripped, not rejected, in both
    implementations. Same set of pins comes out."""
    mod = _load_entrypoint_module()
    orch_pins = sanitize_manifest(FIXTURES / "directive_manifest.txt")
    cont_pins = mod.sanitize(FIXTURES / "directive_manifest.txt")
    assert [p.name for p in orch_pins] == [p["name"] for p in cont_pins]


def test_container_sanitizer_agrees_on_unpinned_rejection():
    mod = _load_entrypoint_module()
    with pytest.raises(Exception) as orch_err:
        sanitize_manifest(FIXTURES / "unpinned_manifest.txt")
    with pytest.raises(Exception) as cont_err:
        mod.sanitize(FIXTURES / "unpinned_manifest.txt")
    assert "unpinned_dependency" in str(orch_err.value)
    assert "unpinned_dependency" in str(cont_err.value)


def test_container_sanitizer_agrees_on_variant_routing():
    """Both implementations route torch+cpu to the CPU index. This is
    the Option C agreement — the container's route() and the
    orchestrator's route_pin() must produce the same URL."""
    mod = _load_entrypoint_module()
    torch_pin = {
        "name": "torch",
        "base_version": "2.14.0",
        "local_variant": "cpu",
    }
    container_route = mod.route(torch_pin)

    from src.agents.prefetch.policy import route_pin
    from src.agents.prefetch.sanitize import PackagePin
    orch_pin = PackagePin(
        name="torch", base_version="2.14.0", local_variant="cpu",
        extras=(), environment_marker=None, explicit_hashes=(),
        raw_line="torch==2.14.0+cpu", line_number=1,
    )
    orchestrator_route = route_pin(orch_pin).index_url

    assert container_route == orchestrator_route
    assert container_route == "https://download.pytorch.org/whl/cpu"
