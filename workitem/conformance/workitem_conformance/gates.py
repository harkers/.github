"""Gate predicates driven entirely by ``policy.yaml``.

Every threshold, required field name, rule and forbidden pair is read from the
policy. This module names no state and embeds no rule: adding a gate to
``policy.yaml`` must never require editing this file.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from workitem_conformance.contract import band_for
from workitem_conformance.transitions import TransitionEngine, WorkItemContext


@dataclass(frozen=True)
class GateResult:
    ok: bool
    failures: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.ok


def _criteria(workitem: dict[str, Any]) -> list[dict[str, Any]]:
    return list(workitem.get("acceptance_criteria") or [])


def _read(workitem: dict[str, Any], dotted: str) -> Any:
    """Resolve a root-relative dotted path, e.g. `verification.review_policy`."""
    value: Any = workitem
    for part in dotted.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _condition_met(workitem: dict[str, Any], when: dict[str, Any] | None) -> bool:
    """Evaluate a gate's `when` clause against the record.

    Mirrors the state machine's condition syntax so there is one mechanism, not
    two. A gate with no `when` applies unconditionally.
    """
    if not when:
        return True
    if "delivery_mode" in when:
        expected = when["delivery_mode"]
        allowed = expected if isinstance(expected, list) else [expected]
        if _read(workitem, "delivery.mode") not in allowed:
            return False
    return True


def _present(workitem: dict[str, Any], dotted: str) -> bool:
    return _read(workitem, dotted) not in (None, "", [], {})


# Each entry interprets one rule key from policy.required_before. A new key in
# the policy without an entry here is a hard error in check_before, not a
# silently ignored rule.
_RULES: dict[str, Callable[[dict[str, Any], Any], bool]] = {
    "acceptance_criteria_min": lambda w, r: len(_criteria(w)) >= r,
    "acceptance_criteria_must_be_measurable": lambda w, r: (
        (not r)
        or all(
            bool(c.get("verification_method")) and bool(str(c.get("expected", "")).strip())
            for c in _criteria(w)
        )
    ),
    "sizing_required": lambda w, r: (not r) or bool(w.get("sizing")),
    "scope_required": lambda w, r: (not r) or _present(w, "scope"),
    "privacy_required": lambda w, r: (not r) or _present(w, "privacy"),
    "all_required_verification": lambda w, r: all(
        (w.get("verification", {}).get(name) or {}).get("status") == r
        for name in (w.get("verification") or {}).get("required", [])
    ),
    "completion_packet_required": lambda w, r: (not r) or _present(w, "completion.packet"),
}


def check_before(workitem: dict[str, Any], policy: dict[str, Any], state: str) -> GateResult:
    """Evaluate every rule the policy declares as a precondition for `state`."""
    rules = policy.get("required_before", {}).get(state)
    if rules is None:
        return GateResult(True, ())
    unknown = sorted(set(rules) - set(_RULES))
    if unknown:
        return GateResult(False, (f"policy.required_before.{state} has unknown rules: {unknown}",))
    failures = tuple(
        f"{state} requires {key}" for key, rule in rules.items() if not _RULES[key](workitem, rule)
    )
    return GateResult(not failures, failures)


def check_review_transition(workitem: dict[str, Any], policy: dict[str, Any]) -> GateResult:
    spec = policy["review_policy"]
    active = _read(workitem, spec["field"])
    required = spec["required_evidence"].get(active)
    if required is None:
        return GateResult(False, (f"unknown review policy {active!r}",))
    failures = tuple(
        f"verification.{name} must be 'passed' under review_policy={active}"
        for name in required
        if (workitem.get("verification") or {}).get(name, {}).get("status") != "passed"
    )
    return GateResult(not failures, failures)


def check_retroactive_criteria(
    workitem: dict[str, Any],
    policy: dict[str, Any],
    engine: TransitionEngine,
) -> GateResult:
    """Refuse redefining success once the contract says the field has closed.

    "At or beyond" is decided by the happy-path order in state-machine.yaml, not
    by string comparison, so reordering the ladder cannot silently change which
    criteria are frozen.
    """
    order = engine.happy_path()
    reached = {
        workitem.get("state"),
        *((workitem.get("hierarchy") or {}).get("visited_states") or []),
    }

    def at_or_beyond(state: str | None, threshold: str) -> bool:
        if state == threshold:
            return True
        if threshold not in order:
            return False
        if state not in order:
            # Exceptional states are late-stage by construction: a WorkItem
            # cannot fail or block its way back to before specification.
            return True
        return order[state] >= order[threshold]

    failures = tuple(
        f"{rule['field']} is immutable from {rule['after_state']} onward ({rule['reason'].strip()})"
        for rule in policy.get("immutable_after", [])
        if any(at_or_beyond(state, rule["after_state"]) for state in reached)
    )
    return GateResult(not failures, failures)


def check_sizing(workitem: dict[str, Any], sizing_policy: dict[str, Any]) -> GateResult:
    sizing = workitem.get("sizing") or {}
    tokens = sizing.get("estimated_context_tokens")
    declared = sizing.get("estimated_complexity")
    if tokens is None or declared is None:
        return GateResult(
            False,
            ("sizing.estimated_complexity and estimated_context_tokens are both required",),
        )
    derived = band_for(tokens, sizing_policy)
    failures = (
        () if derived == declared else (f"band {declared!r} disagrees with derived {derived!r}",)
    )
    return GateResult(not failures, failures)


def check_declared_gates(
    workitem: dict[str, Any],
    policy: dict[str, Any],
    state: str | None = None,
) -> GateResult:
    """Check the gates the policy marks `enforced: true` with an artifact requirement.

    Gates without an `artifact_required` field are enforced by `required_before`
    or by `check_review_transition`. This covers the artifact-presence family
    generically so no state name appears here.

    `state` scopes the check to one state's gate. Without it every enforced gate is
    evaluated, which demands a specification, a plan and a completion packet at once --
    so it could only ever be called from a test, never from validation. harkers/.github#29.
    """
    failures: list[str] = []
    for gate in policy.get("gates", []):
        if not gate.get("enforced"):
            continue
        if state is not None and gate.get("state") != state:
            continue
        if not _condition_met(workitem, gate.get("when")):
            continue
        dotted = gate.get("artifact_required")
        if not dotted:
            continue
        value: Any = workitem
        for part in dotted.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        minimum = gate.get("artifact_min_items", 1)
        ok = len(value) >= minimum if isinstance(value, list) else value not in (None, "", [], {})
        if not ok:
            failures.append(f"{gate['state']} requires {dotted} ({gate['note'].strip()})")
    return GateResult(not failures, tuple(failures))


def evaluate_state_gates(
    workitem: dict[str, Any],
    policy: dict[str, Any],
    state: str,
) -> GateResult:
    """Run whichever predicate `policy.yaml` declares for `state`.

    Dispatching on the declared predicate is what makes the gate table mean something.
    Hardcoding `check_before` -- which is what validation did until harkers/.github#29 --
    meant six of eight `enforced: true` gates could never fire, however clearly the
    policy declared them.

    An unknown predicate is a failure rather than a silent pass: a gate table that has
    drifted from the checker must not read as clean.
    """
    gate = next((g for g in policy.get("gates", []) if g.get("state") == state), None)
    predicate = (gate or {}).get("predicate")

    if predicate is None:
        # No gate declared for this state. States with no declared gate are ordinary
        # mid-ladder states, not an omission to enforce against.
        return GateResult(True, ())

    if predicate == "check_before":
        return check_before(workitem, policy, state)
    if predicate == "check_declared_gates":
        return check_declared_gates(workitem, policy, state=state)
    if predicate == "check_review_transition":
        if "review_policy" not in policy:
            return GateResult(
                False,
                (
                    "policy declares a check_review_transition gate but declares no "
                    "review_policy block for it to read",
                ),
            )
        return check_review_transition(workitem, policy)

    return GateResult(
        False,
        (
            f"policy gate for {state} declares predicate {predicate!r}, which this "
            f"checker does not implement. Known: check_before, check_declared_gates, "
            "check_review_transition.",
        ),
    )


def check_forbidden_transitions(
    policy: dict[str, Any],
    engine: TransitionEngine,
    ctx: WorkItemContext,
) -> GateResult:
    failures = tuple(
        f"{e['from']} -> {e['to']} must be illegal: {e['reason']}"
        for e in policy.get("forbidden_transitions", [])
        if engine.check(e["from"], e["to"], ctx).legal
    )
    return GateResult(not failures, failures)
