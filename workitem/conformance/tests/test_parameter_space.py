"""Invariants over the declared parameter space.

Every combination here is read from the contract's own declared `values`. A test
that hardcoded them would be a fourth description of the contract, and a fourth
delivery mode would need a code change to be covered.
"""

from __future__ import annotations

from dataclasses import replace

from workitem_conformance.contract import (
    combinations,
    load_contract,
    parameter_modes,
    parameter_policies,
)
from workitem_conformance.transitions import TransitionEngine, default_context


def _reachable(contract, mode: str, policy: str) -> set[str]:
    engine = TransitionEngine(contract.state_machine)
    ctx = replace(default_context(), delivery_mode=mode, review_policy=policy)
    seen, frontier = {"DRAFT"}, ["DRAFT"]
    while frontier:
        current = frontier.pop()
        for nxt in engine.outgoing(current):
            if engine.check(current, nxt, ctx).legal and nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    return seen


def test_parameter_spaces_are_enumerable_from_the_contract() -> None:
    """Guards every test in this module against becoming a literal."""
    contract = load_contract()
    modes = parameter_modes(contract)
    policies = parameter_policies(contract)
    assert len(modes) == len(set(modes)) and modes
    assert len(policies) == len(set(policies)) and policies
    assert combinations(contract) == [(m, p) for m in modes for p in policies]


def test_every_state_is_reachable_under_every_applicable_combination() -> None:
    """I1: every non-skipped state is reachable from DRAFT."""
    contract = load_contract()
    engine = TransitionEngine(contract.state_machine)
    all_states = engine.states()
    for mode, policy in combinations(contract):
        skipped = set(engine.skipped_by_delivery_mode(mode))
        seen = _reachable(contract, mode, policy)
        missing = sorted(all_states - skipped - seen)
        assert not missing, f"{mode}/{policy} cannot reach {missing}"


def test_every_combination_can_reach_done() -> None:
    """I2: the work must be finishable. CANCELLED is abandonment, not completion."""
    contract = load_contract()
    for mode, policy in combinations(contract):
        assert "DONE" in _reachable(contract, mode, policy), f"{mode}/{policy}"


def test_skip_lists_match_the_declared_modes() -> None:
    contract = load_contract()
    by_mode = contract.state_machine["parameters"]["delivery_mode"]["skips_states_by_mode"]
    for mode in parameter_modes(contract):
        assert mode in by_mode, f"{mode} has no skips_states_by_mode entry"
    engine = TransitionEngine(contract.state_machine)
    states = engine.states()
    for mode, skipped in by_mode.items():
        unknown = sorted(set(skipped) - states)
        assert not unknown, f"{mode} skips unknown states {unknown}"


def test_review_policy_declares_that_it_affects_gates_not_edges() -> None:
    """Guards the asymmetry the cross-product test relies on."""
    contract = load_contract()
    declared = contract.policy["parameters"]["review_policy"]
    assert declared["affects"] == "gates"
    assert declared["values"] == parameter_policies(contract)
    # If a review policy ever gained an edge condition, this would need revisiting.
    assert "review_policy" not in str(contract.state_machine["transitions"])
