"""
Tests for merge_incident_metadata — the read-merge-write helper
that replaced the blind-SET save_incident_metadata.

This is the single most load-bearing correctness point in 12.1a:
every record_* method calls it (or its sibling pattern), and a
regression here silently drops writes from the incident row.
"""
import json
import pytest

from src.services.incident_service import merge_incident_metadata


def test_merge_into_none_creates_object():
    """existing=None → {"key": value}"""
    result = merge_incident_metadata(None, "code_context", {"file": "x.py"})
    assert json.loads(result) == {"code_context": {"file": "x.py"}}


def test_merge_into_empty_string_creates_object():
    result = merge_incident_metadata("", "code_context", {"file": "x.py"})
    assert json.loads(result) == {"code_context": {"file": "x.py"}}


def test_merge_into_valid_json_preserves_existing_keys():
    """The whole point — existing keys must survive the merge."""
    existing = json.dumps({"rag_context_used": True, "reported_by": "alice"})
    result = merge_incident_metadata(existing, "code_context", {"file": "x.py"})
    parsed = json.loads(result)
    assert parsed["rag_context_used"] is True
    assert parsed["reported_by"] == "alice"
    assert parsed["code_context"] == {"file": "x.py"}


def test_merge_into_malformed_json_starts_fresh():
    """Malformed JSON should not raise — degrade to {} and proceed."""
    result = merge_incident_metadata("{not json", "key", "value")
    assert json.loads(result) == {"key": "value"}


def test_merge_into_dict_passthrough():
    """SQLAlchemy may hand us a decoded dict instead of a string."""
    existing = {"rag_context_used": True}
    result = merge_incident_metadata(existing, "code_context", {"file": "x.py"})
    parsed = json.loads(result)
    assert parsed["rag_context_used"] is True
    assert parsed["code_context"] == {"file": "x.py"}


def test_merge_overwrites_same_key():
    """Re-writing the same key replaces the old value."""
    existing = json.dumps({"code_context": {"old": True}})
    result = merge_incident_metadata(existing, "code_context", {"new": True})
    assert json.loads(result)["code_context"] == {"new": True}


def test_merge_into_non_dict_json_starts_fresh():
    """A JSON array or scalar in the column should not crash us."""
    result = merge_incident_metadata("[1, 2, 3]", "key", "value")
    assert json.loads(result) == {"key": "value"}
