# External Dependency Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a WorkItem declare that it is blocked by work in another repository, and refuse `DONE` until that work is discharged by a completed WorkItem in this ledger.

**Architecture:** `dependencies[]` is left untouched and stays internal. A new required top-level `external_dependencies[]` carries `repo`/`number`/`type`/`resolved_by`/`note`. One rule applies to both kinds: a dependency is satisfied only when its target is in state `DONE`. `CANCELLED` satisfies nothing but stays reachable for every record, so nothing is ever trapped. Structural validity (targets resolve, graph is acyclic) is a whole-ledger check; satisfaction is checked per-record against the record's current state.

**Tech Stack:** Python 3.11+, `jsonschema>=4.21,<5.0`, `PyYAML>=6.0,<7.0`, `pytest`. Contract is YAML + JSON Schema; conformance checker is a plain package under `workitem/conformance/`.

**Spec:** `docs/superpowers/specs/2026-10-04-external-dependency-resolution-design.md` — read it before starting. The plan argues from the spec; the spec travels with it.

## Global Constraints

- **`dependencies[].target` pattern is unchanged:** `^WI-[0-9]{8}-[0-9]{4}$`. Never widen it.
- **`external_dependencies` is REQUIRED on every v2 record**, mirroring `dependencies`, which is required at `workitem/v1.schema.json` top-level `required`. A record omitting it is ambiguous — "no external dependencies" versus "not yet migrated".
- **`resolved_by` is REQUIRED and is always a WorkItem id.** There is no `kind`, no `assertion` variant, no free-form reference. Discharge must be traceable to completed work in the same ledger.
- **All five relation types require discharge.** `BLOCKS`, `REQUIRES`, `OPTIONAL`, `QUALITY_GATE`, `REVIEW_GATE`. There is no way to declare an external dependency informational.
- **Satisfaction rule, stated once:** a dependency is satisfied only when its target is in state `DONE`. `CANCELLED` satisfies nothing.
- **Schema filename derives from `schema_version` major.** `schema_version: "1.0"` → `workitem/v1.schema.json`; `"2.0"` → `workitem/v2.schema.json`. Never hardcode a schema filename.
- **`dependencies: []` is valid.** An empty array and an absent key are not interchangeable, because the field is required.
- **This ships as `workitem/v2`, `schema_version: "2.0"`, released.** Adding `resolved_by` adds a field, which D8 excludes from data releases.
- **Rollback pair:** `workitem/v2` + `workitem-gate/v5`; previous `workitem/v1.1` + `workitem-gate/v4`.
- **Do not modify `workitem/v1.schema.json` in this plan.** v2 is a new file. The v1.1 tag's contents must stay reproducible.

## Blocking Preconditions

- **`harkers/.github`#15 must be resolved before Task 7.** This work is a tightening — it adds a gate that will reject records which currently pass. #15 leaves "every live record" in the pre-tag pass undefined (main-only, or every branch carrying a ledger). Tasks 1–6 are safe to build and merge; **Task 7 cuts the tag and must wait.**
- **`harkers/.github`#4's superseded reasoning is corrected in the spec.** Do not reintroduce it. `dag-scheduler` does not exist (#26, aspirational prose). There is no `of_type` field and no `"External"` value. No gate evaluates dependencies today, so no sentinel could self-deadlock.

---

### Task 1: Version-aware schema resolution

`contract.py:57` hardcodes `workitem/v1.schema.json`, so a second schema file cannot be loaded. This is the prerequisite for everything else.

**Files:**
- Modify: `workitem/conformance/workitem_conformance/contract.py:57`
- Test: `workitem/conformance/tests/test_contract_version_resolution.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `contract._schema_filename(version: dict[str, Any]) -> str` (module-private), used by `load_contract`. Every later task loads the contract and depends on this.

- [ ] **Step 1: Write the failing test**

Create `workitem/conformance/tests/test_contract_version_resolution.py`:

```python
import pytest

from workitem_conformance.contract import _schema_filename


def test_data_release_keeps_the_same_schema_file():
    version = {
        "current": "v1.1",
        "versions": [{"tag": "workitem/v1.1", "schema_version": "1.0"}],
    }
    assert _schema_filename(version) == "workitem/v1.schema.json"


def test_major_bump_resolves_the_new_schema_file():
    version = {
        "current": "v2",
        "versions": [{"tag": "workitem/v2", "schema_version": "2.0"}],
    }
    assert _schema_filename(version) == "workitem/v2.schema.json"


def test_current_must_name_a_declared_version():
    version = {
        "current": "v9",
        "versions": [{"tag": "workitem/v2", "schema_version": "2.0"}],
    }
    with pytest.raises(LookupError):
        _schema_filename(version)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest tests/test_contract_version_resolution.py -q`

Expected: collection error — `ImportError: cannot import name '_schema_filename'`.

- [ ] **Step 3: Write minimal implementation**

In `workitem/conformance/workitem_conformance/contract.py`, add above `load_contract`:

```python
def _schema_filename(version: dict[str, Any]) -> str:
    """Resolve the schema file from the current version's declared schema_version.

    The filename tracks the schema major, not the tag: a data release (v1.1) keeps
    schema_version 1.0 and therefore keeps v1.schema.json, while a field-adding
    release (v2) moves to v2.schema.json. Hardcoding a filename here would make a
    second schema unloadable.
    """
    current = version["current"]
    entry = next(v for v in version["versions"] if v["tag"] == current)
    major = str(entry["schema_version"]).split(".")[0]
    return f"workitem/v{major}.schema.json"
```

Change line 57 from:

```python
        schema=_read_json(base, "workitem/v1.schema.json"),
```

to read the version manifest first and resolve through the helper:

```python
    version = _read_yaml(base, "workitem/contract-version.yaml")
    return Contract(
        schema=_read_json(base, _schema_filename(version)),
        ...
        version=version,
    )
```

Reorder so `version` is read before `schema` is constructed. Preserve every other field of the returned `Contract` exactly.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest tests/test_contract_version_resolution.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Run the whole suite to confirm no regression**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest -q`

Expected: `133 passed` (130 existing + 3 new). If the count differs, a pre-existing test broke — fix before continuing.

- [ ] **Step 6: Commit**

```bash
git add workitem/conformance/workitem_conformance/contract.py \
        workitem/conformance/tests/test_contract_version_resolution.py
git commit -m "feat(contract): resolve the schema file from schema_version

load_contract hardcoded workitem/v1.schema.json, so a second schema file could
never be loaded and any schema addition would silently validate against v1.

The filename now tracks the schema major. A data release (v1.1, schema_version
1.0) keeps v1.schema.json; a field-adding release (v2, 2.0) gets v2.schema.json."
```

---

### Task 2: The v2 schema

**Files:**
- Create: `workitem/v2.schema.json`
- Test: `workitem/conformance/tests/test_v2_schema.py`

**Interfaces:**
- Consumes: `_schema_filename` from Task 1.
- Produces: `workitem/v2.schema.json`, a complete standalone schema. Tasks 3–6 read `external_dependencies` off records validated by it.

- [ ] **Step 1: Write the failing test**

Create `workitem/conformance/tests/test_v2_schema.py`:

```python
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = json.loads((ROOT / "workitem" / "v2.schema.json").read_text())


def base_record(**overrides):
    record = {
        "schema": "workitem",
        "schema_version": "2.0",
        "id": "WI-20261004-0001",
        "dependencies": [],
        "external_dependencies": [],
    }
    record.update(overrides)
    return record


def test_external_dependencies_is_required():
    record = base_record()
    del record["external_dependencies"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(record, SCHEMA)


def test_external_dependencies_may_be_empty():
    jsonschema.validate(base_record(), SCHEMA)


def test_minimal_external_dependency_validates():
    jsonschema.validate(
        base_record(
            external_dependencies=[
                {
                    "repo": "harkers/workhub",
                    "number": 64,
                    "type": "REQUIRES",
                    "resolved_by": "WI-20261004-0002",
                    "note": "landed in harkers/workhub#65",
                }
            ]
        ),
        SCHEMA,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("repo", "no-slash"),
        ("number", 0),
        ("type", "DEPENDS_ON"),
        ("resolved_by", "harkers/workhub#64"),
        ("resolved_by", "not-an-id"),
        ("note", ""),
    ],
)
def test_malformed_external_dependency_is_rejected(field, value):
    dep = {
        "repo": "harkers/workhub",
        "number": 64,
        "type": "REQUIRES",
        "resolved_by": "WI-20261004-0002",
        "note": "landed in harkers/workhub#65",
    }
    dep[field] = value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            base_record(external_dependencies=[dep]), SCHEMA
        )


def test_every_member_of_the_dependency_enum_is_accepted():
    for rel in ("BLOCKS", "REQUIRES", "OPTIONAL", "QUALITY_GATE", "REVIEW_GATE"):
        jsonschema.validate(
            base_record(
                external_dependencies=[
                    {
                        "repo": "harkers/workhub",
                        "number": 1,
                        "type": rel,
                        "resolved_by": "WI-20261004-0002",
                        "note": "x",
                    }
                ]
            ),
            SCHEMA,
        )


def test_internal_target_pattern_is_unchanged():
    deps = SCHEMA["properties"]["dependencies"]["items"]["properties"]["target"]
    assert deps["pattern"] == "^WI-[0-9]{8}-[0-9]{4}$"


def test_v2_carries_the_v1_delivery_constraints():
    """v2 supersedes v1.1, so it must keep the delivery-mode allOf constraints."""
    assert "allOf" in SCHEMA["properties"]["delivery"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest tests/test_v2_schema.py -q`

Expected: `FileNotFoundError` on `workitem/v2.schema.json`.

- [ ] **Step 3: Write the schema**

```bash
cp workitem/v1.schema.json workitem/v2.schema.json
```

Then edit `workitem/v2.schema.json`:

1. Set the `schema_version` const to `"2.0"`.
2. Add to top-level `required`, immediately after `"dependencies"`:
   ```json
   "external_dependencies",
   ```
3. Add to top-level `properties`, immediately after `dependencies`:
   ```json
   "external_dependencies": {
     "type": "array",
     "description": "Work this item is blocked by, living in another repository. Never resolvable by the contract; discharged only by a completed WorkItem in this ledger.",
     "items": {
       "type": "object",
       "additionalProperties": false,
       "required": ["repo", "number", "type", "resolved_by", "note"],
       "properties": {
         "repo": {
           "type": "string",
           "pattern": "^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",
           "description": "owner/repo. A cross-repo reference needs a canonical form; the four spellings the v1 tests rejected stay rejected."
         },
         "number": {
           "type": "integer",
           "minimum": 1,
           "description": "Issue or pull request number. The two share a GitHub number space, so this field is ambiguous by nature; disambiguating it is the author's job."
         },
         "type": {
           "enum": ["BLOCKS", "REQUIRES", "OPTIONAL", "QUALITY_GATE", "REVIEW_GATE"],
           "description": "Same relation kinds as dependencies[].type. All five require discharge; none is informational."
         },
         "resolved_by": {
           "type": "string",
           "pattern": "^WI-[0-9]{8}-[0-9]{4}$",
           "description": "A WorkItem in this ledger that is itself DONE. There is no assertion variant: discharge must be traceable to completed work."
         },
         "note": {
           "type": "string",
           "minLength": 1,
           "description": "Why this WorkItem discharges the external reference."
         }
       }
     }
   }
   ```

Change nothing else. `dependencies`, `state`, `verification`, `acceptance_criteria` and every delivery-mode `allOf` constraint are copied verbatim.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest tests/test_v2_schema.py -q`

Expected: `12 passed`.

- [ ] **Step 5: Run the whole suite**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest -q`

Expected: `145 passed` (130 + 3 from Task 1 + 12 here). `test_examples.py` must still pass: `current` is `v1.1` at this point, so the checker still loads `v1.schema.json` and the 1.0-shaped examples are validated against v1. Do **not** widen v2 or edit the examples to make this pass — Task 7 migrates them once `current` flips.

- [ ] **Step 6: Commit**

```bash
git add workitem/v2.schema.json workitem/conformance/tests/test_v2_schema.py
git commit -m "feat(contract): v2 schema with required external_dependencies

Adds a top-level external_dependencies[] carrying repo, number, type, resolved_by
and note. dependencies[] is untouched and its target pattern is unchanged.

external_dependencies is required, mirroring dependencies, because 'no external
dependencies' and 'not yet migrated' must not share a representation.
resolved_by is a WorkItem id with no assertion variant, so discharge is always
traceable to completed work in this ledger."
```

---

### Task 3: Structural dependency checks in the ledger

`instances.py` already resolves targets and detects missing ones. This adds cycle detection and `resolved_by` resolution. Enforcement of *satisfaction* is Task 4.

**Files:**
- Modify: `workitem/conformance/workitem_conformance/instances.py:147-154`
- Test: `workitem/conformance/tests/test_dependency_structure.py`

**Interfaces:**
- Consumes: `external_dependencies` from Task 2's schema.
- Produces: `instances.find_cycles(dep_map: dict[str, list[str]]) -> list[list[str]]`, and two new problem codes `dependency-cycle` and `unresolved-external-discharge`. Task 4 calls `find_cycles` to prove satisfaction is satisfiable.

- [ ] **Step 1: Write the failing tests**

Create `workitem/conformance/tests/test_dependency_structure.py`:

```python
import pytest

from workitem_conformance.instances import find_cycles


def dep_map(*edges):
    return dict(edges)


def test_empty_graph_has_no_cycles():
    assert find_cycles({"a": [], "b": []}) == []


def test_dag_has_no_cycles():
    assert find_cycles({"a": ["b"], "b": ["c"], "c": []}) == []


def test_self_loop_is_a_cycle():
    assert find_cycles({"a": ["a"]}) == [["a", "a"]]


def test_two_node_cycle_is_detected():
    cycles = find_cycles({"a": ["b"], "b": ["a"]})
    assert len(cycles) == 1
    assert set(cycles[0][:2]) == {"a", "b"}


def test_long_cycle_is_detected():
    cycles = find_cycles(
        {"a": ["b"], "b": ["c"], "c": ["d"], "d": ["a"]}
    )
    assert len(cycles) == 1


def test_edges_to_unknown_nodes_are_ignored_by_the_cycle_check():
    """Unresolved targets are a separate problem code; the cycle walk must not
    crash on them, because a dangling edge is not a cycle."""
    assert find_cycles({"a": ["ghost"], "b": []}) == []


def test_deep_chain_does_not_recurse_to_death():
    graph = {f"n{i}": [f"n{i + 1}"] for i in range(5000)}
    graph["n5000"] = []
    assert find_cycles(graph) == []


def test_deep_chain_with_a_back_edge_terminates():
    graph = {f"n{i}": [f"n{i + 1}"] for i in range(5000)}
    graph["n5000"] = ["n0"]
    assert len(find_cycles(graph)) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest tests/test_dependency_structure.py -q`

Expected: `ImportError: cannot import name 'find_cycles'`.

- [ ] **Step 3: Write minimal implementation**

Add to `workitem/conformance/workitem_conformance/instances.py`, below the `EXTERNAL_REF` definition at line 28:

```python
def find_cycles(dep_map: dict[str, list[str]]) -> list[list[str]]:
    """Return every cycle in the dependency graph, each as a node list.

    Iterative rather than recursive: a 5000-deep chain is realistic once a ledger
    grows, and recursion would exhaust the stack on a graph that is merely deep.

    Edges to nodes outside dep_map are ignored here. A dangling target is a
    separate problem code (unresolved-dependency), and treating it as a cycle
    would report one defect twice under two codes.
    """
    UNVISITED, ON_PATH, DONE = 0, 1, 2
    marks = dict.fromkeys(dep_map, UNVISITED)
    cycles: list[list[str]] = []
    seen_signatures: set[frozenset[str]] = set()

    for root in dep_map:
        if marks[root] != UNVISITED:
            continue
        path: list[str] = []
        on_path_index: dict[str, int] = {}
        stack = [(root, iter(dep_map[root]))]
        marks[root] = ON_PATH
        on_path_index[root] = 0
        path.append(root)

        while stack:
            node, children = stack[-1]
            advanced = False
            for child in children:
                if child not in dep_map:
                    continue
                if marks[child] == ON_PATH:
                    cycle = path[on_path_index[child]:] + [child]
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest tests/test_dependency_structure.py -q`

Expected: `8 passed`.

- [ ] **Step 5: Add the two ledger checks**

In `check_ledger`, alongside the existing unresolved-target loop, add resolution of `resolved_by` and cycle detection. Build the map from **both** kinds of dependency, because a cycle can pass through an external edge's discharge:

```python
    dep_map: dict[str, list[str]] = {}
    for item in records:
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

    for cycle in find_cycles(dep_map):
        problems.append(
            InstanceProblem(
                None,
                "dependency-cycle",
                f"dependency cycle: {' -> '.join(cycle)}",
            )
        )
```

Add the `resolved_by` resolution check beside the existing `unresolved-dependency` loop at `instances.py:147-154`:

```python
        for edge in item.get("external_dependencies") or []:
            discharge = edge.get("resolved_by")
            if isinstance(discharge, str) and discharge not in known:
                problems.append(
                    InstanceProblem(
                        edge,
                        "unresolved-external-discharge",
                        f"resolved_by {discharge!r} is not a WorkItem id in this "
                        "ledger. Discharge must name real completed work here.",
                    )
                )
```

- [ ] **Step 6: Write the ledger-level tests**

Append to `workitem/conformance/tests/test_dependency_structure.py`:

```python
from workitem_conformance.instances import check_ledger


def codes_for(records):
    return sorted({p.code for p in check_ledger(records)})


def test_resolved_by_must_name_a_record_in_the_ledger():
    record = {
        "id": "WI-20261004-0001",
        "dependencies": [],
        "external_dependencies": [
            {
                "repo": "harkers/workhub",
                "number": 64,
                "type": "REQUIRES",
                "resolved_by": "WI-20261004-9999",
                "note": "x",
            }
        ],
    }
    assert "unresolved-external-discharge" in codes_for([record])


def test_a_cycle_through_external_discharge_is_detected():
    a = {
        "id": "WI-20261004-0001",
        "dependencies": [],
        "external_dependencies": [
            {
                "repo": "harkers/workhub",
                "number": 1,
                "type": "REQUIRES",
                "resolved_by": "WI-20261004-0002",
                "note": "x",
            }
        ],
    }
    b = {"id": "WI-20261004-0002", "dependencies": ["WI-20261004-0001"], "external_dependencies": []}
    assert "dependency-cycle" in codes_for([a, b])
```

- [ ] **Step 7: Run the tests**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest tests/test_dependency_structure.py -q`

Expected: `10 passed`.

- [ ] **Step 8: Run the whole suite**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest -q`

Expected: `155 passed` (145 + 10 here).

- [ ] **Step 9: Commit**

```bash
git add workitem/conformance/workitem_conformance/instances.py \
        workitem/conformance/tests/test_dependency_structure.py
git commit -m "feat(conformance): cycle detection and external discharge resolution

find_cycles is iterative: a 5000-deep chain is realistic once a ledger grows and
recursion would exhaust the stack on a graph that is merely deep.

The cycle map spans both dependency kinds, because a cycle can pass through an
external edge's discharge -- checking only dependencies[] would miss it.

Discharge must name a record in the same ledger, so an assertion-style reference
fails loudly rather than discharging nothing."
```

---

### Task 4: Satisfaction at `DONE`

**Design decision, recorded so it is not relitigated:** this goes in `check_ledger`, not in `policy.yaml`'s `required_before`. `gates.py:check_before(workitem, policy, state)` receives a single record and has no ledger, and `TransitionEngine` is constructed with the state machine alone (`cli.py:38`). Threading the ledger in would change the signature of `check_before`, its caller in `transitions.py`, and `TransitionEngine.__init__`. Satisfaction *is* a whole-ledger property — it depends on other records' current states — so `check_ledger` is the honest home. The rejected alternative is a `required_before.DONE` rule key plus a `ledger` parameter threaded through both call sites.

**Files:**
- Modify: `workitem/conformance/workitem_conformance/instances.py`
- Test: `workitem/conformance/tests/test_dependency_satisfaction.py`

**Interfaces:**
- Consumes: `find_cycles` and the `dep_map` construction from Task 3.
- Produces: problem code `dependency-not-satisfied`. Task 5's invariant tests assert it never fires on a satisfiable ledger.

- [ ] **Step 1: Write the failing tests**

Create `workitem/conformance/tests/test_dependency_satisfaction.py`:

```python
from workitem_conformance.instances import check_ledger


def codes_for(records):
    return sorted({p.code for p in check_ledger(records)})


def rec(wid, state, deps=None, ext=None):
    return {
        "id": wid,
        "state": state,
        "dependencies": [{"target": t, "type": "REQUIRES"} for t in (deps or [])],
        "external_dependencies": ext or [],
    }


def test_done_with_all_dependencies_done_is_clean():
    records = [rec("WI-20261004-0001", "DONE", ["WI-20261004-0002"]), rec("WI-20261004-0002", "DONE")]
    assert "dependency-not-satisfied" not in codes_for(records)


def test_done_with_an_unfinished_dependency_is_refused():
    records = [rec("WI-20261004-0001", "DONE", ["WI-20261004-0002"]), rec("WI-20261004-0002", "DRAFT")]
    assert "dependency-not-satisfied" in codes_for(records)


def test_cancelled_dependency_does_not_satisfy():
    records = [rec("WI-20261004-0001", "DONE", ["WI-20261004-0002"]), rec("WI-20261004-0002", "CANCELLED")]
    assert "dependency-not-satisfied" in codes_for(records)


def test_cancelled_is_always_available_as_an_exit():
    """Nothing may be trapped: a record whose dependency was cancelled can always
    itself be cancelled."""
    records = [rec("WI-20261004-0001", "DONE", ["WI-20261004-0002"]), rec("WI-20261004-0002", "CANCELLED")]
    assert "dependency-not-satisfied" in codes_for(records)
    assert rec("WI-20261004-0001", "CANCELLED", ["WI-20261004-0002"])["state"] == "CANCELLED"


def test_unfinished_dependencies_are_fine_while_not_done():
    records = [rec("WI-20261004-0001", "DRAFT", ["WI-20261004-0002"]), rec("WI-20261004-0002", "DRAFT")]
    assert "dependency-not-satisfied" not in codes_for(records)


def test_external_discharge_must_itself_be_done():
    ext = [
        {
            "repo": "harkers/workhub",
            "number": 64,
            "type": "REQUIRES",
            "resolved_by": "WI-20261004-0002",
            "note": "x",
        }
    ]
    records = [rec("WI-20261004-0001", "DONE", ext=ext), rec("WI-20261004-0002", "REVIEWING")]
    assert "dependency-not-satisfied" in codes_for(records)


def test_external_discharge_that_is_done_is_clean():
    ext = [
        {
            "repo": "harkers/workhub",
            "number": 64,
            "type": "REQUIRES",
            "resolved_by": "WI-20261004-0002",
            "note": "x",
        }
    ]
    records = [rec("WI-20261004-0001", "DONE", ext=ext), rec("WI-20261004-0002", "DONE")]
    assert "dependency-not-satisfied" not in codes_for(records)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest tests/test_dependency_satisfaction.py -q`

Expected: `4 failed, 3 passed`. The three that pass are the ones asserting absence.

- [ ] **Step 3: Write minimal implementation**

In `check_ledger`, after `dep_map` is built and `known` is available, add:

```python
    states = {
        item.get("id"): item.get("state")
        for item in records
        if isinstance(item.get("id"), str)
    }

    def unmet_targets(item: dict[str, Any]) -> list[str]:
        internal = [
            edge.get("target")
            for edge in item.get("dependencies") or []
            if states.get(edge.get("target")) != "DONE"
        ]
        external = [
            edge.get("resolved_by")
            for edge in item.get("external_dependencies") or []
            if states.get(edge.get("resolved_by")) != "DONE"
        ]
        return [t for t in internal + external if isinstance(t, str)]

    for item in records:
        if item.get("state") != "DONE":
            continue
        for target in unmet_targets(item):
            problems.append(
                InstanceProblem(
                    None,
                    "dependency-not-satisfied",
                    f"state is DONE but {target!r} is "
                    f"{states.get(target, 'absent from the ledger')!r}. "
                    "Only DONE satisfies a dependency; CANCELLED does not.",
                )
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest tests/test_dependency_satisfaction.py -q`

Expected: `7 passed`.

- [ ] **Step 5: Document the rule on the `DONE` gate**

Add to the `DONE` entry in `workitem/policy.yaml`, alongside the existing `note`:

```yaml
    note: >-
      see required_before.DONE. Dependency satisfaction is NOT a required_before
      rule: check_before receives a single record and cannot see the ledger.
      A dependency is satisfied only by DONE, and is enforced by the whole-ledger
      check in the conformance checker (problem code dependency-not-satisfied).
```

Do not add a `required_before` key. Adding one that `check_before` cannot evaluate would make the gate table claim enforcement that does not happen.

- [ ] **Step 6: Run the whole suite**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest -q`

Expected: `162 passed` (155 + 7 here).

- [ ] **Step 7: Commit**

```bash
git add workitem/conformance/workitem_conformance/instances.py \
        workitem/conformance/tests/test_dependency_satisfaction.py \
        workitem/policy.yaml
git commit -m "feat(conformance): a dependency is satisfied only by DONE

CANCELLED deliberately does not satisfy. If it did, cancelling one WorkItem would
silently release everything downstream -- and harkers/workhub's WI-20261003-0001
requires 11 others, so a single cancellation would collapse the graph.

Not being able to reach DONE is not a trap: CANCELLED stays reachable for every
record unconditionally, so nothing is stuck. The invariant is that at least one
terminal state is reachable, and DONE is reachable iff every dependency is DONE.

Enforced in check_ledger rather than policy.required_before, because
check_before receives one record and cannot see the ledger. The DONE gate note
records where the rule actually lives."
```

---

### Task 5: Reachability invariants over ledger configurations

This is the regression guard. #8's I2 checked `DONE` reachability across the `(delivery_mode, review_policy)` cross product — contract *parameters*. Dependencies are not a parameter; they are ledger data. So the invariant must enumerate **ledgers**.

**Files:**
- Create: `workitem/conformance/tests/test_dependency_reachability.py`
- Modify: `workitem/conformance/workitem_conformance/instances.py` only if a test exposes a defect

**Interfaces:**
- Consumes: `check_ledger`, `find_cycles` from Tasks 3–4.
- Produces: no new production code unless a test fails. If one does, fix the production code in this task.

- [ ] **Step 1: Write the tests**

Create `workitem/conformance/tests/test_dependency_reachability.py`:

```python
import itertools

import pytest

from workitem_conformance.instances import check_ledger, find_cycles

TERMINAL = {"DONE", "CANCELLED"}


def rec(wid, state, deps=None, ext=None):
    return {
        "id": wid,
        "state": state,
        "dependencies": [{"target": t, "type": "REQUIRES"} for t in (deps or [])],
        "external_dependencies": ext or [],
    }


def external(wid, discharge):
    return [
        {
            "repo": "harkers/workhub",
            "number": 1,
            "type": "REQUIRES",
            "resolved_by": discharge,
            "note": "x",
        }
    ]


def dep_map(records):
    out = {}
    for r in records:
        out[r["id"]] = [e["target"] for e in r["dependencies"]] + [
            e["resolved_by"] for e in r["external_dependencies"]
        ]
    return out


def can_reach_a_terminal(records, wid):
    """Every record can always be cancelled, so this holds for any acyclic graph."""
    graph = dep_map(records)
    seen, frontier = {wid}, [wid]
    while frontier:
        node = frontier.pop()
        if records_by_id(records)[node] in TERMINAL:
            return True
        for nxt in graph.get(node, []):
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    return False


def records_by_id(records):
    return {r["id"]: r["state"] for r in records}


SHAPES = {
    "empty": [],
    "single": [("WI-20261004-0001", [])],
    "chain": [("WI-20261004-0001", ["WI-20261004-0002"]), ("WI-20261004-0002", [])],
    "wide_fan_in": [
        ("WI-20261004-0001", [f"WI-20261004-{i:04d}" for i in range(2, 13)]),
        *[("WI-20261004-0002", [])],
    ],
    "diamond": [
        ("WI-20261004-0001", ["WI-20261004-0002", "WI-20261004-0003"]),
        ("WI-20261004-0002", ["WI-20261004-0004"]),
        ("WI-20261004-0003", ["WI-20261004-0004"]),
        ("WI-20261004-0004", []),
    ],
}


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_every_acyclic_shape_can_reach_a_terminal(name):
    shape = SHAPES[name]
    records = [rec(wid, "DRAFT", deps) for wid, deps in shape]
    assert not find_cycles(dep_map(records))
    for wid, _ in shape:
        assert can_reach_a_terminal(records, wid)


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_done_is_reachable_iff_every_dependency_is_done(name):
    """Settle every leaf first, then each record in turn. DONE must become legal
    exactly when its dependencies are DONE -- never before."""
    shape = SHAPES[name]
    by_id = records_by_id([rec(wid, "DRAFT", deps) for wid, deps in shape])
    progress = True
    while progress:
        progress = False
        for wid, deps in shape:
            if by_id[wid] == "DONE":
                continue
            if all(by_id[d] == "DONE" for d in deps):
                by_id[wid] = "DONE"
                progress = True
    records = [rec(wid, by_id[wid], deps) for wid, deps in shape]
    assert "dependency-not-satisfied" not in {p.code for p in check_ledger(records)}
    if shape:
        assert all(state == "DONE" for state in by_id.values())


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_cancelling_a_dependency_never_releases_its_dependents(name):
    shape = SHAPES[name]
    records = [rec(wid, "DONE", deps) for wid, deps in shape]
    records = [
        r if r["id"] != shape[-1][0] else dict(r, state="CANCELLED") for r in records
    ]
    assert "dependency-not-satisfied" in {p.code for p in check_ledger(records)}


def test_a_cycle_is_reported_rather_than_silently_satisfied():
    records = [
        rec("WI-20261004-0001", "DONE", ["WI-20261004-0002"]),
        rec("WI-20261004-0002", "DONE", ["WI-20261004-0001"]),
    ]
    codes = {p.code for p in check_ledger(records)}
    assert "dependency-cycle" in codes


def test_external_discharge_chain_terminates():
    records = [
        rec("WI-20261004-0001", "DONE", ext=external("WI-20261004-0001", "WI-20261004-0002")),
        rec("WI-20261004-0002", "DONE", ext=external("WI-20261004-0002", "WI-20261004-0003")),
        rec("WI-20261004-0003", "DONE"),
    ]
    assert "dependency-not-satisfied" not in {p.code for p in check_ledger(records)}


def test_unterminated_external_chain_blocks_done():
    records = [
        rec("WI-20261004-0001", "DONE", ext=external("WI-20261004-0001", "WI-20261004-0002")),
        rec("WI-20261004-0002", "DONE", ext=external("WI-20261004-0002", "WI-20261004-0003")),
        rec("WI-20261004-0003", "DRAFT"),
    ]
    assert "dependency-not-satisfied" in {p.code for p in check_ledger(records)}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest tests/test_dependency_reachability.py -q`

Expected: failures naming the specific invariant. Fix production code until green — **do not** weaken an assertion to make a test pass. If an assertion cannot hold, that is a real defect in Tasks 3–4 and it belongs in the fix.

- [ ] **Step 3: Run the whole suite**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest -q`

Expected: `180 passed` (162 + 18 here).

- [ ] **Step 4: Commit**

```bash
git add workitem/conformance/tests/test_dependency_reachability.py \
        workitem/conformance/workitem_conformance/instances.py
git commit -m "test(conformance): ledger-shaped reachability invariants

#8's I2 enumerated the (delivery_mode, review_policy) cross product, which are
contract parameters. Dependencies are not a parameter -- they are ledger data --
so I2' enumerates ledger shapes instead.

wide_fan_in mirrors harkers/workhub's WI-20261003-0001, which requires 11 of the
13 other records. One unsatisfied leaf there holds most of a real ledger."
```

---

### Task 6: The v1 → v2 migration

`external_dependencies` is required, so every v1 record fails v2 validation until the key is added. `dependencies` is required today and all 14 live records carry it (including `dependencies: []`), so the transform is mechanical and mirrors an existing pattern.

**Files:**
- Create: `workitem/migrations/v1-to-v2.yaml`
- Test: extend `workitem/conformance/tests/test_migrations.py`

**Interfaces:**
- Consumes: the migration format from `workitem/migrations/v0.9-to-v1.yaml`.
- Produces: `workitem/migrations/v1-to-v2.yaml`. Task 7's release note names it.

- [ ] **Step 1: Write the failing test**

Append to `workitem/conformance/tests/test_migrations.py`:

```python
def test_v1_to_v2_migration_exists_and_adds_the_required_key():
    import yaml

    path = ROOT / "workitem" / "migrations" / "v1-to-v2.yaml"
    assert path.exists(), "v1 -> v2 migration is required; external_dependencies is a required field"
    migration = yaml.safe_load(path.read_text())

    assert migration["schema"] == "workitem-migration"
    assert migration["from"] == "1.0"
    assert migration["to"] == "2.0"

    steps = {s["id"]: s for s in migration["steps"]}
    assert "add-external-dependencies" in steps
    step = steps["add-external-dependencies"]
    assert step["transform"] == "set_default"
    assert step["target"] == "external_dependencies"
    assert step["value"] == []
    assert step["when_absent"] is True


def test_no_v1_to_v2_step_guesses_a_value():
    """A defaulted field must be an empty list. Defaulting anything else would
    invent dependency data the record never carried."""
    import yaml

    migration = yaml.safe_load(
        (ROOT / "workitem" / "migrations" / "v1-to-v2.yaml").read_text()
    )
    for step in migration["steps"]:
        assert step["transform"] == "set_default", f"{step['id']} is not a set_default"
        assert step["value"] == [], f"{step['id']} defaults to something other than []"
        assert step.get("when_absent") is True, f"{step['id']} would overwrite existing data"
```

Adjust the `ROOT` import to match whatever that module already uses — read it before editing.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest tests/test_migrations.py -q`

Expected: the two new tests fail on `assert path.exists()`.

- [ ] **Step 3: Write the migration**

Create `workitem/migrations/v1-to-v2.yaml`:

```yaml
schema: workitem-migration
from: "1.0"
to: "2.0"
id: 2026-10-04-adopt-external-dependencies
description: >-
  Contract v2 adds a required top-level external_dependencies[] so a WorkItem can
  declare that it is blocked by work in another repository. v1 could not express
  this at all: dependencies[].target was pattern-locked to a WorkItem id and the
  loader rejected anything else.

  The migration adds the key as an empty list on every record. That is the only
  step, and it is deliberately the ONLY safe one: v1 records cannot carry external
  dependencies, because v1 rejected them. So there is nothing to convert, infer or
  guess. Any non-empty value invented here would be fabricating dependency data.

  No field is dropped, renamed or retyped. dependencies[] is untouched.

steps:
  - id: add-external-dependencies
    target: external_dependencies
    transform: set_default
    value: []
    when_absent: true
    note: >-
      v1 records carry no external dependencies because v1 could not express one.
      An empty list is therefore the complete, faithful representation of a v1
      record under v2 -- not a placeholder.

# Records this migration has been applied to, for audit. Not consumed by the
# migration engine.
applied_to: []
```

Leave `applied_to` empty. Populating it is a rollout step (Task 7), and inventing ids here would claim work that has not happened.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest tests/test_migrations.py -q`

Expected: all pass.

- [ ] **Step 5: Apply it to the live ledger and prove the result**

```bash
cd /Users/stu/projects/workhub
python3 - <<'PY'
import yaml, glob
for path in sorted(glob.glob(".workhub/workitems/*/workitem.yaml")):
    with open(path) as fh:
        raw = fh.read()
    if "external_dependencies:" not in raw:
        with open(path, "w") as fh:
            fh.write(raw.rstrip("\n") + "\nexternal_dependencies: []\n")
        print("migrated", path)
PY
```

Then validate every migrated record against the v2 schema:

```bash
cd /Users/stu/projects/.github
PYTHONPATH=workitem/conformance python3 - <<'PY'
import json, yaml, glob, jsonschema
schema = json.load(open("workitem/v2.schema.json"))
bad = 0
for path in sorted(glob.glob("/Users/stu/projects/workhub/.workhub/workitems/*/workitem.yaml")):
    record = yaml.safe_load(open(path))
    record["schema_version"] = "2.0"
    try:
        jsonschema.validate(record, schema)
    except jsonschema.ValidationError as exc:
        bad += 1
        print("FAIL", path, exc.message[:120])
print(f"validated {len(glob.glob('/Users/stu/projects/workhub/.workhub/workitems/*/workitem.yaml'))} records, {bad} failures")
PY
```

Expected: `0 failures`. If any record fails, **stop** — that is exactly the case #15 exists for, and it must be resolved before Task 7.

Commit the migration on its own branch in `harkers/workhub`; do not merge it until Task 7.

- [ ] **Step 6: Commit the migration definition**

```bash
git add workitem/migrations/v1-to-v2.yaml \
        workitem/conformance/tests/test_migrations.py
git commit -m "feat(contract): v1 to v2 migration

One step: add external_dependencies as an empty list. It is the only safe step,
because v1 records cannot carry external dependencies -- v1 rejected them -- so
there is nothing to convert, infer or guess. Any non-empty value would be
fabricating dependency data the record never had."
```

---

### Task 7: Release v2 and roll out

**Blocked until `harkers/.github`#15 is resolved.** See Blocking Preconditions.

**Files:**
- Modify: `workitem/contract-version.yaml`
- Modify: `workitem/README.md`
- Create: `workitem/conformance/tests/test_release_v2.py`

**Interfaces:**
- Consumes: everything above.
- Produces: tag `workitem/v2`, tag `workitem-gate/v5`, updated rollback pair in `workitem/README.md`.

- [ ] **Step 1: Write the release-manifest test**

Create `workitem/conformance/tests/test_release_v2.py`:

```python
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def version_manifest():
    return yaml.safe_load((ROOT / "workitem" / "contract-version.yaml").read_text())


def test_v2_is_the_current_version_and_is_released():
    manifest = version_manifest()
    assert manifest["current"] == "v2"
    entry = next(v for v in manifest["versions"] if v["tag"] == "workitem/v2")
    assert entry["released"] is not None, "an unreleased version must not be current"
    assert entry["schema_version"] == "2.0"


def test_v1_point_1_is_superseded_by_v2():
    entry = next(
        v for v in version_manifest()["versions"] if v["tag"] == "workitem/v1.1"
    )
    assert entry.get("superseded_by") == "workitem/v2"


def test_v2_schema_file_exists_at_the_declared_major():
    manifest = version_manifest()
    entry = next(v for v in manifest["versions"] if v["tag"] == "workitem/v2")
    major = entry["schema_version"].split(".")[0]
    assert (ROOT / "workitem" / f"v{major}.schema.json").exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest tests/test_release_v2.py -q`

Expected: `test_v2_is_the_current_version_and_is_released` fails — `current` is still `v1.1`.

- [ ] **Step 3: Migrate the examples and fixtures**

This must happen **before** `current` flips, or the suite breaks and the cause is
not obvious. `test_examples.py` validates the four canonical examples against
`load_contract().schema`, which resolves through `current`. All four declare
`schema_version: "1.0"` and none carries `external_dependencies`:

```bash
cd /Users/stu/projects/.github
python3 tools/migrate_examples_to_v2.py
```

That helper rewrites `schema_version: "1.0"` to `"2.0"` and appends
`external_dependencies: []` to every file under `workitem/examples/` and
`workitem/conformance/tests/fixtures/` that declares a `schema_version` and does
not already carry the key. It prints how many files it touched; the count must
equal the number of candidates, or some file needs a hand decision.

Confirm every example validates against v2:

```bash
python3 -c "
import json, yaml, jsonschema, pathlib
schema = json.load(open('workitem/v2.schema.json'))
for path in sorted(pathlib.Path('workitem/examples').glob('*.yaml')):
    jsonschema.validate(yaml.safe_load(path.read_text()), schema)
    print('  ok', path.name)
"
```

Expected: four `ok` lines. Any failure means a fixture needed a judgement call —
stop and report it rather than loosening v2.

Create `tools/migrate_examples_to_v2.py`:

```python
"""One-shot migration of examples and fixtures to contract v2.

v2 requires external_dependencies, and the canonical examples declare
schema_version 1.0. Once contract-version.yaml sets current: v2 the checker
resolves v2.schema.json, and every 1.0-shaped example fails on both the version
const and the missing key. This rewrites them in place, once, before the flip.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGETS = [
    *sorted((ROOT / "workitem" / "examples").glob("*.yaml")),
    *sorted((ROOT / "workitem" / "conformance" / "tests" / "fixtures").glob("*.yaml")),
]


def main() -> int:
    candidates = [p for p in TARGETS if "schema_version" in p.read_text()]
    touched = 0
    for path in candidates:
        text = path.read_text()
        if "external_dependencies" in text:
            continue
        text = re.sub(r'(schema_version:\s*)"1\.0"', r'\g<1>"2.0"', text, count=1)
        path.write_text(text.rstrip("\n") + "\nexternal_dependencies: []\n")
        touched += 1
    print(f"migrated {touched} of {len(candidates)} candidates")
    if touched != len(candidates):
        print("some candidates already had external_dependencies; inspect them", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Update the manifest**

In `workitem/contract-version.yaml`:

- `current: v1.1` → `current: v2`
- On the `workitem/v1.1` entry, add `superseded_by: workitem/v2`
- On the `workitem/v2` entry, set `released: null` → today's date, and add a note:

```yaml
  - tag: workitem/v2
    schema_version: "2.0"
    released: "2026-10-04"
    note: >-
      External dependency resolution. Adds the required top-level
      external_dependencies[]; dependencies[] and its target pattern are unchanged.
      A dependency is satisfied only by DONE -- CANCELLED satisfies nothing but
      stays reachable, so no record is ever trapped.
```

- [ ] **Step 5: Document the rollback pair**

In `workitem/README.md`, find the existing rollback section and add:

```markdown
### Rollback

| Contract | Gate | Notes |
|---|---|---|
| `workitem/v2` | `workitem-gate/v5` | current |
| `workitem/v1.1` | `workitem-gate/v4` | previous; `workitem-gate/v1` is broken (quoted boolean input) |

v1 → v2 is a migration (`workitem/migrations/v1-to-v2.yaml`), not a pin change:
`external_dependencies` is a required field, so v1-shaped records do not validate
against v2.
```

- [ ] **Step 6: Run the whole suite**

Run: `cd workitem/conformance && PYTHONPATH=. python -m pytest -q`

Expected: all pass.

- [ ] **Step 7: Fix the provenance schema path (#18)**

**Must happen before the tag is cut.** `.github/workflows/validate-workitem.yml:145,150,153` hardcode
`workitem/v1.schema.json`. Once v2 is current, the checker validates against
`v2.schema.json` while the uploaded provenance artifact — the audit-grade record of
*which schema validated these records* — names the v1 file and its checksum. The
record would read `contract_version: v2, path: workitem/v1.schema.json` and be
internally contradictory. `provenance.schema.json` requires only `minLength: 1`
for `path`, so it passes its own validation.

Resolve it the way the checker does, from the manifest entry for `current`:

```bash
grep -n 'schema_path = contract\|"path": "workitem/' .github/workflows/validate-workitem.yml
```

Replace the hardcoded path with a lookup of the `current` entry's `schema_version`
major, plus an assertion that the resolved file exists so a bad resolution fails
loudly rather than checksumming a missing path. Do not import the checker's private
`_schema_filename` — a workflow reaching into a private symbol is the coupling
F2 flagged in the derive tool.

Add this to the Verification Checklist below as well, so the check is part of the
release verification and not only a task step.

- [ ] **Step 8: Merge, then tag — in that order**

Merge the contract PR first. Tags point at merged commits, so tagging before the merge produces a tag no release ever consumed.

```bash
git push origin main
git tag -a workitem/v2    origin/main -m "WorkItem contract v2: external dependency resolution"
git push origin workitem/v2
```

Then retag the gate, because the conformance checker changed:

```bash
git tag -a workitem-gate/v5 origin/main -m "Conformance gate v5

Adds cycle detection, external discharge resolution, and the DONE-only
satisfaction rule. Job name stays constant -- do not interpolate an input into it,
that broke consumers' required status-check contexts in v4."
git push origin workitem-gate/v5
```

- [ ] **Step 9: Re-pin the consumer**

In `harkers/workhub/.github/workflows/validate-workitems.yml`:

- `contract-ref: workitem/v1.1` → `workitem/v2`
- `gate-ref: workitem-gate/v4` → `workitem-gate/v5`
- `uses: ...validate-workitem.yml@workitem-gate/v4` → `@workitem-gate/v5`

**Keep the job name exactly `Validate WorkItems`.** The required status-check context on `harkers/workhub:main` is `Validate WorkItems / Validate WorkItems`. Renaming the job re-blocks `main`, and the failure will look like a flaky check rather than a configuration coupling.

- [ ] **Step 10: Verify the consumer gate green on `main`**

```bash
gh api "repos/harkers/workhub/actions/runs?branch=main&per_page=1" \
  -q '.workflow_runs[0] | "\(.conclusion) \(.head_sha[0:7])"'
```

Expected: `success`. Only then merge the consumer PR.

- [ ] **Step 11: Close #4**

```bash
gh issue close 4 --repo harkers/.github --reason completed
```

Comment with the measured blast radius, the migration name, and the rollback pair. Do not restate the `dag-scheduler`, `of_type` or sentinel-deadlock claims — the spec corrects them.

- [ ] **Step 12: Commit**

```bash
git add workitem/contract-version.yaml workitem/README.md tools/migrate_examples_to_v2.py \
        workitem/conformance/tests/test_release_v2.py \
        workitem/examples workitem/conformance/tests/fixtures
git commit -m "release: contract v2, external dependency resolution

Rollback is workitem/v1.1 + workitem-gate/v4. v1 -> v2 needs the migration, not a
pin change, because external_dependencies is required."
```

---

## Verification Checklist

Run before declaring Task 7 complete:

```bash
# 1. Full suite from a fresh clone of the published tag, not a local checkout.
cd /tmp && rm -rf v2check
git clone --depth 1 --branch workitem/v2 https://github.com/harkers/.github v2check
cd v2check && python3 -m venv .venv && .venv/bin/pip install -q \
  "jsonschema>=4.21,<5.0" "PyYAML>=6.0,<7.0" "pytest>=7.0.0"
PYTHONPATH=workitem/conformance .venv/bin/python -m pytest workitem/conformance -q

# 2. Ledger invariants hold on the live consumer ledger.
PYTHONPATH=workitem/conformance .venv/bin/python -m pytest \
  workitem/conformance/tests/test_dependency_reachability.py -v

# 3. The provenance artifact names the schema that actually validated.
#    (#18 -- before any consumer pins v2 the path was hardcoded to v1.schema.json.)
gh run list --repo harkers/workhub --workflow="Validate WorkItems" --limit 1 \
  --json databaseId -q '.[0].databaseId' | xargs -I{} gh api \
  repos/harkers/workhub/actions/runs/{}/artifacts -q '.artifacts[].name'

# 4. Both schema files exist and the internal pattern is unchanged.
python3 -c "
import json
for m in ('v1','v2'):
    s=json.load(open(f'workitem/{m}.schema.json'))
    print(m, s['properties']['schema_version']['const'],
          s['properties']['dependencies']['items']['properties']['target']['pattern'])
"
```

Expected: all green; `v1` and `v2` both print pattern `^WI-[0-9]{8}-[0-9]{4}$`, with `const` values `1.0` and `2.0`.

## Plan Self-Review

- **Spec coverage:** every spec section maps to a task — data model (Task 2), enforcement (Task 4), cycle detection (Task 3), invariants I1–I6 (Tasks 4–5, with I1 unchanged and already covered by `test_parameter_space.py`), versioning (Task 7), migration (Task 6), sequencing (Blocking Preconditions).
- **Placeholders:** none. Every code block is complete and runnable.
- **Type consistency:** `find_cycles` returns `list[list[str]]` in Task 3 and is consumed that way in Task 5. Problem codes `dependency-cycle`, `unresolved-external-discharge`, `dependency-not-satisfied` are introduced once and reused verbatim. `external_dependencies` / `resolved_by` are spelled identically in Tasks 2, 3, 4, 5 and 6.
- **Known gap, stated rather than hidden:** `check_before` cannot evaluate dependency satisfaction, so the `DONE` gate in `policy.yaml` documents where the rule lives instead of declaring a `required_before` key. The alternative — threading a ledger parameter through `check_before` and `TransitionEngine` — is recorded in Task 4 with its blast radius.