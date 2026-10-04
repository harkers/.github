"""Gate predicates driven entirely by policy.yaml.

Tests may name states, because an assertion has to name something. What they
must not do is enumerate the contract, or they become a fourth description of it.
"""

from __future__ import annotations

import copy
from dataclasses import replace

from workitem_conformance.contract import (
    band_for,
    combinations,
    load_contract,
    load_example,
)
from workitem_conformance.gates import (
    check_before,
    check_declared_gates,
    check_retroactive_criteria,
    check_review_transition,
    check_sizing,
)
from workitem_conformance.transitions import TransitionEngine, default_context

# Named here as fixtures only. The library under test names no state at all.
READY = "READY"
DONE = "DONE"


def _workitem(name: str = "task") -> dict:
    return copy.deepcopy(load_example(load_contract().root, name))


def test_a_conforming_task_passes_every_gate() -> None:
    c = load_contract()
    item = _workitem()
    assert check_before(item, c.policy, READY).ok
    assert check_sizing(item, c.sizing_policy).ok
    assert check_retroactive_criteria(item, c.policy, TransitionEngine(c.state_machine)).ok


def test_ready_refuses_empty_acceptance_criteria() -> None:
    c = load_contract()
    item = _workitem()
    item["acceptance_criteria"] = []
    assert not check_before(item, c.policy, READY).ok


def test_ready_refuses_an_unmeasurable_criterion() -> None:
    c = load_contract()
    item = _workitem()
    item["acceptance_criteria"][0]["expected"] = ""
    assert not check_before(item, c.policy, READY).ok


def test_ready_refuses_missing_scope_privacy_or_sizing() -> None:
    c = load_contract()
    for key in ("scope", "privacy", "sizing"):
        item = _workitem()
        del item[key]
        assert not check_before(item, c.policy, READY).ok, key


def test_done_refuses_incomplete_required_verification() -> None:
    c = load_contract()
    item = _workitem()
    item["verification"]["tests"]["status"] = "pending"
    item["completion"] = {"status": "complete", "packet": "evidence/packet.md"}
    assert not check_before(item, c.policy, DONE).ok


def test_done_refuses_a_missing_completion_packet() -> None:
    c = load_contract()
    item = _workitem()
    for name in item["verification"]["required"]:
        item["verification"][name]["status"] = "passed"
    item["completion"] = {"status": "complete", "packet": None}
    assert not check_before(item, c.policy, DONE).ok


def test_done_passes_only_when_all_required_evidence_is_present() -> None:
    c = load_contract()
    item = _workitem()
    for name in item["verification"]["required"]:
        item["verification"][name]["status"] = "passed"
    item["completion"] = {"status": "complete", "packet": "evidence/packet.md"}
    assert check_before(item, c.policy, DONE).ok


def test_done_with_no_required_verification_is_refused_outright() -> None:
    """INVERTED for workitem/v4.

    This test used to assert that an empty `verification.required` still reached DONE
    once a completion packet existed. It was pinning harkers/.github#31: the rule
    read the record's own list, so `required: []` -- or any list naming only the
    evidence that happened to pass -- opted the record out of its own review policy.

    v4 requires the union of the record's list and the policy floor, so this record
    cannot reach DONE at all. The packet assertion is kept below so the original
    intent (a packet is required) is not lost in the inversion.
    """
    c = load_contract()
    item = _workitem("investigation")
    assert item["verification"]["required"] == []
    policy = item["verification"]["review_policy"]

    item["completion"] = {"status": "complete", "packet": None}
    assert not check_before(item, c.policy, DONE).ok

    item["completion"] = {"status": "complete", "packet": "evidence/packet.md"}
    result = check_before(item, c.policy, DONE)
    assert not result.ok, f"an empty required list reached DONE under {policy!r}"
    assert any("policy floor" in f or "to be 'passed'" in f for f in result.failures), (
        f"expected a policy-floor failure, got {result.failures}"
    )


def test_done_needs_a_packet_even_when_the_floor_is_satisfied() -> None:
    """The packet half of the inverted test, kept as its own case so a future
    change cannot satisfy one requirement by breaking the other."""
    c = load_contract()
    item = _workitem("investigation")
    item["verification"]["review_policy"] = "low_risk"
    item["verification"]["required"] = []
    item["verification"]["local_review"] = {"status": "passed", "evidence": []}
    item["completion"] = {"status": "complete", "packet": None}
    assert not check_before(item, c.policy, DONE).ok
    item["completion"] = {"status": "complete", "packet": "evidence/packet.md"}
    assert check_before(item, c.policy, DONE).ok, (
        "with the floor met, the packet is the only remaining requirement"
    )


def test_an_unknown_rule_key_is_a_hard_error_not_a_silent_pass() -> None:
    c = load_contract()
    policy = copy.deepcopy(c.policy)
    policy["required_before"][READY]["rule_nobody_implemented"] = True
    result = check_before(_workitem(), policy, READY)
    assert not result.ok
    assert "rule_nobody_implemented" in result.failures[0]


def test_a_state_with_no_declared_preconditions_passes() -> None:
    c = load_contract()
    assert check_before(_workitem(), c.policy, "NOT_A_STATE").ok


def test_review_policy_requires_the_declared_evidence_set() -> None:
    c = load_contract()
    item = _workitem("feature")
    for name in item["verification"]["required"]:
        item["verification"][name]["status"] = "passed"
    # feature.yaml declares security_sensitive, which adds specialist_review.
    policy = c.policy["review_policy"]["required_evidence"][item["verification"]["review_policy"]]
    assert "specialist_review" in policy
    item["verification"]["specialist_review"]["status"] = "failed"
    assert not check_review_transition(item, c.policy).ok
    item["verification"]["specialist_review"]["status"] = "passed"
    assert check_review_transition(item, c.policy).ok


def test_low_risk_policy_does_not_require_cloud_review() -> None:
    c = load_contract()
    item = _workitem("investigation")
    item["verification"]["review_policy"] = "low_risk"
    item["verification"]["local_review"] = {"status": "passed", "evidence": []}
    item["verification"]["cloud_review"] = {"status": "failed", "evidence": []}
    assert check_review_transition(item, c.policy).ok

    item["verification"]["local_review"] = {"status": "failed", "evidence": []}
    assert not check_review_transition(item, c.policy).ok


def test_not_applicable_is_not_sufficient_when_policy_is_declared() -> None:
    c = load_contract()
    item = _workitem("feature")
    for name in item["verification"]["required"]:
        item["verification"][name] = {"status": "not_applicable", "evidence": []}
    assert not c.policy["review_policy"]["not_applicable_is_sufficient"]
    assert not check_review_transition(item, c.policy).ok


def test_retroactive_success_definition_is_refused() -> None:
    c = load_contract()
    item = _workitem()
    item["state"] = "IMPLEMENTED"
    item["acceptance_criteria"].append(
        {
            "id": "AC-002",
            "description": "Also handle the timeout case",
            "status": "pending",
            "verification_method": "named_check",
            "expected": "reviewer confirms timeout path",
        }
    )
    assert not check_retroactive_criteria(item, c.policy, TransitionEngine(c.state_machine)).ok


def test_retroactive_definition_is_allowed_before_the_declared_state() -> None:
    c = load_contract()
    item = _workitem()
    item["state"] = c.policy["immutable_after"][0]["after_state"]
    before = [r for r in c.policy["immutable_after"] if r["after_state"] == "DRAFT"]
    item["state"] = "DRAFT"
    assert check_retroactive_criteria(item, c.policy, TransitionEngine(c.state_machine)).ok, before


def test_sizing_band_must_agree_with_token_estimate() -> None:
    c = load_contract()
    item = _workitem()
    item["sizing"] = {"estimated_complexity": "XL", "estimated_context_tokens": 12000}
    assert not check_sizing(item, c.sizing_policy).ok


def test_sizing_requires_both_fields() -> None:
    c = load_contract()
    item = _workitem()
    item["sizing"] = {"estimated_complexity": "SMALL"}
    assert not check_sizing(item, c.sizing_policy).ok


def test_band_boundaries_come_from_the_policy_file() -> None:
    c = load_contract()
    names = [b["name"] for b in c.sizing_policy["bands"]]
    for tokens in (0, 7999, 8000, 19999, 20000, 39999, 40000, 10**9):
        assert band_for(tokens, c.sizing_policy) in names


def test_a_band_limit_opens_the_next_band() -> None:
    """Bands are half-open [min, max): a band owns values below its own max_tokens."""
    c = load_contract()
    bands = c.sizing_policy["bands"]
    for index, band in enumerate(bands):
        limit = band["max_tokens"]
        if limit is None:
            continue
        assert band_for(limit - 1, c.sizing_policy) == band["name"]
        assert band_for(limit, c.sizing_policy) == bands[index + 1]["name"]


def test_every_artifact_gate_is_refused_when_the_artifact_is_absent() -> None:
    c = load_contract()
    item = _workitem()
    item["artifacts"]["specification"] = None
    item["artifacts"]["implementation_plan"] = None
    item["artifacts"]["commits"] = []
    item["delivery"]["pull_request"] = None
    item["completion"]["packet"] = None
    result = check_declared_gates(item, c.policy)
    assert not result.ok
    assert len(result.failures) == 5, result.failures


def test_declared_gates_pass_once_artifacts_exist() -> None:
    c = load_contract()
    item = _workitem()
    item["artifacts"]["specification"] = "evidence/spec.md"
    item["artifacts"]["implementation_plan"] = "evidence/plan.md"
    item["artifacts"]["commits"] = ["abc1234"]
    item["delivery"]["pull_request"] = 42
    item["completion"]["packet"] = "evidence/packet.md"
    assert check_declared_gates(item, c.policy).ok


def test_advisory_gates_are_never_reported_as_failures() -> None:
    """A gate marked enforced:false needs judgement, so the suite must not fake it."""
    c = load_contract()
    advisory = {g["state"] for g in c.policy["gates"] if not g.get("enforced")}
    assert advisory, "the contract must record which gates are advisory"
    item = _workitem()
    failures = check_declared_gates(item, c.policy).failures
    assert failures, "a bare DRAFT task should still fail the artifact gates"
    assert not any(f.startswith(tuple(advisory)) for f in failures), failures


def test_the_gate_table_covers_every_happy_path_state() -> None:
    """Exceptional states are governed by the edge set, not by entry gates."""
    c = load_contract()
    engine = TransitionEngine(c.state_machine)
    gated = {g["state"] for g in c.policy["gates"]}
    exempt = {e["state"] for e in c.policy["no_entry_gate"]}
    missing = sorted(set(c.state_machine["states"]["happy_path"]) - gated - exempt)
    assert not missing, f"happy-path states with neither a gate nor an exemption: {missing}"
    assert exempt <= set(c.state_machine["states"]["happy_path"]), exempt
    unknown = sorted(gated - engine.states())
    assert not unknown, f"gates for states the machine does not declare: {unknown}"


def test_every_enforced_gate_names_a_predicate_that_exists() -> None:
    """An enforced gate with no working predicate is a gate that does nothing."""
    import workitem_conformance.gates as gates_module

    c = load_contract()
    for gate in c.policy["gates"]:
        if not gate.get("enforced"):
            assert "predicate" not in gate, gate
            continue
        name = gate.get("predicate")
        assert name, f"{gate['state']} is enforced but names no predicate"
        assert callable(getattr(gates_module, name, None)), name


def test_gate_with_when_is_skipped_for_other_modes() -> None:
    """A `when` that does not match must stop the gate firing, not fail it."""
    c = load_contract()
    item = _workitem()
    item["delivery"] = {"mode": "branch_only", "branch": "wi/WI-x/y", "pull_request": None}
    failures = check_declared_gates(item, c.policy).failures
    assert not [f for f in failures if "PR_DRAFT" in f], failures


def test_pr_draft_gate_only_binds_for_pull_request() -> None:
    """The specific incoherence: branch_only has no PR, so the gate cannot demand one."""
    c = load_contract()
    item = _workitem()
    item["artifacts"]["specification"] = "s.md"
    item["artifacts"]["implementation_plan"] = "p.md"
    item["artifacts"]["commits"] = ["abc"]
    item["completion"]["packet"] = "packet.md"
    item["delivery"] = {"mode": "pull_request", "branch": "wi/x", "pull_request": None}
    assert [f for f in check_declared_gates(item, c.policy).failures if "PR_DRAFT" in f]

    item["delivery"] = {"mode": "branch_only", "branch": "wi/x", "pull_request": None}
    assert not [f for f in check_declared_gates(item, c.policy).failures if "PR_DRAFT" in f]


def test_no_reachable_state_has_an_unsatisfiable_gate() -> None:
    """I3: no gate may demand a field the active mode forbids.

    Born green by design. A gate can only be unsatisfiable if the schema forbids
    the field, so this becomes meaningful once the schema constraint lands. It
    guards against future incoherence; it does not demonstrate a present one.
    """
    contract = load_contract()
    forbidden = _forbidden_by_mode(contract)
    assert forbidden, "the schema declares no mode forbiddance, so I3 cannot bite yet"
    for mode, policy in combinations(contract):
        for state in _reachable(contract, mode, policy):
            for gate in contract.policy["gates"]:
                if gate["state"] != state or not gate.get("enforced"):
                    continue
                required = gate.get("artifact_required")
                if not required:
                    continue
                when = gate.get("when") or {}
                if "delivery_mode" in when and when["delivery_mode"] != mode:
                    continue
                assert required not in forbidden.get(mode, set()), (
                    f"{mode}/{policy}: {state} demands {required}, which the mode forbids"
                )


def _forbidden_by_mode(contract) -> dict[str, set[str]]:
    """Fields the schema nulls per mode. Read from the schema, never hardcoded."""
    out: dict[str, set[str]] = {}
    for clause in contract.schema.get("allOf", []):
        condition = clause.get("if", {}).get("properties", {}).get("delivery", {})
        mode = condition.get("properties", {}).get("mode", {})
        key = mode.get("const") or (mode.get("enum") or [None])[0]
        if key is None:
            continue
        fields = (
            clause.get("then", {}).get("properties", {}).get("delivery", {}).get("properties", {})
        )
        out[key] = {
            f"delivery.{name}" for name, spec in fields.items() if spec.get("type") == "null"
        }
    return out


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
