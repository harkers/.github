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

    return problems
