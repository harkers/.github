"""Generic transition legality over the declared edge set.

No state name and no edge is written in this module. Everything is read from
``state-machine.yaml``, so adding a state to the contract cannot leave this
engine behind.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

WILDCARD = "*"


@dataclass(frozen=True)
class WorkItemContext:
    """The non-state inputs legality depends on."""

    delivery_mode: str
    review_policy: str
    verification: dict[str, str]
    has_completion_packet: bool
    past_specification: bool


@dataclass(frozen=True)
class Verdict:
    legal: bool
    reason: str


def default_context() -> WorkItemContext:
    return WorkItemContext(
        delivery_mode="pull_request",
        review_policy="normal",
        verification={},
        has_completion_packet=False,
        past_specification=False,
    )


class TransitionEngine:
    def __init__(self, machine: dict[str, Any]) -> None:
        self.machine = machine
        self._happy: list[str] = list(machine["states"]["happy_path"])
        self._exceptional: list[str] = list(machine["states"]["exceptional"])
        self._terminal: frozenset[str] = frozenset(machine["terminal"])
        self._declared: set[tuple[str, str]] = set()
        self._conditional: list[tuple[str, str, dict[str, Any]]] = []
        self._wildcards: list[tuple[str, dict[str, Any]]] = []
        self._specs: dict[tuple[str, str], dict[str, Any]] = {}
        for edge in machine["transitions"]:
            frm, to = edge["from"], edge["to"]
            when = edge.get("when")
            self._specs[(frm, to)] = edge
            if frm == WILDCARD:
                self._wildcards.append((to, when or {}))
            elif when:
                self._conditional.append((frm, to, when))
            else:
                self._declared.add((frm, to))

    def states(self) -> frozenset[str]:
        return frozenset(self._happy) | frozenset(self._exceptional)

    def terminal_states(self) -> frozenset[str]:
        return self._terminal

    def happy_path(self) -> dict[str, int]:
        return {name: i for i, name in enumerate(self._happy)}

    def edge_spec(self, frm: str, to: str) -> dict[str, Any]:
        """The raw declared edge, including any `when` condition. Never invents one."""
        return self._specs.get((frm, to), {})

    def edges(self) -> list[tuple[str, str]]:
        return sorted(self._declared | self._conditional_edges())

    def _conditional_edges(self) -> set[tuple[str, str]]:
        return {(frm, to) for frm, to, _ in self._conditional}

    def outgoing(self, state: str) -> Iterator[str]:
        for frm, to in self.edges():
            if frm == state:
                yield to
        for to, when in self._wildcards:
            if when.get("source_not_terminal") and state not in self._terminal:
                yield to

    def wildcard_targets(self) -> list[str]:
        return sorted(to for to, _ in self._wildcards)

    def skipped_by_delivery_mode(self, delivery_mode: str) -> list[str]:
        for name, spec in self.machine["parameters"].items():
            if name == "delivery_mode" and delivery_mode == "none":
                return list(spec["skips_states"])
        return []

    def declared(self, frm: str, to: str) -> bool:
        """Is this edge in the contract, ignoring context? Exhaustive by construction."""
        if (frm, to) in self._declared:
            return True
        if any(cfrm == frm and cto == to for cfrm, cto, _ in self._conditional):
            return True
        return any(
            target == to and when.get("source_not_terminal") and frm not in self._terminal
            for target, when in self._wildcards
        )

    def check(self, frm: str, to: str, ctx: WorkItemContext) -> Verdict:
        if frm not in self.states():
            return Verdict(False, f"unknown source state {frm!r}")
        if to not in self.states():
            return Verdict(False, f"unknown target state {to!r}")
        if frm in self._terminal:
            return Verdict(False, f"{frm} is terminal")

        # A state the contract skips under this delivery mode is unreachable under
        # it, whether the edge into it was unconditional, conditional or wildcard.
        skipped = self.skipped_by_delivery_mode(ctx.delivery_mode)
        if to in skipped:
            return Verdict(False, f"{to} is unreachable under delivery.mode={ctx.delivery_mode}")

        for cfrm, cto, when in self._conditional:
            if cfrm == frm and cto == to:
                if when.get("delivery_mode") == ctx.delivery_mode:
                    return Verdict(True, f"conditional edge for delivery.mode={ctx.delivery_mode}")
                return Verdict(False, f"conditional edge requires {when}")

        for target, when in self._wildcards:
            if target == to and when.get("source_not_terminal"):
                return Verdict(True, "wildcard edge from a non-terminal state")

        if (frm, to) in self._declared:
            return Verdict(True, "declared edge")
        return Verdict(False, f"no declared edge {frm} -> {to}")
