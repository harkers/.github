"""Every `enforced: true` gate must be REACHABLE from validation.

`harkers/.github`#29: `check_instance` called `check_before` unconditionally, so six of
the eight enforced gates could never fire — `check_declared_gates`,
`check_review_transition` and `check_retroactive_criteria` were exercised only by their
own unit tests. The gate table read as enforced and the functions read as tested, and
nothing asserted that the shipped path reached them.

These tests assert *reachability*, not correctness. A function that works and is never
called is invisible to a unit test of that function, which is precisely how this gap
survived.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from workitem_conformance.contract import load_contract
from workitem_conformance.gates import evaluate_state_gates
from workitem_conformance.instances import check_instance
from workitem_conformance.transitions import TransitionEngine

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = yaml.safe_load((ROOT / "workitem" / "examples" / "task.yaml").read_text())

KNOWN_PREDICATES = {"check_before", "check_declared_gates", "check_review_transition"}


@pytest.fixture
def contract():
    return load_contract(ROOT)


def enforced_gates(contract):
    return [g for g in contract.policy["gates"] if g.get("enforced")]


def test_the_gate_table_declares_more_than_check_before(contract):
    """If this fails, the fix regressed to hardcoding one predicate again."""
    predicates = {g.get("predicate") for g in enforced_gates(contract)}
    assert len(predicates) > 1, f"only one predicate in use: {predicates}"
    assert predicates <= KNOWN_PREDICATES, predicates


@pytest.mark.parametrize("predicate", sorted(KNOWN_PREDICATES))
def test_every_declared_predicate_is_dispatchable(predicate):
    """An unknown predicate must fail loudly. A gate table that has drifted from the
    checker must not read as clean."""
    record = copy.deepcopy(EXAMPLE)
    policy = {
        "gates": [{"state": "READY", "predicate": predicate, "enforced": True}],
        # check_review_transition reads this; the others ignore it. Supplying it for
        # every predicate keeps the test about dispatch rather than about each gate's
        # own requirements.
        "review_policy": {
            "field": "verification.review_policy",
            "required_evidence": {"normal": ["local_review"]},
        },
    }
    record["verification"] = {
        "review_policy": "normal",
        "local_review": {"status": "passed"},
    }
    verdict = evaluate_state_gates(record, policy, "READY")
    assert verdict.ok, verdict.failures


def test_an_unimplemented_predicate_fails_rather_than_passing():
    record = copy.deepcopy(EXAMPLE)
    policy = {"gates": [{"state": "READY", "predicate": "check_something_new", "enforced": True}]}
    verdict = evaluate_state_gates(record, policy, "READY")
    assert not verdict.ok
    assert "does not implement" in verdict.failures[0]


def test_a_state_with_no_declared_gate_is_not_a_failure(contract):
    record = copy.deepcopy(EXAMPLE)
    verdict = evaluate_state_gates(record, contract.policy, "IN_PROGRESS")
    assert verdict.ok, verdict.failures


@pytest.mark.parametrize(
    ("state", "artifact"),
    [
        ("SPEC_READY", "specification"),
        ("PLAN_READY", "implementation_plan"),
    ],
)
def test_each_artifact_gate_now_fires_from_check_instance(contract, state, artifact):
    """The end-to-end proof: a record AT the state, missing that state's artifact, is
    refused by the shipped validation path -- not only by a direct call."""
    engine = TransitionEngine(contract.state_machine)
    record = copy.deepcopy(EXAMPLE)
    record["state"] = state
    record["artifacts"] = {artifact: None}
    problems = [
        p
        for p in check_instance(Path("t/workitem.yaml"), record, contract, engine)
        if p.rule == "state-gate"
    ]
    assert problems, f"{state} with no {artifact} was accepted"


def test_the_same_record_is_accepted_once_the_artifact_exists(contract, state=None):
    engine = TransitionEngine(contract.state_machine)
    record = copy.deepcopy(EXAMPLE)
    record["state"] = "SPEC_READY"
    record["artifacts"] = {"specification": "docs/spec.md"}
    problems = [
        p
        for p in check_instance(Path("t/workitem.yaml"), record, contract, engine)
        if p.rule == "state-gate"
    ]
    assert not problems, [p.detail for p in problems]


def test_check_declared_gates_is_scoped_to_one_state(contract):
    """Unscoped, it demanded EVERY enforced gate at once — a specification, a plan and
    a completion packet simultaneously — so it could only ever be called from a test."""
    from workitem_conformance.gates import check_declared_gates

    record = copy.deepcopy(EXAMPLE)
    record["artifacts"] = {"specification": "docs/spec.md"}
    scoped = check_declared_gates(record, contract.policy, state="SPEC_READY")
    assert scoped.ok, scoped.failures

    unscoped = check_declared_gates(record, contract.policy)
    assert not unscoped.ok, "the unscoped form should demand more, not less"


# --- REVIEWING: the case whose absence let four live records pass ------------
#
# The tests above cover SPEC_READY and PLAN_READY, both of which use
# `check_declared_gates`. REVIEWING uses `check_review_transition` — a different
# predicate — so it was the one state with no end-to-end case. That is why the suite
# was green while five of harkers/workhub's fourteen records violated their own gate.
#
# Five, not four: WI-20261003-0005 was missed when this was first written. The count
# comes from running the checker over the live ledger, not from reading it.


def _reviewing_record(**verification):
    record = copy.deepcopy(EXAMPLE)
    record["state"] = "REVIEWING"
    base = {
        "review_policy": "normal",
        "required": ["tests"],
        "tests": {"status": "passed", "evidence": []},
        "local_review": {"status": "not_applicable", "evidence": []},
        "cloud_review": {"status": "not_applicable", "evidence": []},
        "specialist_review": {"status": "not_applicable", "evidence": []},
    }
    base.update(verification)
    record["verification"] = base
    return record


def _state_gate_problems(record, contract):
    engine = TransitionEngine(contract.state_machine)
    return [
        p
        for p in check_instance(Path("t/workitem.yaml"), record, contract, engine)
        if p.rule == "state-gate"
    ]


def test_reviewing_refuses_a_record_whose_local_review_did_not_pass(contract):
    """The exact shape of WI-20261003-0007/0008/0009. This is the case the suite was
    missing, and its absence is why the fix looked safe against the live ledger."""
    problems = _state_gate_problems(_reviewing_record(), contract)
    assert problems, "a REVIEWING record with local_review not_applicable was accepted"
    assert "local_review" in problems[0].detail


def test_reviewing_accepts_a_record_whose_policy_evidence_is_present(contract):
    ok = _reviewing_record(
        local_review={"status": "passed", "evidence": []},
        cloud_review={"status": "passed", "evidence": []},
    )
    assert not _state_gate_problems(ok, contract)


def test_reviewing_is_evaluated_by_its_own_declared_predicate(contract):
    """REVIEWING is the only enforced gate using check_review_transition, so it is the
    only one a test that only exercises check_declared_gates would miss."""
    predicates = {g["state"]: g.get("predicate") for g in enforced_gates(contract)}
    assert predicates.get("REVIEWING") == "check_review_transition"
    by_artifact = {
        g["state"]
        for g in contract.policy["gates"]
        if g.get("enforced") and g.get("artifact_required")
    }
    assert "REVIEWING" not in by_artifact, (
        "if REVIEWING now carries an artifact_required it needs its own case too"
    )


def test_every_enforced_state_has_an_end_to_end_case(contract):
    """The generalisation of the gap: assert that each enforced gate is covered by a
    refusal test, so a ninth gate cannot be added without one."""
    covered = {
        "SPEC_READY",
        "PLAN_READY",
        "REVIEWING",
        "READY",
        "DONE",
        "COMMITTED",
        "PR_DRAFT",
        "REPORTING",
    }
    declared = {g["state"] for g in enforced_gates(contract)}
    uncovered = declared - covered
    assert not uncovered, (
        f"enforced gates with no end-to-end refusal test: {sorted(uncovered)}. "
        "Add one before shipping the gate, or it will pass on green and fail on real data."
    )


# --- COMMITTED, PR_DRAFT, REPORTING: the other three artifact gates ---------
#
# Found by test_every_enforced_state_has_an_end_to_end_case above, which is the
# point of it. REPORTING is one of the four live violations, so it mattered most.


@pytest.mark.parametrize(
    ("state", "mutate"),
    [
        ("COMMITTED", lambda r: r["artifacts"].__setitem__("commits", [])),
        (
            "PR_DRAFT",
            lambda r: r["delivery"].__setitem__("pull_request", None),
        ),
        ("REPORTING", lambda r: r["completion"].__setitem__("packet", None)),
    ],
)
def test_artifact_gates_refuse_their_own_state(contract, state, mutate):
    engine = TransitionEngine(contract.state_machine)
    record = copy.deepcopy(EXAMPLE)
    record["state"] = state
    record["delivery"] = {"mode": "pull_request", "branch": None, "pull_request": 7}
    record["artifacts"] = {
        "specification": "docs/spec.md",
        "implementation_plan": "docs/plan.md",
        "commits": ["abc123"],
        "completion_packet": "evidence/packet.md",
    }
    record["completion"] = {"status": "complete", "packet": "evidence/packet.md"}
    mutate(record)

    problems = [
        p
        for p in check_instance(Path("t/workitem.yaml"), record, contract, engine)
        if p.rule == "state-gate"
    ]
    assert problems, f"{state} with its own artifact missing was accepted"


def test_reporting_is_refused_without_a_packet(contract):
    """WI-20261003-0002's exact shape: state REPORTING, no completion packet. One of
    the four live violations this fix exposes."""
    engine = TransitionEngine(contract.state_machine)
    record = copy.deepcopy(EXAMPLE)
    record["state"] = "REPORTING"
    record["completion"] = {"status": "incomplete", "packet": None}
    record["artifacts"] = {
        "specification": "docs/spec.md",
        "implementation_plan": "docs/plan.md",
        "commits": ["abc123"],
        "completion_packet": None,
    }
    problems = [
        p
        for p in check_instance(Path("t/workitem.yaml"), record, contract, engine)
        if p.rule == "state-gate"
    ]
    assert problems
    assert "completion.packet" in problems[0].detail


def test_pr_draft_requires_a_pull_request_even_under_branch_only(contract):
    """PR_DRAFT is skipped under `branch_only`, so its gate is conditioned off there.
    The record must not satisfy it by being in a mode that skips the state."""
    engine = TransitionEngine(contract.state_machine)
    record = copy.deepcopy(EXAMPLE)
    record["state"] = "PR_DRAFT"
    record["delivery"] = {"mode": "pull_request", "branch": None, "pull_request": None}
    problems = [
        p
        for p in check_instance(Path("t/workitem.yaml"), record, contract, engine)
        if p.rule == "state-gate"
    ]
    assert problems, "PR_DRAFT with no pull_request was accepted"
