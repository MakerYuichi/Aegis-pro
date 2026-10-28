"""
Tests for src.agents.prefetch.sanitize.

The sanitizer's contract: read a manifest, return a list of
PackagePin. Both exact pins and version ranges are accepted.
Directives are stripped. Malformed lines are rejected with a
specific reason and line number.

The fixture corpus is shared with the container-side sanitizer via
an agreement test at the bottom of this file. If the two
implementations ever drift, that test fails.
"""
from __future__ import annotations

import importlib.util as _importlib_util
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


# ── happy path: pinned ──────────────────────────────────────────

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
    assert fastapi.is_pinned is True
    assert fastapi.base_version == "0.115.11"
    assert fastapi.local_variant == ""
    assert fastapi.raw_specifier == "==0.115.11"
    assert fastapi.extras == ()
    assert fastapi.environment_marker is None
    assert fastapi.line_number == 1


def test_extras_preserved():
    pins = sanitize_manifest(FIXTURES / "pinned_manifest.txt")
    uvicorn = next(p for p in pins if p.name == "uvicorn")
    assert uvicorn.extras == ("standard",)


# ── ranges accepted (Option C) ─────────────────────────────────

def test_unpinned_range_accepted():
    """
    Ranges are accepted, not rejected. The sanitizer records
    is_pinned=False and preserves the raw specifier so the
    prefetcher's pip resolver can pick an absolute version.
    """
    pins = sanitize_manifest(FIXTURES / "unpinned_manifest.txt")
    names = [p.name for p in pins]
    assert "httpx" in names
    httpx_pin = next(p for p in pins if p.name == "httpx")
    assert httpx_pin.is_pinned is False
    assert httpx_pin.base_version == ""
    assert httpx_pin.raw_specifier == ">=0.28.1"


@pytest.mark.parametrize("line,expected_spec", [
    ("pkg>=1.0", ">=1.0"),
    ("pkg<=1.0", "<=1.0"),
    ("pkg~=1.0", "~=1.0"),
    ("pkg!=1.0", "!=1.0"),
    ("pkg>1.0", ">1.0"),
    ("pkg<1.0", "<1.0"),
    ("pkg", ""),
])
def test_all_range_operators_accepted(tmp_path, line, expected_spec):
    f = tmp_path / "req.txt"
    f.write_text(line + "\n")
    pins = sanitize_manifest(f)
    assert len(pins) == 1
    assert pins[0].is_pinned is False
    assert pins[0].raw_specifier == expected_spec


def test_bare_name_accepted(tmp_path):
    f = tmp_path / "req.txt"
    f.write_text("pkg\n")
    pins = sanitize_manifest(f)
    assert pins[0].is_pinned is False
    assert pins[0].raw_specifier == ""


# ── variants (Option C) ─────────────────────────────────────────

def test_variant_manifest_splits_base_and_variant():
    pins = sanitize_manifest(FIXTURES / "variant_manifest.txt")
    torch = next(p for p in pins if p.name == "torch")
    assert torch.is_pinned is True
    assert torch.base_version == "2.14.0"
    assert torch.local_variant == "cpu"
    assert torch.raw_specifier == "==2.14.0+cpu"
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
    assert exc_info.value.reason == "malformed_requirement"


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

ENTRYPOINT_PATH = (
    Path(__file__).parents[2] / "scripts" / "prefetch_entrypoint.py"
)


def _load_entrypoint_module():
    """Load scripts/prefetch_entrypoint.py as a module for agreement tests.

    The script imports `parsers` at the top:
        from parsers import parse_manifest, ManifestParseError

    That's a bare import, not a package-relative one, because
    inside the prefetch container the script and parsers.py are
    both mounted at /opt, and PYTHONPATH=/opt puts them on
    sys.path together.

    In the orchestrator's test environment, /opt doesn't exist and
    src/agents/prefetch/ isn't on sys.path. The bare `parsers`
    import would fail with ModuleNotFoundError: No module named
    'parsers'. This helper adds src/agents/prefetch/ to sys.path
    before loading the script, so `from parsers import ...`
    resolves to the same file the container uses.

    This is what the container's PYTHONPATH=/opt mount achieves —
    the test reproduces that arrangement in-process. No production
    code change; the script's `from parsers import ...` is
    unchanged.
    """
    import sys
    parsers_dir = (
        Path(__file__).parents[2] / "src" / "agents" / "prefetch"
    )
    parsers_dir_str = str(parsers_dir)
    if parsers_dir_str not in sys.path:
        sys.path.insert(0, parsers_dir_str)

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
    assert [p.is_pinned for p in orch_pins] == [
        p["is_pinned"] for p in cont_pins
    ]


def test_container_sanitizer_agrees_on_variants():
    mod = _load_entrypoint_module()
    orch_pins = sanitize_manifest(FIXTURES / "variant_manifest.txt")
    cont_pins = mod.sanitize(FIXTURES / "variant_manifest.txt")
    for op, cp in zip(orch_pins, cont_pins):
        assert op.name == cp["name"]
        assert op.base_version == cp["base_version"]
        assert op.local_variant == cp["local_variant"]
        assert op.is_pinned == cp["is_pinned"]


def test_container_sanitizer_agrees_on_directives():
    """--extra-index-url is stripped, not rejected, in both
    implementations. Same set of pins comes out."""
    mod = _load_entrypoint_module()
    orch_pins = sanitize_manifest(FIXTURES / "directive_manifest.txt")
    cont_pins = mod.sanitize(FIXTURES / "directive_manifest.txt")
    assert [p.name for p in orch_pins] == [p["name"] for p in cont_pins]


def test_container_sanitizer_agrees_on_ranges():
    """Both implementations accept ranges. The raw specifier is
    preserved on both sides. This is the Option C agreement —
    without it, the orchestrator could accept a range and the
    container reject it, or vice versa."""
    mod = _load_entrypoint_module()
    orch_pins = sanitize_manifest(FIXTURES / "unpinned_manifest.txt")
    cont_pins = mod.sanitize(FIXTURES / "unpinned_manifest.txt")
    for op, cp in zip(orch_pins, cont_pins):
        assert op.name == cp["name"]
        assert op.is_pinned == cp["is_pinned"]
        assert op.raw_specifier == cp["raw_specifier"]


def test_container_sanitizer_agrees_on_variant_routing():
    """Both implementations route torch+cpu to the CPU index. This
    is the Option C agreement on routing — the container's route()
    and the orchestrator's route_pin() must produce the same URL."""
    mod = _load_entrypoint_module()
    torch_pin_dict = {
        "name": "torch",
        "base_version": "2.14.0",
        "local_variant": "cpu",
        "is_pinned": True,
    }
    container_route = mod.route(torch_pin_dict)

    from src.agents.prefetch.policy import route_pin
    from src.agents.prefetch.sanitize import PackagePin
    orch_pin = PackagePin(
        name="torch", is_pinned=True, base_version="2.14.0",
        local_variant="cpu", raw_specifier="==2.14.0+cpu",
        extras=(), environment_marker=None, explicit_hashes=(),
        raw_line="torch==2.14.0+cpu", line_number=1,
    )
    orchestrator_route = route_pin(orch_pin).index_url

    assert container_route == orchestrator_route
    assert container_route == "https://download.pytorch.org/whl/cpu"
