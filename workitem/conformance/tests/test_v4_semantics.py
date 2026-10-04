"""The two behaviours workitem/v4 adds, tested before they exist.

Both close a live defect found by cloud review of the merged contract work:

  #31  DONE honoured the record's own ``verification.required``, so a record could
       opt out of its own policy by narrowing the list it declares.
  #40  The state machine had no backward transition, so a record filed into the
       wrong state could not be corrected honestly -- every exit asserted something
       false.

Each test names a failure that was measured on harkers/.github#7e16961, so a
regression is a return to a state that was observed rather than imagined.
"""

from __future__ import annotations

import copy

import pytest

from workitem_conformance.contract import load_contract
from workitem_conformance.gates import check_before, check_review_transition
from workitem_conformance.transitions import TransitionEngine, WorkItemContext

BASE = {
    "id": "WI-20261004-9999",
    "schema_version": "3.0",
    "type": "TASK",
    "state": "DONE",
    "acceptance_criteria": [
        {
            "id": "AC-001",
            "description": "d",
            "status": "met",
            "verification_method": "command",
            "expected": "e",
        }
    ],
    "sizing": {"estimated_complexity": "SMALL"},
    "scope": {"allowed_paths": ["src/**"], "denied_paths": [".git/**"]},
    "privacy": {"level": "INTERNAL", "network": "denied"},
    "delivery": {"mode": "pull_request", "branch": "b", "pull_request": 1},
    "artifacts": {"completion_packet": "evidence/p.md"},
    "completion": {"status": "complete", "packet": "evidence/p.md"},
    "verification": {},
}


def _ctx(**kw):
    base = {
        "delivery_mode": "pull_request",
        "review_policy": "normal",
        "verification": {},
        "has_completion_packet": True,
        "past_specification": True,
        "any_criterion_met": True,
    }
    base.update(kw)
    return WorkItemContext(**base)


# --- #40: a backward transition that is honest about what it permits ----------


def test_workitem_context_requires_any_criterion_met():
    """No default. A defaulted field would be silently False in the consumer --
    the guard would always pass and read as enforced, which is #36's failure mode."""
    with pytest.raises(TypeError):
        WorkItemContext(
            delivery_mode="pull_request",
            review_policy="normal",
            verification={},
            has_completion_packet=True,
            past_specification=True,
        )


def test_reviewing_may_return_to_ready_when_nothing_was_built():
    engine = TransitionEngine(load_contract().state_machine)
    verdict = engine.check("REVIEWING", "READY", _ctx(any_criterion_met=False))
    assert verdict.legal, verdict.reason


def test_reviewing_may_not_return_to_ready_once_something_is_met():
    """The guard is the whole point: you may go back only if you never claimed
    anything was done."""
    engine = TransitionEngine(load_contract().state_machine)
    verdict = engine.check("REVIEWING", "READY", _ctx(any_criterion_met=True))
    assert not verdict.legal
    assert "no_criterion_met" in verdict.reason


def test_the_backward_edge_is_declared_and_guarded():
    machine = load_contract().state_machine
    specs = [e for e in machine["transitions"] if e["from"] == "REVIEWING" and e["to"] == "READY"]
    assert specs, "REVIEWING -> READY is not declared"
    assert specs[0].get("when") == {"no_criterion_met": True}, (
        "the edge must be guarded, or it permits discarding real progress"
    )


def test_ready_is_still_reachable_under_every_delivery_mode():
    """The backward edge must not become a hole in the forward ladder."""
    for mode in ("pull_request", "branch_only", "none"):
        engine = TransitionEngine(load_contract().state_machine)
        assert engine.check("READY", "IN_PROGRESS", _ctx(delivery_mode=mode)).legal


# --- #31: DONE requires the union, not the record's declaration -------------


def _verification(**kw):
    base = {
        "review_policy": "normal",
        "required": ["tests"],
        "tests": {"status": "passed", "evidence": []},
        "local_review": {"status": "not_applicable", "evidence": []},
        "cloud_review": {"status": "not_applicable", "evidence": []},
    }
    base.update(kw)
    return base


def test_done_is_refused_when_the_policy_floor_is_unmet():
    """WI-20261003-0007's exact shape: policy demands local+cloud, the record
    declares only tests, and DONE passed anyway on 7e16961."""
    contract = load_contract()
    record = copy.deepcopy(BASE)
    record["verification"] = _verification()
    result = check_before(record, contract.policy, "DONE")
    assert not result.ok
    assert any("local_review" in f for f in result.failures), result.failures


def test_done_is_refused_when_the_floor_evidence_failed():
    """Not vacuous: nothing is empty, the author simply declared one element."""
    contract = load_contract()
    record = copy.deepcopy(BASE)
    record["verification"] = _verification(
        review_policy="high_risk",
        required=["tests"],
        local_review={"status": "failed", "evidence": []},
        cloud_review={"status": "failed", "evidence": []},
        specialist_review={"status": "pending", "evidence": []},
    )
    result = check_before(record, contract.policy, "DONE")
    assert not result.ok


def test_done_is_granted_when_the_union_is_satisfied():
    contract = load_contract()
    record = copy.deepcopy(BASE)
    record["verification"] = _verification(
        required=["tests", "local_review", "cloud_review"],
        local_review={"status": "passed", "evidence": []},
        cloud_review={"status": "passed", "evidence": []},
    )
    assert check_before(record, contract.policy, "DONE").ok


def test_the_record_may_demand_more_than_the_policy():
    """Union, not replacement. A record that requires extra evidence must not be
    able to reach DONE until that extra evidence passes."""
    contract = load_contract()
    record = copy.deepcopy(BASE)
    record["verification"] = _verification(
        required=["tests", "local_review", "cloud_review", "specialist_review"],
        local_review={"status": "passed", "evidence": []},
        cloud_review={"status": "passed", "evidence": []},
        specialist_review={"status": "pending", "evidence": []},
    )
    assert not check_before(record, contract.policy, "DONE").ok


def test_reviewing_and_done_read_the_same_floor():
    """#31's root cause was two sources of truth: REVIEWING honoured the policy,
    DONE honoured the record. Both must read the policy now."""
    contract = load_contract()
    record = copy.deepcopy(BASE)
    record["verification"] = _verification()
    assert not check_review_transition(record, contract.policy).ok
    assert not check_before(record, contract.policy, "DONE").ok
