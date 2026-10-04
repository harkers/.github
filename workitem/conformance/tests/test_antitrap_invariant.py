"""The anti-trap invariant, stated as executable assertions.

External-dependency satisfaction refuses DONE unless every dependency is DONE
(instances.py, problem code dependency-not-satisfied). That rule is only sound if
a record whose dependency was cancelled has somewhere else to go.

It does -- CANCELLED is a terminal sink reachable from every non-terminal state --
but *nothing tests that*. It rests on exactly two things:

  1. policy.yaml has no required_before entry for any exceptional state, and
  2. the state machine still declares the unconditional wildcard edge into
     CANCELLED from every non-terminal state.

Add `required_before: CANCELLED: {...}` to policy.yaml and every cancelled record
fails check_before -- instances.py runs check_before for a record's *current*
state whatever it is -- and then a dependent of a cancelled WorkItem can reach no
terminal state at all. That is the exact trap the spec says cannot happen, and it
would happen with the whole suite green: the dependency reachability tests call
check_ledger, which never invokes check_before.

These tests fail when either precondition is removed.
"""

from __future__ import annotations

from workitem_conformance.contract import load_contract
from workitem_conformance.transitions import TransitionEngine

EXCEPTIONAL_EXIT = "CANCELLED"


def _contract():
    return load_contract()


def test_no_exceptional_state_has_an_entry_gate() -> None:
    """A gate on an exceptional state can make it unreachable, which turns the
    DONE-only satisfaction rule into a trap."""
    c = _contract()
    exceptional = set(c.state_machine["states"]["exceptional"])
    gated = {g["state"] for g in c.policy["gates"]}
    offenders = sorted(gated & exceptional)
    assert not offenders, (
        f"exceptional states with an entry gate: {offenders}. A record cancelled "
        "with unmet dependencies would have nowhere left to go."
    )


def test_required_before_names_no_exceptional_state() -> None:
    """check_before runs for a record's current state whatever it is, so a
    required_before entry on an exceptional state bites the same way."""
    c = _contract()
    exceptional = set(c.state_machine["states"]["exceptional"])
    offenders = sorted(set(c.policy["required_before"]) & exceptional)
    assert not offenders, f"required_before gates an exceptional state: {offenders}"


def test_every_non_terminal_state_can_reach_cancelled_in_one_step() -> None:
    """The unconditional exit. If this needs a condition, the condition is a
    dependency-shaped hole waiting to be found."""
    c = _contract()
    engine = TransitionEngine(c.state_machine)
    terminal = engine.terminal_states()
    non_terminal = set(engine.states()) - set(terminal)
    assert EXCEPTIONAL_EXIT in terminal, f"{EXCEPTIONAL_EXIT} is no longer terminal"

    blocked = []
    for state in sorted(non_terminal):
        verdict = engine.check(state, EXCEPTIONAL_EXIT, _context_for(engine, state))
        if not verdict.legal:
            blocked.append((state, str(verdict)))
    assert not blocked, f"non-terminal states that cannot reach {EXCEPTIONAL_EXIT}: {blocked}"


def _context_for(engine: TransitionEngine, state: str):
    from workitem_conformance.transitions import default_context

    return default_context()


def test_the_satisfaction_rule_is_still_enforced_where_the_note_says() -> None:
    """policy.yaml's DONE note points at dependency-not-satisfied as prose. Nothing
    executable pinned that pointer; this does. If the whole-ledger block is
    deleted, the policy file would lie and this fails."""
    c = _contract()
    done_note = next(g["note"] for g in c.policy["gates"] if g["state"] == "DONE")
    assert "dependency-not-satisfied" in done_note, (
        "the DONE gate no longer names the rule that gates it"
    )
    assert "check_ledger" in done_note or "conformance checker" in done_note

    source = (
        _contract().root / "workitem" / "conformance" / "workitem_conformance" / "instances.py"
    ).read_text()
    assert '"dependency-not-satisfied"' in source, (
        "the DONE gate note names a rule the checker no longer emits"
    )
