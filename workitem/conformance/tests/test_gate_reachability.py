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
