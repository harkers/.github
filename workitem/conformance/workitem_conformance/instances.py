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
from workitem_conformance.gates import check_before, check_sizing
from workitem_conformance.transitions import TransitionEngine

ID_PATTERN = re.compile(r"^WI-\d{8}-\d{4}$")
# A dependency may not name anything outside the ledger today. See harkers/.github#4.
EXTERNAL_REF = re.compile(r"^(?!\d)(?!WI-).+")


def find_cycles(dep_map: dict[str, list[str]]) -> list[list[str]]:
    """Return every cycle in the dependency graph, each as a node list.

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
                    # The same cycle is reachable from each of its nodes; report it once.
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
        targets = [
            edge.get("target")
            for edge in item.get("dependencies") or []
            if isinstance(edge.get("target"), str)
        ]
        targets += [
            edge.get("resolved_by")
            for edge in item.get("external_dependencies") or []
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
        verdict = check_before(item, contract.policy, state)
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

    for edge in item.get("dependencies") or []:
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
        for edge in item.get("dependencies") or []:
            target = str(edge.get("target", ""))
            if ID_PATTERN.match(target) and target not in known:
                problems.append(
                    InstanceProblem(
                        rel, "unresolved-dependency", f"dependency {target!r} has no record"
                    )
                )
        for edge in item.get("external_dependencies") or []:
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

    return problems
