# Delivery-Mode Reachability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every WorkItem able to finish under every `delivery_mode`, and make the state machine and the gate policy agree about what each mode means.

**Architecture:** The contract stays pure data. Two changes to `state-machine.yaml` give every mode a reachable route to `DONE`; one `when:` condition on the single gate that needs it makes the gate table mode-aware; one schema constraint makes a contradictory record inexpressible. The engine's conditional-edge evaluation is corrected first, because the new edges depend on it — two conditionals sharing a `(from, to)` pair currently shadow each other.

**Tech Stack:** Python >=3.12, `jsonschema>=4.21`, `PyYAML>=6.0`, `pytest>=7.0`, `ruff>=0.1` (line-length 100, rules `E,W,F,I,B,C4,UP`).

**Spec:** [`docs/superpowers/specs/2026-10-03-delivery-mode-reachability-design.md`](../specs/2026-10-03-delivery-mode-reachability-design.md)

**Fixes:** `harkers/.github`#8

---

## Global Constraints

- No module under `workitem/conformance/workitem_conformance/` may embed a state name, a transition edge, a sizing band or a policy rule as a literal. Contract data only.
- Tests may name states and edges as assertions, but must **not enumerate** the contract. Every test that asserts a set, graph or matrix reads it from a contract file.
- Contract version `workitem/v1.1`, schema version stays `"1.0"`, gate tag `workitem-gate/v3`.
- **Tightening a schema does not bump `schema_version`** (spec D8). Records keep `"1.0"`.
- Contract artifacts live under `workitem/` and are data, never code.
- `state-machine.yaml` is the sole definition of the lifecycle; `policy.yaml` the sole definition of gates and forbidden transitions.
- Ruff must pass clean before any task is committed.

**Some code blocks in this plan are method-body fragments, indented at class level.** They are
replacement snippets for the method named in the surrounding prose, not programs to paste into a file.
Do not run `ast.parse` over them or expect them to stand alone.

**Ordering constraint that must not be violated:** Task 1 (engine) lands before Task 2 (edges). Applying Task 2 first produces a state machine whose `delivery.mode: none` path still cannot reach `DONE`, and no test catches it until Task 1 exists.

---

## File Structure

| Path | Responsibility |
|---|---|
| `workitem/state-machine.yaml` | `skips_states_by_mode`; three conditional edges |
| `workitem/policy.yaml` | `when:` on `PR_DRAFT`; `parameters.review_policy` with `affects: gates` |
| `workitem/v1.schema.json` | `allOf` delivery/mode constraints |
| `workitem/contract-version.yaml` | `current: v1.1`; `v1.1` schema_version corrected to `"1.0"` |
| `workitem/conformance/workitem_conformance/transitions.py` | Per-mode skip lookup; non-shadowing conditional evaluation; `edge_spec` returns all variants |
| `workitem/conformance/workitem_conformance/gates.py` | `check_declared_gates` honours `when` |
| `workitem/conformance/tests/test_transitions.py` | Engine-level tests for the above |
| `workitem/conformance/tests/test_gates.py` | `when` handling |
| `workitem/conformance/tests/test_parameter_space.py` | **New.** The three invariants, enumerated from the contract |
| `workitem/conformance/tests/test_examples.py` | Schema rejection fixtures for the new constraints |

---

## Task 1: Conditional edges must not shadow each other

The engine change on its own. No contract data changes, so nothing can regress.

**Files:**
- Modify: `workitem/conformance/workitem_conformance/transitions.py`
- Modify: `workitem/conformance/tests/test_transitions.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `TransitionEngine.edge_specs(frm: str, to: str) -> list[dict[str, Any]]` — every declared variant for the pair, in declaration order
  - `TransitionEngine.skipped_by_delivery_mode(delivery_mode: str) -> list[str]` — reads `skips_states_by_mode`, defaulting to `[]`

---

- [ ] **Step 1: Write the failing test**

Append to `workitem/conformance/tests/test_transitions.py`:

```python
def _machine_with_two_conditionals_for_one_pair() -> dict:
    """Two REPORTING -> DONE edges, one per mode. The case the fix depends on."""
    return {
        "states": {"happy_path": ["DRAFT", "REPORTING", "DONE"], "exceptional": []},
        "terminal": ["DONE"],
        "repair": {"state": "NONE", "resume_state": "DRAFT", "entry_states": []},
        "failure": {"state": "NONE", "resume_state": "DRAFT", "entry_states": []},
        "parameters": {
            "delivery_mode": {
                "field": "delivery.mode",
                "values": ["pull_request", "branch_only", "none"],
                "default": "pull_request",
                "skips_states_by_mode": {
                    "pull_request": [],
                    "branch_only": [],
                    "none": [],
                },
            }
        },
        "transitions": [
            {"from": "DRAFT", "to": "REPORTING"},
            {"from": "REPORTING", "to": "DONE", "when": {"delivery_mode": "branch_only"}},
            {"from": "REPORTING", "to": "DONE", "when": {"delivery_mode": "none"}},
        ],
    }


def test_both_conditionals_for_one_pair_are_honoured() -> None:
    """A duplicate (from, to) pair must not shadow: first-wins made `none` unreachable."""
    engine = TransitionEngine(_machine_with_two_conditionals_for_one_pair())
    assert engine.check("REPORTING", "DONE", _ctx(delivery_mode="branch_only")).legal
    assert engine.check("REPORTING", "DONE", _ctx(delivery_mode="none")).legal
    assert not engine.check("REPORTING", "DONE", _ctx(delivery_mode="pull_request")).legal


def test_edge_specs_returns_every_variant_for_a_duplicated_pair() -> None:
    engine = TransitionEngine(_machine_with_two_conditionals_for_one_pair())
    variants = engine.edge_specs("REPORTING", "DONE")
    assert [v["when"]["delivery_mode"] for v in variants] == ["branch_only", "none"]


def test_edge_specs_is_empty_for_an_undeclared_pair() -> None:
    engine = TransitionEngine(_machine_with_two_conditionals_for_one_pair())
    assert engine.edge_specs("DRAFT", "DONE") == []


def test_skips_are_read_per_mode_not_only_for_none() -> None:
    machine = _machine_with_two_conditionals_for_one_pair()
    machine["parameters"]["delivery_mode"]["skips_states_by_mode"]["none"] = ["REPORTING"]
    engine = TransitionEngine(machine)
    assert engine.skipped_by_delivery_mode("none") == ["REPORTING"]
    assert engine.skipped_by_delivery_mode("branch_only") == []
    assert engine.skipped_by_delivery_mode("a_mode_nobody_declared") == []


def test_a_skipped_destination_is_refused_for_every_edge_kind() -> None:
    """The skip must win over unconditional, conditional and wildcard alike."""
    machine = _machine_with_two_conditionals_for_one_pair()
    machine["parameters"]["delivery_mode"]["skips_states_by_mode"]["none"] = ["DONE"]
    machine["transitions"].append({"from": "DRAFT", "to": "DONE"})
    machine["transitions"].append({"from": "*", "to": "DONE", "when": {"source_not_terminal": True}})
    engine = TransitionEngine(machine)
    assert not engine.check("DRAFT", "DONE", _ctx(delivery_mode="none")).legal
    assert engine.check("DRAFT", "DONE", _ctx(delivery_mode="pull_request")).legal
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest workitem/conformance/tests/test_transitions.py -v -k "both_conditionals or edge_specs or skips_are_read or skipped_destination"`

Expected: FAIL — `AttributeError: 'TransitionEngine' object has no attribute 'edge_specs'`

- [ ] **Step 3: Replace `_specs`, `edge_spec`, `skipped_by_delivery_mode` and `check`'s conditional loop**

In `workitem/conformance/workitem_conformance/transitions.py`, replace the single-spec store in `__init__`:

```python
        self._specs: dict[tuple[str, str], dict[str, Any]] = {}
        for edge in machine["transitions"]:
            frm, to = edge["from"], edge["to"]
            when = edge.get("when")
            # A pair may legitimately appear twice with different conditions, so
            # collect every variant rather than keeping only one.
            self._specs.setdefault((frm, to), []).append(edge)
            if frm == WILDCARD:
                self._wildcards.append((to, when or {}))
            elif when:
                self._conditional.append((frm, to, when))
            else:
                self._declared.add((frm, to))
```

Replace `edge_spec`:

```python
    def edge_specs(self, frm: str, to: str) -> list[dict[str, Any]]:
        """Every declared variant of this edge, in declaration order."""
        return list(self._specs.get((frm, to), []))

    def edge_spec(self, frm: str, to: str) -> dict[str, Any]:
        """The single variant, or an empty dict. Prefer edge_specs() where a pair
        may be duplicated."""
        variants = self.edge_specs(frm, to)
        return variants[0] if variants else {}
```

Replace `skipped_by_delivery_mode`:

```python
    def skipped_by_delivery_mode(self, delivery_mode: str) -> list[str]:
        """States unreachable under this mode. An undeclared mode skips nothing."""
        by_mode = self.machine.get("parameters", {}).get("delivery_mode", {})
        return list(by_mode.get("skips_states_by_mode", {}).get(delivery_mode, []))
```

Replace the conditional loop inside `check`:

```python
        # Scan every conditional for this pair. A pair may be declared once per
        # mode, so first-match-wins would refuse whichever condition came second.
        matched = False
        for cfrm, cto, when in self._conditional:
            if cfrm == frm and cto == to:
                matched = True
                if when.get("delivery_mode") == ctx.delivery_mode:
                    return Verdict(True, f"conditional edge for delivery.mode={ctx.delivery_mode}")
        if matched:
            return Verdict(False, "every declared condition on this edge was unmet")
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest workitem/conformance -q`

Expected: PASS, count unchanged from 109. No previously-passing test may break — scan-all is strictly more permissive than first-match, so nothing legal before is illegal now.

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`

Expected: `All checks passed!` and no formatting diffs.

- [ ] **Step 6: Commit**

```bash
git add workitem/conformance
git commit -m "fix(checker): conditional edges sharing a pair must not shadow

The first conditional whose (from, to) matched returned immediately, while
_specs[(frm, to)] = edge kept only the last. First-wins in one place, last-wins in
the other.

This is not theoretical. The delivery-mode fix declares REPORTING -> DONE once per
mode, so the same pair appears twice. Measured against that change with this code
unchanged:

    delivery.mode=pull_request   DONE reachable: True   20/20
    delivery.mode=branch_only    DONE reachable: True    18/20
    delivery.mode=none           DONE reachable: False   15/20   <- unchanged from v1

Under none, check() hit the branch_only edge first and refused, so the fix did not
fix the bug.

check() now scans every conditional for the pair and succeeds if any matches.
edge_specs() returns every variant, so a duplicated pair can never be invisible
again; edge_spec() remains for single-variant callers.
skipped_by_delivery_mode reads skips_states_by_mode per mode instead of comparing
against 'none', and an undeclared mode now skips nothing."
```

---

## Task 2: Per-mode skips and the bypass edges

**Files:**
- Modify: `workitem/state-machine.yaml`
- Modify: `workitem/conformance/tests/test_parameter_space.py` (create)

**Interfaces:**
- Consumes: `TransitionEngine.edge_specs`, `skipped_by_delivery_mode`, `check` (Task 1)
- Produces:
  - `workitem_conformance.contract.parameter_modes(contract) -> list[str]` — declared `delivery_mode.values`
  - `workitem_conformance.contract.parameter_policies(contract) -> list[str]` — declared `review_policy.values`
  - `workitem_conformance.contract.combinations(contract) -> list[tuple[str, str]]` — the cross product

  These are **module-level functions taking a `Contract`**, not `Contract` methods. Import them:
  `from workitem_conformance.contract import combinations, load_contract, parameter_modes, parameter_policies`

---

- [ ] **Step 1: Write the failing test**

Create `workitem/conformance/tests/test_parameter_space.py`:

```python
"""Invariants over the declared parameter space.

Every combination here is read from the contract's own declared `values`. A test
that hardcoded them would be a fourth description of the contract, and a fourth
delivery mode would need a code change to be covered.
"""

from __future__ import annotations

from dataclasses import replace

from workitem_conformance.contract import (
    combinations,
    load_contract,
    parameter_modes,
    parameter_policies,
)
from workitem_conformance.transitions import TransitionEngine, default_context


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


def test_parameter_spaces_are_enumerable_from_the_contract() -> None:
    """Guards every test in this module against becoming a literal."""
    contract = load_contract()
    modes = parameter_modes(contract)
    policies = parameter_policies(contract)
    assert len(modes) == len(set(modes)) and modes
    assert len(policies) == len(set(policies)) and policies
    assert combinations(contract) == [
        (m, p) for m in modes for p in policies
    ]


def test_every_state_is_reachable_under_every_applicable_combination() -> None:
    """I1: every non-skipped state is reachable from DRAFT."""
    contract = load_contract()
    engine = TransitionEngine(contract.state_machine)
    all_states = engine.states()
    for mode, policy in combinations(contract):
        skipped = set(engine.skipped_by_delivery_mode(mode))
        seen = _reachable(contract, mode, policy)
        missing = sorted(all_states - skipped - seen)
        assert not missing, f"{mode}/{policy} cannot reach {missing}"


def test_every_combination_can_reach_done() -> None:
    """I2: the work must be finishable. CANCELLED is abandonment, not completion."""
    contract = load_contract()
    for mode, policy in combinations(contract):
        assert "DONE" in _reachable(contract, mode, policy), f"{mode}/{policy}"


def test_skip_lists_match_the_declared_modes() -> None:
    contract = load_contract()
    by_mode = contract.state_machine["parameters"]["delivery_mode"]["skips_states_by_mode"]
    for mode in parameter_modes(contract):
        assert mode in by_mode, f"{mode} has no skips_states_by_mode entry"
    engine = TransitionEngine(contract.state_machine)
    states = engine.states()
    for mode, skipped in by_mode.items():
        unknown = sorted(set(skipped) - states)
        assert not unknown, f"{mode} skips unknown states {unknown}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest workitem/conformance/tests/test_parameter_space.py -v`

Expected: FAIL — `AttributeError: 'Contract' object has no attribute 'parameter_modes'`

- [ ] **Step 3: Add the parameter accessors**

Append to `workitem/conformance/workitem_conformance/contract.py`:

```python
def parameter_modes(contract: Contract) -> list[str]:
    """Declared delivery_mode values, in declaration order."""
    return list(contract.state_machine["parameters"]["delivery_mode"]["values"])


def parameter_policies(contract: Contract) -> list[str]:
    """Declared review_policy values, in declaration order."""
    return list(contract.policy["review_policy"]["values"])


def combinations(contract: Contract) -> list[tuple[str, str]]:
    """Every (delivery_mode, review_policy) pair the contract declares."""
    return [(m, p) for m in parameter_modes(contract) for p in parameter_policies(contract)]
```

- [ ] **Step 4: Run to confirm the accessors work but the invariants fail**

Run: `.venv/bin/pytest workitem/conformance/tests/test_parameter_space.py -v`

Expected: the enumeration test PASSES; `test_every_combination_can_reach_done` FAILS for `none` with `none/low_risk cannot reach DONE`.

- [ ] **Step 5: Change `skips_states` to `skips_states_by_mode`**

In `workitem/state-machine.yaml`, replace:

```yaml
    # States unreachable when the WorkItem produces no branch or PR.
    skips_states: [COMMITTED, PR_DRAFT, IMPLEMENTATION_COMPLETE, PR_READY]
```

with:

```yaml
    # States unreachable under each mode. Gates in policy.yaml consult the same
    # list through their own `when:` conditions, so the graph and the gates cannot
    # disagree about what a mode means.
    skips_states_by_mode:
      pull_request: []
      branch_only:  [PR_DRAFT, PR_READY]
      none:         [COMMITTED, PR_DRAFT, IMPLEMENTATION_COMPLETE, PR_READY]
```

- [ ] **Step 6: Add the three bypass edges**

In `workitem/state-machine.yaml`, immediately after the existing
`- { from: VALIDATED, to: TESTING, when: { delivery_mode: none } }` line, add:

```yaml
  # Bypass edges. One per mode that skips a state on the route to DONE. Without
  # these, skipping PR_READY removes the only incoming edge of DONE and the
  # WorkItem can never finish.
  - { from: VALIDATED,          to: TESTING,               when: { delivery_mode: none } }
  - { from: COMMITTED,          to: IMPLEMENTATION_COMPLETE, when: { delivery_mode: branch_only } }
  - { from: REPORTING,          to: DONE,                   when: { delivery_mode: branch_only } }
  - { from: REPORTING,          to: DONE,                   when: { delivery_mode: none } }
```

Delete the original `VALIDATED → TESTING` line first — it is replaced, not duplicated.

- [ ] **Step 7: Run the invariant tests**

Run: `.venv/bin/pytest workitem/conformance/tests/test_parameter_space.py -v`

Expected: all four PASS. `test_every_combination_can_reach_done` is the one that was failing.

- [ ] **Step 8: Run the whole suite**

Run: `.venv/bin/pytest workitem/conformance -q`

Expected: PASS. `test_delivery_mode_none_admits_the_short_circuit_edge` must still pass — it enumerates via `edge_spec`, which now returns the first variant, and `REPORTING → DONE` does not interfere with `VALIDATED → TESTING`.

- [ ] **Step 9: Lint, then commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
git add workitem/state-machine.yaml workitem/conformance
git commit -m "fix(contract): every delivery mode can reach DONE

DONE had exactly one incoming edge, from PR_READY, and skips_states marked
PR_READY as skipped under delivery.mode: none. Removing it removed the only door to
DONE, so an investigation or documentation WorkItem could reach REPORTING and then
stop permanently. Measured at v1: 15 of 20 states reachable under none, DONE among
the missing five.

skips_states becomes skips_states_by_mode, and branch_only gains the skips it
never had. Three bypass edges are declared explicitly rather than synthesised, so
every edge stays visible in the contract.

Parameter spaces are now readable through contract.parameter_modes,
parameter_policies and combinations, so the invariant tests enumerate the cross
product from the contract instead of a literal."
```

---

## Task 3: The gate table learns `when`

**Files:**
- Modify: `workitem/policy.yaml`
- Modify: `workitem/conformance/workitem_conformance/gates.py`
- Modify: `workitem/conformance/tests/test_gates.py`

**Interfaces:**
- Consumes: `contract.combinations`, `TransitionEngine` (Tasks 1–2)
- Produces: `gates.check_declared_gates(workitem, policy) -> GateResult` now honours `when`

---

- [ ] **Step 1: Write the failing test**

Append to `workitem/conformance/tests/test_gates.py`:

```python
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
    the field, so this becomes meaningful only once Task 4's constraint lands. It
    guards against future incoherence; it does not demonstrate a present one.
    """
    contract = load_contract()
    engine = TransitionEngine(contract.state_machine)
    forbidden = _forbidden_by_mode(contract)
    for mode, policy in combinations(contract):
        ctx = replace(default_context(), delivery_mode=mode, review_policy=policy)
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
        fields = clause.get("then", {}).get("properties", {}).get("delivery", {}).get("properties", {})
        out[key] = {f"delivery.{name}" for name, spec in fields.items() if spec.get("type") == "null"}
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
```

Add to the imports at the top of `test_gates.py`, keeping isort order — `dataclasses` is stdlib and
must precede the first-party imports:

```python
from dataclasses import replace
```

- [ ] **Step 2: Run to verify the tests fail**

Run: `.venv/bin/pytest workitem/conformance/tests/test_gates.py -v -k "when_is_skipped or only_binds or unsatisfiable"`

Expected: the two `when` tests FAIL — `PR_DRAFT requires delivery.pull_request` still fires under `branch_only`. `unsatisfiable` PASSES: `_forbidden_by_mode` reads an absent `allOf`, so nothing is forbidden yet and there is nothing to violate.

- [ ] **Step 3: Add `when:` to the PR_DRAFT gate**

In `workitem/policy.yaml`, change the `PR_DRAFT` entry to:

```yaml
  - state: PR_DRAFT
    artifact_required: delivery.pull_request
    enforced: true
    predicate: check_declared_gates
    when: { delivery_mode: pull_request }
    note: "branch pushed and a draft PR exists using the repository PR template"
```

- [ ] **Step 4: Teach `check_declared_gates` to honour `when`**

In `workitem/conformance/workitem_conformance/gates.py`, add a helper after `_read`:

```python
def _condition_met(workitem: dict[str, Any], when: dict[str, Any] | None) -> bool:
    """Evaluate a gate's `when` clause against the record.

    Mirrors the state machine's condition syntax so there is one mechanism, not
    two. A gate with no `when` applies unconditionally.
    """
    if not when:
        return True
    if "delivery_mode" in when:
        expected = when["delivery_mode"]
        actual = _read(workitem, "delivery.mode")
        allowed = expected if isinstance(expected, list) else [expected]
        if actual not in allowed:
            return False
    return True
```

Then change the loop head in `check_declared_gates` from:

```python
    for gate in policy.get("gates", []):
        if not gate.get("enforced"):
            continue
```

to:

```python
    for gate in policy.get("gates", []):
        if not gate.get("enforced"):
            continue
        if not _condition_met(workitem, gate.get("when")):
            continue
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest workitem/conformance/tests/test_gates.py -v`

Expected: PASS, including the two that were failing. `test_every_artifact_gate_is_refused_when_the_artifact_is_absent` must still report exactly 5 failures, because `task.yaml` is `pull_request` mode.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/pytest workitem/conformance -q`

Expected: PASS.

- [ ] **Step 7: Declare that review_policy affects gates, not edges**

In `workitem/policy.yaml`, add before `review_policy`:

```yaml
# Declared so the cross-product test can enumerate it, and so the asymmetry
# between the two parameters is a fact in the contract rather than a comment:
# delivery_mode governs edges, review_policy governs gates.
parameters:
  review_policy:
    field: verification.review_policy
    values: [low_risk, normal, security_sensitive, high_risk]
    affects: gates
```

- [ ] **Step 8: Add the guard test and run**

Append to `workitem/conformance/tests/test_parameter_space.py`:

```python
def test_review_policy_declares_that_it_affects_gates_not_edges() -> None:
    """Guards the asymmetry the cross-product test relies on."""
    contract = load_contract()
    declared = contract.policy["parameters"]["review_policy"]
    assert declared["affects"] == "gates"
    assert declared["values"] == parameter_policies(contract)
    # If a review policy ever gained an edge condition, this would need revisiting.
    assert "review_policy" not in str(contract.state_machine["transitions"])
```

Run: `.venv/bin/pytest workitem/conformance -q`

Expected: PASS.

- [ ] **Step 9: Lint, then commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
git add workitem/policy.yaml workitem/conformance
git commit -m "fix(contract): the gate table learns delivery mode

PR_DRAFT's gate demanded delivery.pull_request unconditionally, so under
branch_only -- committed to a branch, never a PR -- the state machine said the path
was legal and the gate said it could never be satisfied. Every state was reachable
and the work still could not be completed. Measured across the 12 declared
combinations, four violated it, all branch_only.

Gates now carry the same when: syntax the state machine already uses, so there is
one mechanism rather than two. check_declared_gates skips a gate whose condition
does not match rather than failing it.

review_policy now declares affects: gates, making the asymmetry between the two
parameters a fact in the contract instead of a comment. It has no edge condition,
which is why the cross-product invariant can treat it as gate-only."
```

---

## Task 4: A record cannot contradict its mode

**Files:**
- Modify: `workitem/v1.schema.json`
- Modify: `workitem/conformance/tests/test_examples.py`
- Test: `workitem/conformance/tests/fixtures/none-with-a-branch.yaml`, `branch-only-with-a-pull-request.yaml`

**Interfaces:**
- Consumes: `_forbidden_by_mode` reading `contract.schema["allOf"]` (Task 3) — this is the constraint I3 depends on

---

- [ ] **Step 1: Create the fixtures**

Create `workitem/conformance/tests/fixtures/none-with-a-branch.yaml` by copying
`workitem/examples/investigation.yaml` and replacing its delivery block with:

```yaml
delivery:
  mode: none
  branch: wi/WI-20261003-0004/some-branch
  pull_request: null
```

Create `workitem/conformance/tests/fixtures/branch-only-with-a-pull-request.yaml` by copying
`workitem/examples/task.yaml` and replacing its delivery block with:

```yaml
delivery:
  mode: branch_only
  branch: wi/WI-20261003-0001/some-branch
  pull_request: 42
```

- [ ] **Step 2: Write the failing test**

Append to `workitem/conformance/tests/test_examples.py`:

```python
@pytest.mark.parametrize(
    "fixture",
    ["branch-only-with-a-pull-request", "none-with-a-branch"],
)
def test_record_cannot_contradict_its_delivery_mode(fixture: str) -> None:
    path = Path(__file__).parent / "fixtures" / f"{fixture}.yaml"
    assert list(_validator().iter_errors(yaml.safe_load(path.read_text()))), (
        f"{fixture} was accepted but contradicts its own delivery.mode"
    )


def test_draft_record_with_a_null_branch_stays_valid() -> None:
    """branch is deliberately unconstrained for pull_request.

    WI-20261003-0005 is a live DRAFT with branch: null. A branch does not exist
    until execution begins, so requiring one would invalidate the only record that
    exists, for a condition unrelated to reachability.
    """
    item = load_example(load_contract().root, "task")
    assert item["delivery"]["branch"] is None
    assert not list(_validator().iter_errors(item))


def test_none_record_may_carry_neither_branch_nor_pull_request() -> None:
    item = load_example(load_contract().root, "investigation")
    assert item["delivery"]["mode"] == "none"
    assert not list(_validator().iter_errors(item))


def test_branch_only_record_with_a_null_pull_request_is_accepted() -> None:
    item = load_example(load_contract().root, "bug")
    item["delivery"] = {"mode": "branch_only", "branch": "wi/WI-20261003-0002/x", "pull_request": None}
    assert not list(_validator().iter_errors(item))


def test_delivery_mode_conditionals_cannot_match_vacuously() -> None:
    """Every `if` keys on delivery.mode, so both must always be present."""
    required = load_contract().schema["required"]
    assert "delivery" in required
    assert "mode" in load_contract().schema["properties"]["delivery"]["required"]
```

- [ ] **Step 3: Run to verify the tests fail**

Run: `.venv/bin/pytest workitem/conformance/tests/test_examples.py -v -k "contradict or null_branch or neither_branch or null_pull_request or vacuously"`

Expected: the two `contradict` cases FAIL — 0 schema errors, because v1 has no `allOf`. The other three PASS.

- [ ] **Step 4: Add the `allOf` constraints**

In `workitem/v1.schema.json`, insert `"allOf": [...]` as a sibling of `"properties"`, immediately before `"$defs"`:

```json
  "allOf": [
    {
      "if": { "properties": { "delivery": { "properties": { "mode": { "const": "none" } } } } },
      "then": { "properties": { "delivery": { "properties": {
        "branch": { "type": "null" },
        "pull_request": { "type": "null" }
      } } } }
    },
    {
      "if": { "properties": { "delivery": { "properties": { "mode": { "const": "branch_only" } } } } },
      "then": { "properties": { "delivery": { "properties": {
        "pull_request": { "type": "null" }
      } } } }
    }
  ],
```

Both `if` clauses omit `required`. That is safe because `delivery` is in the schema's top-level
`required` and `mode` is required within it, so neither can be absent for an `if` to match
vacuously. `test_delivery_mode_conditionals_cannot_match_vacuously` asserts it.

`branch` is left unconstrained for `pull_request` on purpose — see the test in step 2.

- [ ] **Step 5: Run to verify the tests pass**

Run: `.venv/bin/pytest workitem/conformance/tests/test_examples.py -v`

Expected: PASS, including the two that were failing.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/pytest workitem/conformance -q`

Expected: PASS. `test_a_valid_ledger_reports_no_problems` writes `feature.yaml` into a ledger — its delivery is `pull_request`, unconstrained.

- [ ] **Step 7: Verify the live ledger still validates**

Run:

```bash
.venv/bin/python -m workitem_conformance.cli --contract-root . \
  --ledger-root ../workhub/.workhub \
  --pattern '.workhub/workitems/*/workitem.yaml'
```

Expected: `All 1 WorkItem instance(s) valid.` If `workhub` is not checked out alongside, skip and record that in the commit message.

- [ ] **Step 8: Lint, then commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
git add workitem/v1.schema.json workitem/conformance
git commit -m "fix(contract): a record cannot contradict its delivery mode

mode: none is defined as no delivery artifacts at all, and mode: branch_only as
committed to a branch and never a PR. v1.schema.json enforced neither:
branch_only with pull_request: 42 validated with 0 errors, so a WorkItem could
declare a delivery mode and then assert the delivery that mode forbids.

Two allOf clauses close it. This is also what makes invariant I3 decidable -- 'the
mode forbids this field' has to be a machine-checkable fact rather than a comment
-- so it and the gate `when` in policy.yaml must land together.

branch is deliberately left unconstrained for pull_request. WI-20261003-0005 is a
live DRAFT with branch: null, and a branch does not exist until execution begins.
Constraining it would invalidate the only record that exists, for a condition
unrelated to reachability. There is a test pinning that."
```

---

## Task 5: Version the contract, and correct the mapping

**Files:**
- Modify: `workitem/contract-version.yaml`
- Modify: `workitem/conformance/tests/test_provenance.py`

**Interfaces:**
- Consumes: `contract.version` (Task 1)
- Produces: `current: v1.1`; `workitem/v1.1` → `schema_version: "1.0"`

---

- [ ] **Step 1: Write the failing test**

Append to `workitem/conformance/tests/test_provenance.py`:

```python
def test_v1_1_is_a_data_release_and_keeps_schema_version_1_0() -> None:
    """D8: tightening a schema does not bump schema_version.

    Bumping the const would invalidate every existing record and falsify the
    no-migration claim. So records stay "1.0" and the mapping is corrected.
    """
    c = load_contract()
    assert c.version["current"] == "v1.1"
    entry = [v for v in c.version["versions"] if v["tag"] == "workitem/v1.1"]
    assert entry, "v1.1 must be declared"
    assert entry[0]["schema_version"] == "1.0"
    assert entry[0]["released"] is not None


def test_a_contract_data_release_does_not_change_the_schema_version() -> None:
    """The tag and the schema version are different namespaces.

    Guards the reasoning in D8 so a future minor release cannot silently bump the
    schema version and break every record.
    """
    c = load_contract()
    declared = c.schema["properties"]["schema_version"]["const"]
    for entry in c.version["versions"]:
        if entry["tag"] == c.version["current"]:
            continue
        if entry["released"] is None:
            continue
        assert entry["schema_version"] == declared, (
            f"{entry['tag']} is released with schema_version {entry['schema_version']}, "
            f"but v1.schema.json pins {declared}"
        )
```

- [ ] **Step 2: Run to verify the tests fail**

Run: `.venv/bin/pytest workitem/conformance/tests/test_provenance.py -v -k "v1_1 or data_release"`

Expected: FAIL — `current` is `v1`, and `workitem/v1.1` declares `released: null`.

- [ ] **Step 3: Flip the current version and correct the mapping**

In `workitem/contract-version.yaml`, set `current: v1.1` and replace the version list with:

```yaml
current: v1.1

# Contract versions are git tags in harkers/.github. Consumers pin a tag and
# MUST NOT consume an unpinned moving ref.
#
# `schema_version` maps a tag to the record schema it validates. A contract *data*
# release -- one that changes the state machine or policy without adding, removing
# or retyping a field -- keeps the same schema_version. Tightening a constraint is
# such a release. See the design spec's D8.
versions:
  - tag: workitem/v1
    schema_version: "1.0"
    released: "2026-10-03"
    superseded_by: workitem/v1.1
  - tag: workitem/v1.1
    schema_version: "1.0"
    released: "2026-10-03"
    note: >-
      Delivery-mode reachability fix. Adds no field; tightens the schema so a record
      cannot contradict its delivery.mode.
  - tag: workitem/v2
    schema_version: "2.0"
    released: null
```

- [ ] **Step 4: Run to verify the tests pass**

Run: `.venv/bin/pytest workitem/conformance -q`

Expected: PASS. `test_contract_version_matches_the_schema` reads `current`'s mapping and compares it to the const — both `1.0`, so it passes. `test_only_the_current_and_past_versions_are_released` needs `workitem/v2` still unreleased.

- [ ] **Step 5: Lint, then commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
git add workitem/contract-version.yaml workitem/conformance
git commit -m "fix(contract): release workitem/v1.1, correct the version mapping

workitem/v1.1 previously declared schema_version '1.1' while v1.schema.json pins
const '1.0', and test_provenance binds the two. Every option collided: bumping the
const invalidates every record and falsifies the no-migration claim; leaving the
mapping makes it simply wrong; an enum breaks the test that reads ['const'].

v1.1 changes the state machine and the policy and adds no field, so it keeps
schema_version '1.0'. The tag and the schema version are different namespaces and a
data release does not imply a schema change. Two tests pin that reasoning so a
future minor release cannot bump it silently."
```

---

## Task 6: Cut the tags and update the only consumer

**Files:**
- Create: tag `workitem/v1.1` and `workitem-gate/v3` in `harkers/.github`
- Modify (separate repo): `harkers/workhub` `.github/workflows/validate-workitems.yml`

**Interfaces:**
- Consumes: everything from Tasks 1–5
- Produces: two git tags; one consumer PR

---

- [ ] **Step 1: Confirm the suite is green and the tree is clean**

Run:

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest workitem/conformance -q
git status --porcelain
```

Expected: all clean. Do not cut a tag from a dirty tree.

- [ ] **Step 2: Merge the branch**

Push and open a PR against `main` in `harkers/.github`, then squash-merge. Do not push `main` directly.

- [ ] **Step 3: Cut both tags on the merge commit**

Run:

```bash
git fetch origin
git tag -a workitem/v1.1 origin/main -m "WorkItem contract v1.1

Delivery-mode reachability fix. DONE had one incoming edge, from PR_READY, and
PR_READY was skipped under delivery.mode: none -- so an investigation or
documentation WorkItem could never finish. Adds per-mode skip lists, three explicit
bypass edges, a mode-aware gate table, and a schema constraint so a record cannot
contradict its delivery.mode.

Contract data release: adds no field, so schema_version stays 1.0.
"
git tag -a workitem-gate/v3 origin/main -m "WorkItem validation gate v3

The checker now scans every conditional edge sharing a (from, to) pair instead of
returning on the first match, and reads skip lists per mode. Required by v1.1,
which declares two conditionals for one edge pair.
"
git push origin workitem/v1.1 workitem-gate/v3
```

Expected: both tags created. Verify:

```bash
git ls-remote --tags origin | grep -E "v1.1|gate/v3"
```

- [ ] **Step 4: Open the consumer PR**

In `harkers/workhub`, branch from `main`, change
`.github/workflows/validate-workitems.yml` to:

```yaml
    name: Validate Work Items against workitem/v1.1
    uses: harkers/.github/.github/workflows/validate-workitem.yml@workitem-gate/v3
    with:
      contract-ref: workitem/v1.1
      gate-ref: workitem-gate/v3
      contract-repo: harkers/.github
      workitem-glob: .workhub/workitems/*/workitem.yaml
```

The job `name:` must match the context the consumer's branch protection requires. Current
required context on `harkers/workhub` `main`:

```text
Validate Work Items against workitem/v1 / Validate Work Items against workitem/v1
```

**Renaming the job changes the required context, and a mismatch blocks every merge.** Two
options: keep the job name unchanged so the existing required context still matches, or rename it
and update branch protection in the same PR. Prefer the first — change only the refs, not the
name:

```yaml
    name: Validate Work Items against workitem/v1 / Validate Work Items against workitem/v1
    uses: harkers/.github/.github/workflows/validate-workitem.yml@workitem-gate/v3
    with:
      contract-ref: workitem/v1.1
      gate-ref: workitem-gate/v3
      contract-repo: harkers/.github
      workitem-glob: .workhub/workitems/*/workitem.yaml
```

- [ ] **Step 5: Verify the gate runs green before merging**

Run:

```bash
gh api "repos/harkers/workhub/commits/$(gh pr view <n> --json headRefOid -q .headRefOid)/check-runs" \
  -q '.check_runs[] | "\(.name) -> \(.conclusion)"'
```

Expected: `Validate WorkItems against workitem/v1 / Validate WorkItems against workitem/v1 -> success`.
Only merge once it is green — `main` is protected and `strict: true`.

- [ ] **Step 6: Merge, then confirm on `main`**

Run:

```bash
gh pr merge <n> --squash --delete-branch
gh api "repos/harkers/workhub/actions/runs?per_page=1" \
  -q '.workflow_runs[] | "\(.conclusion) \(.head_branch)"'
```

Expected: `success main`.

- [ ] **Step 7: Record the roll-back pair**

Note in the consumer PR body, and in the contract README, that `workitem/v1` +
`workitem-gate/v2` remains a working combination, so a consumer reverts by editing two lines.

---

## Final Verification

Run from `harkers/.github`:

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest workitem/conformance -q
```

Then confirm the invariants hold directly, independent of the test suite:

```bash
.venv/bin/python - <<'PY'
from dataclasses import replace
from pathlib import Path

from workitem_conformance.contract import combinations, load_contract
from workitem_conformance.transitions import TransitionEngine, default_context

c = load_contract(Path("."))
e = TransitionEngine(c.state_machine)
for mode, policy in combinations(c):
    ctx = replace(default_context(), delivery_mode=mode, review_policy=policy)
    seen, fr = {"DRAFT"}, ["DRAFT"]
    while fr:
        cur = fr.pop()
        for nxt in e.outgoing(cur):
            if e.check(cur, nxt, ctx).legal and nxt not in seen:
                seen.add(nxt); fr.append(nxt)
    skipped = set(e.skipped_by_delivery_mode(mode))
    missing = sorted(e.states() - skipped - seen)
    print(f"{mode:14} {policy:20} DONE={'DONE' in seen}  unreachable={missing or 'none'}")
PY
```

Expected: twelve lines, `DONE=True` on every one, `unreachable=none` on every one.

Then confirm `harkers/.github` is merged and both tags exist, and that `harkers/workhub` `main`
is green. Do **not** enable or change branch protection as part of this plan.