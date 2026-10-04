"""Cross-record validation: the invariants no single-record schema can express.

``v1.schema.json`` can only see one record at a time. Everything that requires
knowing about other records -- or about the contract's *data* files rather than
its field shapes -- lives here.

The reusable CI gate calls :mod:`workitem_conformance.cli`, which calls this. It
exists because a schema-valid ledger is not a correct ledger: a WorkItem bumped
to ``DONE`` with nothing verified, or a dependency pointing at a record that does
not exist, both validate cleanly and both are wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from workitem_conformance.contract import Contract
from workitem_conformance.gates import check_before, check_sizing, evaluate_state_gates
from workitem_conformance.transitions import TransitionEngine

ID_PATTERN = re.compile(r"^WI-\d{8}-\d{4}$")
# A dependency may not name anything outside the ledger today. See harkers/.github#4.
EXTERNAL_REF = re.compile(r"^(?!\d)(?!WI-).+")


def find_cycles(dep_map: dict[str, list[str]]) -> list[list[str]]:
    """Return one representative cycle per DFS back edge, each as a node list.

    This is *not* an exhaustive enumeration. A graph can hold more cycles than this
    returns: in {a: [b, c], b: [c], c: [a]} both a->b->c->a and a->c->a are cycles,
    and only the first is reported, because the a->c->a closing edge is examined
    after c has already been marked done.

    Exhaustive enumeration is unnecessary here. An acyclic graph has no back edge,
    so `find_cycles(...) == []` is a sound acyclicity verdict in both directions --
    which is the only question the ledger check asks. The per-cycle count should
    not be read as a count of cycles.

    Iterative rather than recursive: a 5000-deep chain is realistic once a ledger
    grows, and recursion would exhaust the stack on a graph that is merely deep.

    Edges to nodes outside dep_map are ignored here. A dangling target is a
    separate problem code (unresolved-dependency), and treating it as a cycle
    would report one defect twice under two codes.
    """
    UNVISITED, ON_PATH, DONE = 0, 1, 2
    marks: dict[str, int] = dict.fromkeys(dep_map, UNVISITED)
    cycles: list[list[str]] = []
    seen_signatures: set[frozenset[str]] = set()

    for root in dep_map:
        if marks[root] != UNVISITED:
            continue
        marks[root] = ON_PATH
        path: list[str] = [root]
        on_path_index: dict[str, int] = {root: 0}
        stack: list[tuple[str, Any]] = [(root, iter(dep_map[root]))]

        while stack:
            node, children = stack[-1]
            advanced = False
            for child in children:
                if child not in dep_map:
                    continue
                if marks[child] == ON_PATH:
                    cycle = path[on_path_index[child] :] + [child]
                    # A duplicate edge can close the same cycle twice within one
                    # tree; collapse on the node set rather than record it twice.
                    signature = frozenset(cycle)
                    if signature not in seen_signatures:
                        seen_signatures.add(signature)
                        cycles.append(cycle)
                    continue
                if marks[child] == UNVISITED:
                    marks[child] = ON_PATH
                    on_path_index[child] = len(path)
                    path.append(child)
                    stack.append((child, iter(dep_map[child])))
                    advanced = True
                    break
            if not advanced:
                marks[node] = DONE
                on_path_index.pop(node, None)
                path.pop()
                stack.pop()
    return cycles


def _is_attested(edge: dict[str, Any]) -> bool:
    """True when an external_dependencies entry is discharged by human attestation.

    v3 lets an entry discharge EITHER by resolved_by (a WorkItem that must be DONE)
    OR by an `attested` block, exclusively. An attested edge cannot be verified
    against the ledger -- that is the accepted weakening, and `by`/`at` being
    required is what stops an unowned assertion.

    An attested edge contributes no node to the dependency graph and no unmet
    target: there is no WorkItem to resolve. Both fall out of `resolved_by` being
    absent, and both are expressed below by the isinstance filter rather than by
    this predicate -- deliberately, because the isinstance filter also does the
    right thing for a malformed edge carrying both keys, where checking
    resolved_by is more useful than skipping it.
    """
    return "attested" in edge


def _edges(item: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Return the mapping entries of item[key], skipping anything that is not one.

    A malformed entry -- `[null]`, `['bad']`, `[42]` -- is already a schema
    violation, and cli.validate collects schema errors *and* runs these ledger
    checks. Without this guard, `edge.get(...)` raised AttributeError and the gate
    crashed instead of reporting the violation it had just recorded. A consumer
    could not see their own typo, and one character was enough to take the gate
    down.

    Skipping is correct rather than lenient: the schema error is the finding, and
    the ledger rules below cannot interpret an entry that has no fields.
    """
    raw = item.get(key) or []
    if not isinstance(raw, list):
        return []
    return [edge for edge in raw if isinstance(edge, dict)]


def build_dep_map(records: list[tuple[Path, dict[str, Any]]]) -> dict[str, list[str]]:
    """Map each record id to everything it waits on.

    Spans both dependency kinds. A cycle can pass through an external edge's
    discharge -- A waits on external B, and B's discharge is A -- so a map built
    from dependencies[] alone would miss it.
    """
    dep_map: dict[str, list[str]] = {}
    for _path, item in records:
        wid = item.get("id")
        if not isinstance(wid, str):
            continue
        targets: list[str] = [
            edge["target"]
            for edge in _edges(item, "dependencies")
            if isinstance(edge.get("target"), str)
        ]
        targets += [
            edge["resolved_by"]
            for edge in _edges(item, "external_dependencies")
            if isinstance(edge.get("resolved_by"), str)
        ]
        dep_map[wid] = targets
    return dep_map


@dataclass(frozen=True)
class InstanceProblem:
    path: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path}: [{self.rule}] {self.detail}"


def discover(root: Path, pattern: str) -> list[Path]:
    """Find WorkItem instances. Sorted so output is stable across runs."""
    return sorted(p for p in root.glob(pattern) if p.is_file())


def load_instance(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text())
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} is not a mapping")
    return loaded


def _declared_stem(path: Path) -> str:
    """The WorkItem id implied by where the file lives, e.g. ``WI-20261003-0005``."""
    return path.parent.name


def check_instance(
    path: Path,
    item: dict[str, Any],
    contract: Contract,
    engine: TransitionEngine,
) -> list[InstanceProblem]:
    """Every rule that can be decided from one record plus the contract data."""
    problems: list[InstanceProblem] = []
    rel = str(path)

    state = item.get("state")
    if state not in engine.states():
        problems.append(
            InstanceProblem(rel, "unknown-state", f"{state!r} is not a state in state-machine.yaml")
        )
    else:
        # A record may not sit in a state whose own gate it fails. This is what
        # stops a hand-edited `state: DONE` with nothing verified.
        #
        # Dispatched on the gate table's declared predicate, not hardcoded. Until
        # harkers/.github#29 this called check_before unconditionally, so six of the
        # eight `enforced: true` gates could never fire.
        verdict = evaluate_state_gates(item, contract.policy, state)
        if not verdict.ok:
            problems.append(
                InstanceProblem(rel, "state-gate", f"state {state}: {'; '.join(verdict.failures)}")
            )

    sizing = check_sizing(item, contract.sizing_policy)
    if not sizing.ok:
        problems.append(InstanceProblem(rel, "sizing", "; ".join(sizing.failures)))

    identifier = item.get("id")
    if not isinstance(identifier, str) or not ID_PATTERN.match(identifier):
        problems.append(
            InstanceProblem(rel, "malformed-id", f"id {identifier!r} is not WI-YYYYMMDD-NNNN")
        )
    elif identifier != _declared_stem(path):
        problems.append(
            InstanceProblem(
                rel,
                "id-path-mismatch",
                f"id {identifier} does not match its directory {_declared_stem(path)}",
            )
        )

    for edge in _edges(item, "dependencies"):
        target = str(edge.get("target", ""))
        if EXTERNAL_REF.match(target):
            problems.append(
                InstanceProblem(
                    rel,
                    "external-dependency",
                    f"target {target!r} is not a WorkItem id in this ledger. "
                    "External references are not expressible yet (harkers/.github#4).",
                )
            )

    return problems


def check_ledger(
    records: list[tuple[Path, dict[str, Any]]],
) -> list[InstanceProblem]:
    """Rules that need every record at once. Unresolvable edges are caught here."""
    problems: list[InstanceProblem] = []
    seen: dict[str, str] = {}

    for path, item in records:
        identifier = item.get("id")
        if isinstance(identifier, str):
            location = str(path)
            if identifier in seen:
                problems.append(
                    InstanceProblem(
                        location,
                        "duplicate-id",
                        f"id {identifier} also used by {seen[identifier]}",
                    )
                )
            else:
                seen[identifier] = location

    known = set(seen)
    for path, item in records:
        rel = str(path)
        parent = (item.get("hierarchy") or {}).get("parent")
        if parent and parent not in known:
            problems.append(
                InstanceProblem(
                    rel, "unresolved-parent", f"hierarchy.parent {parent!r} has no record"
                )
            )
        for edge in _edges(item, "dependencies"):
            target = str(edge.get("target", ""))
            if ID_PATTERN.match(target) and target not in known:
                problems.append(
                    InstanceProblem(
                        rel, "unresolved-dependency", f"dependency {target!r} has no record"
                    )
                )
        for edge in _edges(item, "external_dependencies"):
            if _is_attested(edge):
                continue  # discharged by attestation; there is no id to resolve
            discharge = str(edge.get("resolved_by", ""))
            if ID_PATTERN.match(discharge) and discharge not in known:
                problems.append(
                    InstanceProblem(
                        rel,
                        "unresolved-external-discharge",
                        f"resolved_by {discharge!r} is not a WorkItem id in this "
                        "ledger. Discharge must name real completed work here.",
                    )
                )

    for cycle in find_cycles(build_dep_map(records)):
        problems.append(
            InstanceProblem(
                str(Path("<ledger>")),
                "dependency-cycle",
                f"dependency cycle: {' -> '.join(cycle)}",
            )
        )

    # Satisfaction is a whole-ledger property: it depends on other records' current
    # states, so it cannot live in gates.check_before, which sees one record.
    #
    # Only DONE satisfies a dependency. CANCELLED deliberately does not -- if it did,
    # cancelling one WorkItem would silently release everything downstream, and
    # WI-20261003-0001 requires 11 others, so a single cancellation would collapse the
    # graph. Not reaching DONE is not a trap: CANCELLED stays reachable for every
    # record unconditionally, so the invariant is that at least one terminal state is
    # reachable, and DONE is reachable iff every dependency is DONE.
    states = {
        item.get("id"): item.get("state")
        for _path, item in records
        if isinstance(item.get("id"), str)
    }

    def unmet_targets(item: dict[str, Any]) -> list[str]:
        # A target absent from the ledger is reported here as unmet as well as by
        # unresolved-dependency above. That double report is deliberate: such a
        # record genuinely violates two rules -- its edge does not resolve, and it
        # cannot be DONE while waiting on something that does not exist. The cycle
        # check does not do this, because a dangling edge is only ever one defect.
        internal = [
            edge["target"]
            for edge in _edges(item, "dependencies")
            if isinstance(edge.get("target"), str)
        ]
        external = [
            edge["resolved_by"]
            for edge in _edges(item, "external_dependencies")
            if isinstance(edge.get("resolved_by"), str)
        ]
        return [t for t in internal + external if states.get(t) != "DONE"]

    for path, item in records:
        if item.get("state") != "DONE":
            continue
        for target in unmet_targets(item):
            problems.append(
                InstanceProblem(
                    str(path),
                    "dependency-not-satisfied",
                    f"state is DONE but {target!r} is "
                    f"{states.get(target, 'absent from the ledger')!r}. "
                    "Only DONE satisfies a dependency; CANCELLED does not.",
                )
            )

    return problems
