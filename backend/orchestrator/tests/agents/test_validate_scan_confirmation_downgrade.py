"""Regression tests for the downgrade-then-refuse cascade.

Before this test file, _validate_scan_confirmation had a trap: it
downgraded a probe_reproduced confirmation to reasoned_only when the
history had no successful probe, then the very next check refused
the finding because the evidence didn't say "probe not possible" —
even though the agent never had a chance to write that, because it
believed its probe succeeded when it composed the evidence.

The acceptance bug (status_codes.py:116) hit this exact trap. These
tests verify the fix: on downgrade, the evidence is annotated so
the reasoned_only check passes.
"""
from src.agents.investigator import _validate_scan_confirmation, _append_downgrade_note
from src.agents.investigator_models import (
    CONFIRMATION_PROBE_REPRODUCED,
    CONFIRMATION_REASONED_ONLY,
    STATUS_UNVERIFIED,
    REFUSE_COULD_NOT_DETERMINE, 
    STATUS_CONFIRMED,
    STATUS_REFUSED,
    STATUS_UNVERIFIED,
    InvestigationResult,
)


def _confirmed(
    confirmation=CONFIRMATION_PROBE_REPRODUCED,
    evidence="the probe reproduced the crash",
    fix_location="requests/status_codes.py",
) -> InvestigationResult:
    return InvestigationResult(
        status=STATUS_CONFIRMED,
        failure_mode="TypeError under -OO",
        fix_location=fix_location,
        evidence=evidence,
        confirmation=confirmation,
        confidence=0.95,
    )


CHAIN = [
    {"file": "requests/status_codes.py", "line": 116,
     "symbol": "__doc__", "reason": "usage",
     "terminal_kind": "Optional", "branch_id": 0},
]


def test_downgrade_preserves_finding():
    """The exact acceptance-test shape: confirm claims probe_reproduced,
    but history shows a probe that ran and did NOT reproduce the bug.
    The pipeline downgrades to reasoned_only, then rejects the
    downgraded confirmation because the probe failed to reproduce.
    The finding lands in 'unverified' (Needs Review), NOT 'refused'.
    Refusal would mean 'not a bug'. Unverified means 'could not
    determine'. The distinction matters for the report."""
    result = _confirmed()
    history = [{
        "tool": "probe", "ok": True,
        "metadata": {
            "ran": True, "reproduced": False, "exit_code": 0,
            "reproduction_hint": "probe referenced '__doc__'...",
        },
    }]
    out = _validate_scan_confirmation(result, history, chain=CHAIN)
    assert out.status == STATUS_UNVERIFIED  
    assert out.reason == REFUSE_COULD_NOT_DETERMINE  


def test_downgrade_note_mentions_exit_code():
    history = [{
        "tool": "probe", "ok": True,
        "metadata": {"ran": True, "reproduced": False, "exit_code": 0},
    }]
    note = _append_downgrade_note("original evidence", history)
    assert "original evidence" in note  # preserves audit trail
    assert "exit_code=0" in note
    assert "reasoned_only" in note


def test_downgrade_note_when_no_probe_was_run():
    """The agent claimed probe_reproduced without calling probe."""
    note = _append_downgrade_note("original evidence", [])
    assert "original evidence" in note
    assert "no probe was called" in note
    assert "reasoned_only" in note


def test_downgrade_note_includes_hint():
    history = [{
        "tool": "probe", "ok": True,
        "metadata": {
            "ran": True, "reproduced": False, "exit_code": 0,
            "reproduction_hint": "retry with -OO",
        },
    }]
    note = _append_downgrade_note("original", history)
    assert "retry with -OO" in note


def test_reasoned_only_without_evidence_still_refused():
    """When the agent chose reasoned_only from the start and gave
    no reason, the finding is still refused. The downgrade path is
    a different branch."""
    result = _confirmed(
        confirmation=CONFIRMATION_REASONED_ONLY,
        evidence="",  # no reason stated
    )
    history = []  # no probe
    out = _validate_scan_confirmation(result, history, chain=CHAIN)
    assert out.status == STATUS_UNVERIFIED  # REFUSE_COULD_NOT_DETERMINE


def test_reasoned_only_with_evidence_but_no_probe_rejected():
    """Agent chose reasoned_only, wrote evidence text explaining why
    a probe can't run, but did NOT attempt a probe. The evidence text
    alone is not enough — the escape hatch requires a probe attempt
    in history. Routing: unverified (Needs Review), not refused.
    
    This test replaces the old test_reasoned_only_with_evidence_accepted,
    which asserted the pre-fix behavior where evidence text alone was
    sufficient."""
    result = _confirmed(
        confirmation=CONFIRMATION_REASONED_ONLY,
        evidence="requires -OO interpreter flag; sandbox probe cannot set it",
    )
    out = _validate_scan_confirmation(result, [], chain=CHAIN)
    assert out.status == STATUS_UNVERIFIED  # ← changed from CONFIRMED
    assert out.reason == REFUSE_COULD_NOT_DETERMINE  # ← added


def test_fix_location_outside_chain_rejected():
    """The pre-existing check still fires."""
    result = _confirmed(fix_location="some/other/file.py")
    out = _validate_scan_confirmation(result, [], chain=CHAIN)
    assert out.status == STATUS_REFUSED


def test_probe_reproduced_with_successful_probe_untouched():
    """The happy path — a probe that actually reproduced — is unchanged."""
    result = _confirmed()
    history = [{
        "tool": "probe", "ok": True,
        "metadata": {"ran": True, "reproduced": True, "exit_code": 1},
    }]
    out = _validate_scan_confirmation(result, history, chain=CHAIN)
    assert out.status == STATUS_CONFIRMED
    assert out.confirmation == CONFIRMATION_PROBE_REPRODUCED

def test_reasoned_only_with_probe_attempt_accepted():
    """Agent chose reasoned_only, and history shows a probe attempt
    that failed for an environmental reason (ModuleNotFoundError).
    The escape hatch is legitimately used — accept the finding as
    confirmed."""
    result = _confirmed(
        confirmation=CONFIRMATION_REASONED_ONLY,
        evidence="probe could not run in sandbox: missing urllib3 dependency",
    )
    history = [{
        "tool": "probe", "ok": True,
        "metadata": {
            "ran": True, "reproduced": False, "exit_code": 1,
        },
        "result": "ModuleNotFoundError: No module named 'urllib3'",
    }]
    out = _validate_scan_confirmation(result, history, chain=CHAIN)
    assert out.status == STATUS_CONFIRMED
    assert out.confirmation == CONFIRMATION_REASONED_ONLY
