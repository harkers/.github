"""The contract files must agree with each other and be fully documented."""

from __future__ import annotations

from workitem_conformance.contract import load_contract, load_example
from workitem_conformance.gates import (
    check_before,
    check_forbidden_transitions,
    check_sizing,
)
from workitem_conformance.transitions import TransitionEngine, default_context

EXAMPLE_NAMES = ["task", "bug", "feature", "investigation"]


def _readme() -> str:
    return (load_contract().root / "workitem" / "README.md").read_text()


def test_every_state_is_documented_in_the_readme() -> None:
    engine = TransitionEngine(load_contract().state_machine)
    readme = _readme()
    missing = [s for s in sorted(engine.states()) if s not in readme]
    assert not missing, f"undocumented states: {missing}"


def test_the_readme_states_the_canonical_rule() -> None:
    readme = _readme()
    assert "No WorkItem" in readme and "No Work" in readme
    assert "GENERATED" in readme.upper(), "TODO.md must be marked non-authoritative"


def test_the_readme_defers_the_ladder_rather_than_restating_it() -> None:
    """The README may show the ladder; it must not claim to be the definition."""
    readme = _readme()
    assert "state-machine.yaml" in readme
    assert "not redefine" in readme or "MUST NOT redefine" in readme


def test_the_schema_declares_dependency_types() -> None:
    c = load_contract()
    declared = c.schema["properties"]["dependencies"]["items"]["properties"]["type"]["enum"]
    assert declared, "schema declares no dependency types"


def test_every_state_named_in_policy_exists_in_the_state_machine() -> None:
    c = load_contract()
    engine = TransitionEngine(c.state_machine)
    states = engine.states()
    referenced: set[str] = set(c.policy["required_before"])
    for rule in c.policy["immutable_after"]:
        referenced.add(rule["after_state"])
    for entry in c.policy["forbidden_transitions"]:
        referenced.update((entry["from"], entry["to"]))
    referenced.update(g["state"] for g in c.policy["gates"])
    referenced.update(e["state"] for e in c.policy["no_entry_gate"])
    missing = sorted(s for s in referenced if s not in states)
    assert not missing, f"policy references unknown states: {missing}"


def test_every_required_review_evidence_name_is_a_schema_property() -> None:
    c = load_contract()
    props = set(c.schema["properties"]["verification"]["properties"])
    for name, required in c.policy["review_policy"]["required_evidence"].items():
        unknown = [n for n in required if n not in props]
        assert not unknown, f"review_policy {name} names unknown evidence: {unknown}"
    assert set(c.policy["review_policy"]["values"]) == set(
        c.schema["properties"]["verification"]["properties"]["review_policy"]["enum"]
    ), "review_policy values and the schema enum disagree"


def test_every_sizing_band_name_is_a_schema_enum_value() -> None:
    c = load_contract()
    allowed = set(c.schema["properties"]["sizing"]["properties"]["estimated_complexity"]["enum"])
    for band in c.sizing_policy["bands"]:
        assert band["name"] in allowed, band["name"]
    assert allowed == {b["name"] for b in c.sizing_policy["bands"]}, (
        "the schema and sizing-policy disagree about the band set"
    )


def test_every_artifact_gate_path_exists_in_the_schema() -> None:
    c = load_contract()
    for gate in c.policy["gates"]:
        dotted = gate.get("artifact_required")
        if not dotted:
            continue
        node = c.schema
        for part in dotted.split("."):
            assert isinstance(node, dict), f"{gate['state']}: {dotted} traverses a non-object"
            if "properties" in node:
                node = node["properties"]
            assert part in node, f"{gate['state']}: {dotted} has no {part}"
            node = node[part]


def test_no_forbidden_transition_is_actually_legal() -> None:
    c = load_contract()
    engine = TransitionEngine(c.state_machine)
    result = check_forbidden_transitions(c.policy, engine, default_context())
    assert result.ok, result.failures


def test_every_forbidden_transition_is_meaningfully_forbidden() -> None:
    """A forbidden pair that is already illegal everywhere adds no protection."""
    c = load_contract()
    engine = TransitionEngine(c.state_machine)
    for entry in c.policy["forbidden_transitions"]:
        frm, to = entry["from"], entry["to"]
        assert frm in engine.states() and to in engine.states(), entry
        assert not engine.declared(frm, to), f"{frm}->{to} is a declared edge"


def test_examples_declare_states_the_machine_knows() -> None:
    """Each example satisfies the gate for the state it declares, and the READY bar.

    It must NOT satisfy DONE: these are DRAFT examples, and a DRAFT WorkItem that
    already carried a completion packet would itself be a contract violation.
    """
    c = load_contract()
    engine = TransitionEngine(c.state_machine)
    ready = "READY"
    assert ready in c.policy["required_before"], "the contract must gate READY"
    for name in EXAMPLE_NAMES:
        item = load_example(c.root, name)
        assert item["state"] in engine.states(), name
        assert check_before(item, c.policy, item["state"]).ok, f"{name}/{item['state']}"
        assert check_before(item, c.policy, ready).ok, f"{name}/{ready}"
        assert check_sizing(item, c.sizing_policy).ok, name
        assert not check_before(item, c.policy, "DONE").ok, (
            f"{name} is a DRAFT example and must not already satisfy the DONE gate"
        )


def test_every_example_carries_a_privacy_level_and_a_scope() -> None:
    """The confidentiality boundary is not optional on any WorkItem."""
    c = load_contract()
    levels = set(c.schema["properties"]["privacy"]["properties"]["level"]["enum"])
    for name in EXAMPLE_NAMES:
        item = load_example(c.root, name)
        assert item["privacy"]["level"] in levels, name
        assert item["scope"]["allowed_paths"], name


def test_examples_cover_every_contract_concern() -> None:
    """The four examples between them exercise the contract's parameters."""
    c = load_contract()
    examples = [load_example(c.root, n) for n in EXAMPLE_NAMES]
    delivery_modes = {e["delivery"]["mode"] for e in examples}
    assert "none" in delivery_modes, "no example skips the PR ceremony"
    policies = {e["verification"]["review_policy"] for e in examples}
    assert len(policies) >= 2, f"examples only cover review policies {policies}"
    bands = {e["sizing"]["estimated_complexity"] for e in examples}
    assert len(bands) >= 2, f"examples only cover sizing bands {bands}"
    types = {e["identity"]["type"] for e in examples}
    assert {"TASK", "BUG", "FEATURE", "INVESTIGATION"} <= types, types
    assert any(e["dependencies"] for e in examples), "no example has a dependency edge"
    assert any(e["delivery"]["mode"] == "none" for e in examples)
    methods = {ac["verification_method"] for e in examples for ac in e["acceptance_criteria"]}
    assert {"command", "artifact", "named_check"} <= methods, methods
