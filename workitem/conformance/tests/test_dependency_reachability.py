"""Ledger-shaped reachability invariants.

#8's I2 enumerated the (delivery_mode, review_policy) cross product, which are
contract *parameters*. Dependencies are not a parameter -- they are per-record
ledger data -- so these invariants enumerate ledger *shapes* instead.

The load-bearing property is I2': on an acyclic ledger, every record can always
reach a terminal state, because CANCELLED is reachable unconditionally. Without
that, refusing DONE on an unmet dependency would be a trap rather than a rule.
"""

from pathlib import Path

import pytest

from workitem_conformance.instances import build_dep_map, check_ledger, find_cycles

TERMINAL = {"DONE", "CANCELLED"}


def rec(wid, state, deps=None, ext=None):
    return {
        "id": wid,
        "state": state,
        "dependencies": [{"target": t, "type": "REQUIRES"} for t in (deps or [])],
        "external_dependencies": ext or [],
    }


def external(discharge):
    return [
        {
            "repo": "harkers/workhub",
            "number": 1,
            "type": "REQUIRES",
            "resolved_by": discharge,
            "note": "x",
        }
    ]


def pairs(records):
    return [(Path(f"{r['id']}/workitem.yaml"), r) for r in records]


def rules(records):
    return {p.rule for p in check_ledger(pairs(records))}


def settle(shape):
    """Set every record to DONE if its dependencies are DONE. Repeat until fixpoint.

    This is the constructive half of I5: DONE must become legal exactly when the
    dependencies are DONE, and a fixpoint is how a DAG bottoms out.
    """
    state = {wid: "DRAFT" for wid, _ in shape}
    progress = True
    while progress:
        progress = False
        for wid, deps in shape:
            if state[wid] == "DONE":
                continue
            if all(state[d] == "DONE" for d in deps):
                state[wid] = "DONE"
                progress = True
    return state


SHAPES = {
    "chain": [
        ("WI-20261004-0001", ["WI-20261004-0002"]),
        ("WI-20261004-0002", []),
    ],
    "diamond": [
        ("WI-20261004-0001", ["WI-20261004-0002", "WI-20261004-0003"]),
        ("WI-20261004-0002", ["WI-20261004-0004"]),
        ("WI-20261004-0003", ["WI-20261004-0004"]),
        ("WI-20261004-0004", []),
    ],
    # Mirrors harkers/workhub's WI-20261004-0001 shape, which requires 11 others.
    # One unsatisfied leaf here holds most of a real ledger.
    "wide_fan_in": [
        ("WI-20261004-0001", [f"WI-20261004-{i:04d}" for i in range(2, 13)]),
        *[("WI-20261004-0002", [])],
        *[("WI-20261004-0003", [])],
        *[("WI-20261004-0004", [])],
        *[("WI-20261004-0005", [])],
        *[("WI-20261004-0006", [])],
        *[("WI-20261004-0007", [])],
        *[("WI-20261004-0008", [])],
        *[("WI-20261004-0009", [])],
        *[("WI-20261004-0010", [])],
        *[("WI-20261004-0011", [])],
        *[("WI-20261004-0012", [])],
    ],
    "two_independent_chains": [
        ("WI-20261004-0001", ["WI-20261004-0002"]),
        ("WI-20261004-0002", []),
        ("WI-20261004-0003", ["WI-20261004-0004"]),
        ("WI-20261004-0004", []),
    ],
    "single": [("WI-20261004-0001", [])],
}


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_i4_every_shape_is_acyclic_by_construction(name):
    shape = SHAPES[name]
    assert find_cycles({wid: list(deps) for wid, deps in shape}) == []


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_i5_done_is_reachable_iff_every_dependency_is_done(name):
    shape = SHAPES[name]
    state = settle(shape)
    records = [rec(wid, state[wid], deps) for wid, deps in shape]
    assert "dependency-not-satisfied" not in rules(records)
    assert all(s == "DONE" for s in state.values()), state


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_i2p_cancel_is_always_reachable_whatever_the_dependencies(name):
    """The anti-trap property. Every record can always be cancelled, so refusing
    DONE on an unmet dependency never leaves a record with nowhere to go."""
    shape = SHAPES[name]
    state = settle(shape)
    # Leave exactly one leaf unfinished so the dependent cannot reach DONE.
    leaf = shape[-1][0]
    cancelled = [rec(wid, "CANCELLED" if wid != leaf else state[wid], deps) for wid, deps in shape]
    assert "dependency-not-satisfied" not in rules(cancelled)


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_i5_one_unfinished_leaf_blocks_exactly_its_dependents(name):
    shape = SHAPES[name]
    state = settle(shape)
    leaf = shape[-1][0]

    dependents = {wid for wid, deps in shape if leaf in deps}
    if not dependents:
        pytest.skip(f"{name}: nothing depends on the last record")

    # Settle everything, then leave exactly the leaf unfinished.
    stuck_state = dict(state, **{leaf: "DRAFT"})
    stuck = [rec(wid, stuck_state[wid], deps) for wid, deps in shape]

    problems = check_ledger(pairs(stuck))
    found = [p for p in problems if p.rule == "dependency-not-satisfied"]
    assert found, f"{name}: an unfinished leaf blocked nothing"
    assert all(leaf in p.detail for p in found)

    # The block is confined to the records that actually wait on the leaf, and
    # downstream records are not flagged merely for being downstream.
    blocked = {p.path for p in found}
    assert blocked == {str(Path(f"{wid}/workitem.yaml")) for wid in dependents}


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_cancelling_a_leaf_never_releases_its_dependents(name):
    shape = SHAPES[name]
    leaf = shape[-1][0]
    records = [rec(wid, "CANCELLED" if wid == leaf else "DONE", deps) for wid, deps in shape]
    dependents = [wid for wid, deps in shape if leaf in deps]
    if not dependents:
        pytest.skip(f"{name}: nothing depends on the cancelled record")
    assert "dependency-not-satisfied" in rules(records)


def test_a_cycle_is_reported_rather_than_silently_satisfied():
    records = [
        rec("WI-20261004-0001", "DONE", ["WI-20261004-0002"]),
        rec("WI-20261004-0002", "DONE", ["WI-20261004-0001"]),
    ]
    assert "dependency-cycle" in rules(records)


def test_external_discharge_chain_terminates_in_done():
    records = [
        rec("WI-20261004-0001", "DONE", ext=external("WI-20261004-0002")),
        rec("WI-20261004-0002", "DONE", ext=external("WI-20261004-0003")),
        rec("WI-20261004-0003", "DONE"),
    ]
    assert "dependency-not-satisfied" not in rules(records)


def test_unterminated_external_chain_blocks_done():
    records = [
        rec("WI-20261004-0001", "DONE", ext=external("WI-20261004-0002")),
        rec("WI-20261004-0002", "DONE", ext=external("WI-20261004-0003")),
        rec("WI-20261004-0003", "DRAFT"),
    ]
    assert "dependency-not-satisfied" in rules(records)


def test_a_cycle_can_pass_through_an_external_discharge():
    """A waits on external B; B's discharge is A. A graph built from dependencies[]
    alone is empty here and would miss the cycle entirely."""
    records = [
        rec("WI-20261004-0001", "DRAFT", ext=external("WI-20261004-0002")),
        rec("WI-20261004-0002", "DRAFT", ["WI-20261004-0001"]),
    ]
    assert find_cycles(build_dep_map(pairs(records))) != []
    assert "dependency-cycle" in rules(records)


def test_the_same_shape_without_the_back_edge_is_not_a_cycle():
    records = [
        rec("WI-20261004-0001", "DONE", ext=external("WI-20261004-0002")),
        rec("WI-20261004-0002", "DONE"),
    ]
    assert find_cycles(build_dep_map(pairs(records))) == []
    assert "dependency-cycle" not in rules(records)


def test_a_deep_chain_is_not_a_cycle():
    shape = [(f"WI-20261004-{i:04d}", [f"WI-20261004-{i + 1:04d}"]) for i in range(1, 400)]
    shape.append(("WI-20261004-0400", []))
    assert find_cycles({wid: list(deps) for wid, deps in shape}) == []
