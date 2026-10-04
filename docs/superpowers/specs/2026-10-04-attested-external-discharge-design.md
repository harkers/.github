# Attested discharge for external dependencies — design and implementation

Date: 2026-10-04
Implements: harkers/.github#24
Adopts: harkers/workhub `docs/decisions/0005-external-workitem-dependencies-are-advisory.md` option (a)
Supersedes: the option-(b)-flavoured rule in `workitem/v2.1`

## Problem

`workitem/v2.1` requires `external_dependencies[].resolved_by` to name a WorkItem that is itself `DONE`. Applied to the live record that motivated workhub's ADR 0005:

```yaml
WI-20261003-0005   state: DRAFT
  dependencies:          []
  external_dependencies: []
  issue refs in prose:   ['13', '14', '15']
```

All three blockers reached `DONE` on 2026-10-03/04 (`#13` PR #40, `#14` PR #67, `#15` PR #78). So under v2.1 this record cannot finish until three WorkItems are manufactured retrospectively for completed work, each reaching `DONE` itself.

That is the outcome ADR 0005 names when rejecting option (b): *"manufactures records and creates dangling edges"*. And a ledger that cannot record reality gets worked around — which is exactly how `dependencies: []` plus prose arose.

## Decision

Each `external_dependencies[]` entry discharges **exactly one** of two ways.

```yaml
external_dependencies:
  # strict: machine-checked against the ledger
  - repo: harkers/agent-fabric
    number: 31
    type: REQUIRES
    resolved_by: WI-20261004-0031

  # attested: recorded human confirmation, gated at PR_READY
  - repo: harkers/workhub
    number: 13
    type: REQUIRES
    attested:
      by: <identifier>
      at: "2026-10-04T12:00:00Z"
      note: "merged as 9b0929c; WorkItem not raised retrospectively"
```

| discharge | checked against | refuses |
|---|---|---|
| `resolved_by` | the ledger — the named WorkItem must be `DONE` | `DONE`, via `dependency-not-satisfied` |
| `attested` | presence of an attributed record | nothing — the attestation *is* the confirmation |

`PR_READY` precedes `DONE` in the ladder, so a satisfied attestation carries an item through to `DONE`. That is ADR 0005's constraint 2: the cost lands at delivery, where the human information exists, rather than at planning time, where it does not.

### The weakening, stated

An attested edge **cannot be verified by this contract**. An item can ship carrying a permanent external blocker provided a human signs for it. Accepted knowingly, because the alternative is a ledger that cannot record reality.

The mitigation is attribution, not verifiability: `by` and `at` are required, so an unowned assertion is not expressible. This is a reversal of the v2 decision to drop `kind` entirely — on the grounds that an unfalsifiable assertion is not a discharge. The live record is information that did not exist when that decision was taken.

### Divergence from ADR 0005's shape

ADR 0005 proposes a `BLOCKED_BY_EXTERNAL` relation type. This keeps the separate `external_dependencies[]` array, because:

1. `dependencies[].target` stays pattern-locked to `WI-…` — already released and consumed.
2. Field separation already achieves the discrimination ADR 0005 wants ("a reader can tell an unresolvable edge from a resolvable one without inspecting the target's format").

Changing the shape would break a deployed consumer for no gain.

## Versioning

**`workitem/v3`, `schema_version: "3.0"`.** `resolved_by` becomes one arm of an exclusive choice rather than the only option — a retyping in effect, which D8 excludes from data releases.

`workitem/v2.1` stays pinnable. Every existing record uses `resolved_by` alone, which remains valid under v3. Superseded, not withdrawn.

## Implementation

### Task 1 — schema

`workitem/v3.schema.json`, derived from v2 by `tools/derive_v2_schema.py` extended to a `--from` major. `external_dependencies.items` becomes:

```json
"oneOf": [
  { "required": ["repo","number","type","resolved_by"],
    "additionalProperties": false, "properties": { ...resolved_by arm... } },
  { "required": ["repo","number","type","attested"],
    "additionalProperties": false, "properties": { ...attested arm... } }
]
```

`attested` requires `by` (non-empty), `at` (`date-time`), `note` (non-empty).

Both arms need `additionalProperties: false` so an entry cannot smuggle fields past the exclusivity check — otherwise `oneOf` is defeated by adding a stray key.

### Task 2 — checker

`unmet_targets` currently treats every entry as needing `resolved_by == DONE`. Change it to return an entry as satisfied when it is attested:

```python
def unmet_targets(item):
    internal = [...]
    external = [
        edge.get("resolved_by")
        for edge in _edges(item, "external_dependencies")
        if "attested" not in edge and states.get(edge.get("resolved_by")) != "DONE"
    ]
```

And `unresolved-external-discharge` must not fire on an attested edge.

### Task 3 — tests

- `attested` alone validates; `resolved_by` alone still validates
- both together is **rejected** (exclusivity)
- neither is rejected
- an attested entry does not produce `unresolved-external-discharge`
- an attested entry does not produce `dependency-not-satisfied` when the record is `DONE`
- `attested` missing `by` / `at` / `note` is rejected
- the live case: `WI-20261003-0005`-shaped record reaches `DONE` with three attestations and zero `resolved_by`
- **prove each new test fails on a real break** — an invariant test that cannot fail is decoration

### Task 4 — release

Manifest to `v3`, released, `v2.1 superseded_by v3`. Derive tool handles `--from 2`. Examples/fixtures migrated to the v3 shape. New `workitem-gate/v6` for the changed checker. Consumer re-pins to `workitem/v3` + `workitem-gate/v6`, **keeping the job name `Validate WorkItems`**.

`migration v1-to-v2.yaml` is unaffected — v3 is a superset of v2 for records that use `resolved_by`. No v2→v3 migration is needed, and the manifest should say so.

## Verification

```bash
# full suite
PYTHONPATH=workitem/conformance .venv/bin/python -m pytest workitem/conformance -q

# released tag, fresh clone
git clone --depth 1 --branch workitem/v3 https://github.com/harkers/.github v3check

# the live case, end to end
PYTHONPATH=v3check/workitem/conformance python -c "... validate a 0005-shaped record ..."
```

## Non-goals

- Promotion of an external edge to an internal `BLOCKS` edge once the referenced issue becomes a WorkItem. ADR 0005 leaves it open; it is a real migration path and out of scope here.
- Cross-repository trust — whether a `harkers/agent-fabric#31` citation may be made with no verification of its state. Also open in the ADR.
- Changing internal `dependencies[]` semantics, cycle detection, or the `CANCELLED` rule.