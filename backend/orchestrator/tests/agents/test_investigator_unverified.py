"""Tests for the unverified status — the fix for issue #130.

When the Investigator refuses with reason="could_not_determine", it
isn't claiming the finding is a false positive. It's saying it
couldn't decide. The pipeline must present that differently from a
false_positive refusal.

Before this fix, both reasons produced status="refused" and the CLI
grouped them under "Refused (not bugs)". After this fix,
could_not_determine produces status="unverified" and the CLI groups
it under "Needs Review (unverified)".
"""
from __future__ import annotations

import pytest

from src.agents.investigator import InvestigatorAgent
from src.agents.investigator_models import (
    ALL_STATUSES,
    MODE_SCAN,
    REFUSE_COULD_NOT_DETERMINE,
    REFUSE_FALSE_POSITIVE,
    STATUS_REFUSED,
    STATUS_UNVERIFIED,
    InvestigationResult,
    InvestigatorAction,
)


def _action(reason: str) -> InvestigatorAction:
    return InvestigatorAction(
        action="refuse",
        thought="test",
        args={"reason": reason, "candidates_considered": []},
        mode=MODE_SCAN,
    )


def test_unverified_status_constant_exists():
    """The new status constant is present and registered."""
    assert STATUS_UNVERIFIED == "unverified"
    assert STATUS_UNVERIFIED in ALL_STATUSES


def test_could_not_determine_maps_to_unverified():
    """A refusal with reason=could_not_determine produces
    status=unverified."""
    result = InvestigatorAgent._refuse_result(
        _action(REFUSE_COULD_NOT_DETERMINE), iteration=3, history=[]
    )
    assert result.status == STATUS_UNVERIFIED
    assert result.reason == REFUSE_COULD_NOT_DETERMINE


def test_false_positive_stays_refused():
    """A refusal with reason=false_positive stays as refused —
    the Investigator is confident the finding is not a bug."""
    result = InvestigatorAgent._refuse_result(
        _action(REFUSE_FALSE_POSITIVE), iteration=3, history=[]
    )
    assert result.status == STATUS_REFUSED
    assert result.reason == REFUSE_FALSE_POSITIVE


def test_unverified_preserves_history_and_thought():
    """The unverified result carries the same audit trail as
    refused. Nothing is lost by the relabeling."""
    history = [{"tool": "read_file", "ok": True, "result": "..."}]
    action = InvestigatorAction(
        action="refuse",
        thought="couldn't decide between two guards",
        args={"reason": REFUSE_COULD_NOT_DETERMINE,
              "candidates_considered": ["self.headers"]},
        mode=MODE_SCAN,
    )
    result = InvestigatorAgent._refuse_result(
        action, iteration=5, history=history
    )
    assert result.status == STATUS_UNVERIFIED
    assert result.thought == "couldn't decide between two guards"
    assert result.candidates_considered == ["self.headers"]
    assert result.iterations == 5
    assert result.history == history


def test_unverified_is_not_a_success():
    """unverified findings produce no auto-fix. is_success stays
    False."""
    result = InvestigationResult(
        status=STATUS_UNVERIFIED,
        reason=REFUSE_COULD_NOT_DETERMINE,
    )
    assert result.is_success is False

def test_validate_scan_confirmation_could_not_determine_maps_to_unverified():
    """The _refuse helper used by _validate_scan_confirmation must
    also apply the mapping. A refusal with reason=could_not_determine
    that comes from post-hoc validation should still produce
    status=unverified."""
    from src.agents.investigator import _refuse
    from src.agents.investigator_models import (
        InvestigationResult, STATUS_CONFIRMED, STATUS_UNVERIFIED,
        REFUSE_COULD_NOT_DETERMINE,
    )
    
    confirmed = InvestigationResult(
        status=STATUS_CONFIRMED,
        failure_mode="some mode",
        fix_location="src/foo.py",
        confirmation="reasoned_only",
        evidence="",  # no probe stated — the case that triggers downgrade
    )
    refused = _refuse(
        confirmed, history=[], reason=REFUSE_COULD_NOT_DETERMINE,
        candidates=["some mode"],
    )
    assert refused.status == STATUS_UNVERIFIED
    assert refused.reason == REFUSE_COULD_NOT_DETERMINE
