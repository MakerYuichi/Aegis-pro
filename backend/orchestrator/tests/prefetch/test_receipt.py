"""
Tests for src.agents.prefetch.receipt.

The container announces the receipt as the last line of stdout.
parse_receipt() reads that line. Everything before it is pip output
and is not our concern.
"""
from __future__ import annotations

import json

import pytest

from src.agents.prefetch.receipt import (
    MAX_RECEIPT_LINE_BYTES,
    PrefetchReceipt,
    ReceiptError,
    parse_receipt,
)


def _valid_payload():
    return {
        "manifest_path": "requirements.txt",
        "manifest_hash": "sha256:" + "a" * 64,
        "python_version": "3.11.16",
        "platform_tag": "linux_x86_64",
        "packages": [
            {
                "name": "fastapi",
                "base_version": "0.115.11",
                "local_variant": "",
                "extras": [],
                "environment_marker": None,
                "hashes": ["sha256:abc"],
                "source_index": "https://pypi.org/simple/",
                "filename": "fastapi-0.115.11-py3-none-any.whl",
                "dependencies": [],
            },
        ],
        "fetched_now": True,
        "duration_ms": 1234,
    }


# ── happy path ──────────────────────────────────────────────────

def test_parses_last_line_with_pip_output_before():
    stdout = (
        "Collecting fastapi==0.115.11\n"
        "  Downloading fastapi-0.115.11-py3-none-any.whl\n"
        "Successfully downloaded fastapi\n"
        + json.dumps(_valid_payload())
    )
    receipt = parse_receipt(stdout)
    assert isinstance(receipt, PrefetchReceipt)
    assert receipt.manifest_path == "requirements.txt"
    assert receipt.python_version == "3.11.16"
    assert receipt.fetched_now is True
    assert receipt.duration_ms == 1234
    assert len(receipt.packages) == 1


def test_preserves_variant_field():
    payload = _valid_payload()
    payload["packages"][0]["local_variant"] = "cpu"
    payload["packages"][0]["source_index"] = (
        "https://download.pytorch.org/whl/cpu"
    )
    stdout = json.dumps(payload)
    receipt = parse_receipt(stdout)
    assert receipt.packages[0]["local_variant"] == "cpu"
    assert (
        receipt.packages[0]["source_index"]
        == "https://download.pytorch.org/whl/cpu"
    )


# ── error cases ─────────────────────────────────────────────────

def test_empty_stdout_raises():
    with pytest.raises(ReceiptError) as exc_info:
        parse_receipt("")
    assert exc_info.value.reason == "empty_stdout"


def test_whitespace_only_stdout_raises():
    with pytest.raises(ReceiptError) as exc_info:
        parse_receipt("   \n\n  \n")
    assert exc_info.value.reason == "empty_stdout"


def test_last_line_not_json_raises():
    with pytest.raises(ReceiptError) as exc_info:
        parse_receipt("some pip output\nnot json at all\n")
    assert exc_info.value.reason == "receipt_not_json"


def test_last_line_is_json_array_raises():
    with pytest.raises(ReceiptError) as exc_info:
        parse_receipt("[1, 2, 3]")
    assert exc_info.value.reason == "receipt_not_object"


@pytest.mark.parametrize("missing_key", [
    "manifest_path",
    "manifest_hash",
    "python_version",
    "platform_tag",
    "packages",
    "fetched_now",
    "duration_ms",
])
def test_missing_required_field_raises(missing_key):
    payload = _valid_payload()
    del payload[missing_key]
    with pytest.raises(ReceiptError) as exc_info:
        parse_receipt(json.dumps(payload))
    assert exc_info.value.reason == "receipt_missing_field"
    assert missing_key in exc_info.value.detail


def test_packages_not_list_raises():
    payload = _valid_payload()
    payload["packages"] = {"not": "a list"}
    with pytest.raises(ReceiptError) as exc_info:
        parse_receipt(json.dumps(payload))
    assert exc_info.value.reason == "receipt_packages_not_list"


def test_oversized_last_line_raises():
    huge = "x" * (MAX_RECEIPT_LINE_BYTES + 100)
    with pytest.raises(ReceiptError) as exc_info:
        parse_receipt(f"pip output\n{huge}")
    assert exc_info.value.reason == "receipt_too_large"


# ── the empty-packages case ────────────────────────────────────
#
# A repo with a manifest that resolves to zero packages is
# impossible in practice — the sanitizer rejects an empty manifest
# before we get here. But the receipt shape must accept an empty
# list, because a prefetch that finds a warm cache and skips the
# download still has to report the same set of packages it found
# last time. In PR 1, that case doesn't happen yet (every prefetch
# downloads). When the cache-hit path lands, this stays valid.

def test_empty_packages_list_accepted():
    payload = _valid_payload()
    payload["packages"] = []
    payload["fetched_now"] = False
    receipt = parse_receipt(json.dumps(payload))
    assert receipt.packages == []
    assert receipt.fetched_now is False
