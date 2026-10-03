"""Legality is derived from the declared edge set, never restated here."""

from __future__ import annotations

import itertools
from dataclasses import replace
from pathlib import Path

import yaml

from workitem_conformance.contract import load_contract
from workitem_conformance.transitions import (
    TransitionEngine,
    WorkItemContext,
    default_context,
)


def _machine() -> dict:
    return load_contract().state_machine


def _engine() -> TransitionEngine:
    return TransitionEngine(_machine())


def _ctx(**overrides: object) -> WorkItemContext:
    return replace(default_context(), **overrides)


def test_every_state_is_reachable_from_the_first_happy_state() -> None:
    machine = _machine()
    engine = _engine()
    start = machine["states"]["happy_path"][0]
    reachable = {start}
    frontier = [start]
    while frontier:
        for nxt in engine.outgoing(frontier.pop()):
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)
    assert reachable == engine.states()


def test_terminal_states_are_sinks() -> None:
    """Structural: nothing may leave a state the contract calls terminal."""
    engine = _engine()
    for state in engine.terminal_states():
        assert list(engine.outgoing(state)) == [], state


def test_engine_never_permits_an_undeclared_edge() -> None:
    engine = _engine()
    ctx = _ctx()
    for frm, to in itertools.product(sorted(engine.states()), repeat=2):
        if engine.declared(frm, to):
            continue
        assert not engine.check(frm, to, ctx).legal, f"{frm}->{to} permitted but undeclared"


def test_every_unconditional_declared_edge_is_permitted() -> None:
    engine = _engine()
    ctx = _ctx()
    skipped = set(engine.skipped_by_delivery_mode(ctx.delivery_mode))
    for frm, to in engine.edges():
        if engine.edge_spec(frm, to).get("when"):
            continue
        if to in skipped:
            continue
        assert engine.check(frm, to, ctx).legal, f"{frm}->{to} declared but refused"


def test_wildcard_edges_expand_to_every_non_terminal_source() -> None:
    engine = _engine()
    for target in engine.wildcard_targets():
        for frm in sorted(engine.states() - engine.terminal_states()):
            assert engine.declared(frm, target), f"{frm}->{target} should be declared"


def test_delivery_mode_none_makes_delivery_states_unreachable() -> None:
    engine = _engine()
    ctx = _ctx(delivery_mode="none")
    unreachable = set(engine.skipped_by_delivery_mode("none"))
    assert unreachable, "delivery.mode=none must skip at least one state"
    for frm, to in engine.edges():
        if to in unreachable:
            assert not engine.check(frm, to, ctx).legal, (
                f"{frm}->{to} legal under delivery.mode=none"
            )


def test_delivery_mode_none_admits_the_short_circuit_edge() -> None:
    engine = _engine()
    short_circuit = [
        (frm, to)
        for frm, to in engine.edges()
        if engine.edge_spec(frm, to).get("when", {}).get("delivery_mode") == "none"
    ]
    assert short_circuit, "state-machine.yaml must declare a delivery.mode=none short circuit"
    for frm, to in short_circuit:
        assert not engine.check(frm, to, _ctx()).legal
        assert engine.check(frm, to, _ctx(delivery_mode="none")).legal


def test_repair_state_has_exactly_one_exit_into_the_execution_path() -> None:
    """The contract's own repair topology, read from state-machine.yaml.

    The repair state also has the wildcard BLOCKED and CANCELLED exits, which
    every non-terminal state has. What must be unique is the edge back into the
    execution path, or repair rounds could re-enter execution without recording.
    """
    engine = _engine()
    repair = _machine()["repair"]
    repair_state = repair["state"]
    resume_state = repair["resume_state"]

    assert repair_state in engine.states()
    assert resume_state in engine.states()
    wildcard = set(engine.wildcard_targets())
    specific_exits = set(engine.outgoing(repair_state)) - wildcard
    assert specific_exits == {resume_state}, f"{repair_state} exits: {specific_exits}"


def test_only_declared_states_may_enter_execution() -> None:
    """Repair rounds must be recorded, so the entry points into execution are closed."""
    engine = _engine()
    repair = _machine()["repair"]
    resume_state = repair["resume_state"]
    predecessors = {frm for frm in engine.states() if engine.declared(frm, resume_state)}
    assert predecessors == set(repair["execution_entry_states"]), (
        f"states entering {resume_state}: {sorted(predecessors)}, "
        f"contract declares {sorted(repair['execution_entry_states'])}"
    )


def test_repair_entry_states_are_the_declared_ones() -> None:
    engine = _engine()
    repair = _machine()["repair"]
    for entry in repair["entry_states"]:
        assert engine.declared(entry, repair["state"]), entry


def test_failure_is_reachable_only_from_states_where_execution_has_begun() -> None:
    engine = _engine()
    failure = _machine()["failure"]
    happy = _machine()["states"]["happy_path"]

    for entry in failure["entry_states"]:
        assert engine.declared(entry, failure["state"]), entry
    assert engine.declared(failure["state"], failure["resume_state"])

    # A task that fails specification or planning has not failed, it has not begun.
    before_execution = set(happy[: happy.index(failure["entry_states"][0])])
    for state in sorted(before_execution):
        assert not engine.declared(state, failure["state"]), (
            f"{state} precedes execution and must not be able to fail"
        )


def test_an_unknown_state_is_refused() -> None:
    """The legal state set lives in state-machine.yaml, so the engine is the gate."""
    engine = _engine()
    fixture = Path(__file__).parent / "fixtures" / "invalid-unknown-state.yaml"
    bad = yaml.safe_load(fixture.read_text())
    assert bad["state"] not in engine.states()
    assert not engine.check(bad["state"], "READY", _ctx()).legal
    assert not engine.check("DRAFT", bad["state"], _ctx()).legal


def test_the_machine_declares_everything_the_tests_rely_on() -> None:
    """Guards against a contract edit silently weakening these assertions."""
    machine = _machine()
    assert machine["states"]["happy_path"], "no happy path declared"
    assert machine["states"]["exceptional"], "no exceptional states declared"
    assert machine["terminal"], "no terminal states declared"
    assert machine["repair"]["state"] not in machine["states"]["happy_path"], (
        "the repair state must be exceptional, not a happy-path stage"
    )
    assert machine["parameters"]["delivery_mode"]["values"]
