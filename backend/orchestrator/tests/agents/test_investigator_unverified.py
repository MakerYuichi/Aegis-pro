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



# ---------------------------------------------------------------------------
# Regression tests for the reasoned_only escape hatch
#
# Bug: on 2026-10-27, the agent claimed probe_reproduced without running
# a probe. _validate_scan_confirmation downgraded to reasoned_only and
# called _append_downgrade_note, which wrote the word "probe" into the
# evidence. The next check tested `"probe" in evidence` — which the note
# had just made True. The escape hatch was self-satisfying.
#
# Fix: the policy check now reads history (the structural fact) and
# requires an actual probe observation. These tests pin that.
# ---------------------------------------------------------------------------

from src.agents.investigator import (
    _validate_scan_confirmation,
    _reasoned_only_is_legitimate,
)
from src.agents.investigator_models import (
    CONFIRMATION_PROBE_REPRODUCED,
    CONFIRMATION_REASONED_ONLY,
    STATUS_CONFIRMED,
    STATUS_UNVERIFIED,
    STATUS_REFUSED,
    REFUSE_COULD_NOT_DETERMINE,
    REFUSE_FALSE_POSITIVE,
    InvestigationResult,
)


def _make_confirmed(
    confirmation: str,
    evidence: str = "",
    fix_location: str = "requests/status_codes.py",
    failure_mode: str = "TypeError when __doc__ is None",
) -> InvestigationResult:
    return InvestigationResult(
        status=STATUS_CONFIRMED,
        failure_mode=failure_mode,
        fix_location=fix_location,
        evidence=evidence,
        confidence=0.95,
        confirmation=confirmation,
        history=[],
    )


CHAIN = [{"file": "requests/status_codes.py", "line": 116}]


def test_reasoned_only_rejected_when_no_probe_in_history():
    """
    The 329B7F shape: agent wrote 'a probe would need -OO' in
    evidence, but never called the probe tool. Must be rejected,
    not accepted on the word 'probe'.
    """
    result = _make_confirmed(
        confirmation=CONFIRMATION_REASONED_ONLY,
        evidence="a probe would need -OO to reproduce",
    )

    out = _validate_scan_confirmation(result, history=[], chain=CHAIN)

    assert out.status == STATUS_UNVERIFIED
    assert out.reason == REFUSE_COULD_NOT_DETERMINE


def test_reasoned_only_rejected_when_probe_ran_clean():
    """
    A probe ran, exited 0, no exception. The bug wasn't
    reproduced. Not legitimate — and not environmental.
    """
    history = [
        {
            "tool": "probe",
            "ok": True,
            "args": {"code": "import requests.status_codes"},
            "result": "",
            "metadata": {"ran": True, "reproduced": False, "exit_code": 0},
        }
    ]
    result = _make_confirmed(
        confirmation=CONFIRMATION_REASONED_ONLY,
        evidence="probe did not reproduce",
    )

    out = _validate_scan_confirmation(result, history=history, chain=CHAIN)

    assert out.status == STATUS_UNVERIFIED
    assert out.reason == REFUSE_COULD_NOT_DETERMINE


def test_reasoned_only_accepted_when_probe_failed_environmentally():
    """
    The DBF975 shape: probe ran, failed with ModuleNotFoundError.
    Environmental failure — accept.
    """
    history = [
        {
            "tool": "probe",
            "ok": True,
            "args": {"code": "import requests"},
            "result": "ModuleNotFoundError: No module named 'urllib3'",
            "metadata": {"ran": True, "reproduced": False, "exit_code": 1},
        }
    ]
    result = _make_confirmed(
        confirmation=CONFIRMATION_REASONED_ONLY,
        evidence="probe failed with ModuleNotFoundError",
    )

    out = _validate_scan_confirmation(result, history=history, chain=CHAIN)

    assert out.status == STATUS_CONFIRMED
    assert out.confirmation == CONFIRMATION_REASONED_ONLY


def test_reasoned_only_accepted_when_sandbox_disabled():
    """Probe tool returned ok=False with sandbox_disabled. Legitimate."""
    history = [
        {
            "tool": "probe",
            "ok": False,
            "error": "sandbox_disabled",
            "metadata": {"ran": False, "reproduced": False,
                         "reason": "VERIFY_BEFORE_REPORT is false; sandbox unavailable"},
        }
    ]
    result = _make_confirmed(
        confirmation=CONFIRMATION_REASONED_ONLY,
        evidence="sandbox unavailable",
    )

    out = _validate_scan_confirmation(result, history=history, chain=CHAIN)

    assert out.status == STATUS_CONFIRMED


def test_probe_reproduced_downgraded_when_no_successful_probe():
    """
    Agent claims probe_reproduced, no probe observation exists.
    Downgrade to reasoned_only, then reject (because no probe
    attempt either). End state: unverified.
    """
    result = _make_confirmed(
        confirmation=CONFIRMATION_PROBE_REPRODUCED,
        evidence="probe reproduced the TypeError",
    )

    out = _validate_scan_confirmation(result, history=[], chain=CHAIN)

    assert out.status == STATUS_UNVERIFIED
    assert out.reason == REFUSE_COULD_NOT_DETERMINE


def test_probe_reproduced_accepted_when_probe_reproduced():
    """
    Agent claims probe_reproduced, probe observation exists with
    metadata.reproduced=True. Accept unchanged.
    """
    history = [
        {
            "tool": "probe",
            "ok": True,
            "args": {"code": "import requests.status_codes",
                     "interpreter_flags": ["-OO"]},
            "result": "TypeError: unsupported operand type(s) for +: "
                      "'NoneType' and 'str'",
            "metadata": {"ran": True, "reproduced": True, "exit_code": 1},
        }
    ]
    result = _make_confirmed(
        confirmation=CONFIRMATION_PROBE_REPRODUCED,
        evidence="probe reproduced TypeError under -OO",
    )

    out = _validate_scan_confirmation(result, history=history, chain=CHAIN)

    assert out.status == STATUS_CONFIRMED
    assert out.confirmation == CONFIRMATION_PROBE_REPRODUCED


def test_fix_location_outside_chain_rejected():
    """Unrelated sanity check: the chain check still works."""
    result = _make_confirmed(
        confirmation=CONFIRMATION_PROBE_REPRODUCED,
        evidence="probe reproduced",
        fix_location="some/other/file.py",
    )
    history = [
        {
            "tool": "probe",
            "ok": True,
            "result": "TypeError",
            "metadata": {"ran": True, "reproduced": True, "exit_code": 1},
        }
    ]

    out = _validate_scan_confirmation(result, history=history, chain=CHAIN)

    assert out.status == STATUS_REFUSED
    assert out.reason == REFUSE_FALSE_POSITIVE


def test_reasoned_only_helper_rejects_empty_history():
    """Direct unit test of the helper."""
    legit, why = _reasoned_only_is_legitimate([])
    assert legit is False
    assert "no probe" in why.lower()
