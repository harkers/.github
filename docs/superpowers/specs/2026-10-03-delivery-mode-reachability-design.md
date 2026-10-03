# Delivery-mode reachability — Design

- **Date:** 2026-10-03
- **Fixes:** `harkers/.github`#8 — *delivery_mode `branch_only` and `none` cannot reach `DONE`*
- **Scope:** the canonical contract and its checker. No change to `workhub`, no writer, no consumer behaviour beyond a pin.
- **Status:** design approved; not yet implemented
- **Contract:** `workitem/v1` → **`workitem/v1.1`** · **Gate:** `workitem-gate/v2` → **`workitem-gate/v3`**

---

## 1. Summary

`DONE` had exactly one incoming edge, from `PR_READY`. Because `parameters.delivery_mode.skips_states`
marks `PR_READY` as skipped under `delivery.mode: none`, removing it removed the only door to `DONE`.
A WorkItem with `delivery.mode: none` — every investigation, every documentation task — could not
finish. It could reach `REPORTING` and then stop, permanently.

`branch_only` is separately incoherent: it declares no skips, so the graph routes it through `PR_DRAFT`
while the `PR_DRAFT` gate demands `delivery.pull_request` — a value that by definition does not exist
in `branch_only`. The state machine says the path is legal; the gate says it can never be satisfied.

This document fixes both. It is a defect fix, not a redesign: the 16+4 ladder, the gate rules and
the identifier scheme are unchanged.

## 2. Evidence

Reachability computed from the declared edge set, per delivery mode:

| `delivery.mode` | `DONE` reachable | states reached | unreachable |
| --- | --- | --- | --- |
| `pull_request` | yes | 20 / 20 | — |
| `branch_only` | yes *(in the graph)* | 20 / 20 | — |
| `none` | **NO** | 15 / 20 | `COMMITTED`, `PR_DRAFT`, `IMPLEMENTATION_COMPLETE`, `PR_READY`, `DONE` |

Gate satisfiability, checked independently of the graph:

```text
delivery.mode=none:         PR_DRAFT gate satisfiable without a PR? NO
delivery.mode=branch_only:  PR_DRAFT gate satisfiable without a PR? NO
```

Declared at the time:

```yaml
parameters:
  delivery_mode:
    values: [pull_request, branch_only, none]
    skips_states: [COMMITTED, PR_DRAFT, IMPLEMENTATION_COMPLETE, PR_READY]   # applied only when mode == "none"
```

```yaml
- state: PR_DRAFT
  artifact_required: delivery.pull_request
  enforced: true      # unconditional — no delivery.mode awareness
```

## 3. Root cause

**Delivery-mode awareness was implemented in exactly one place.** `state-machine.yaml` had a
`parameters` block; `policy.yaml`'s gate table had no notion of delivery mode at all. So the graph and
the gates disagreed about what a delivery mode means, and the graph's skip mechanism had no way to
route around a skipped state.

Two contributing defects:

1. `skips_states` was a single list applied only when `delivery.mode == "none"`. `branch_only` had no
   skips, so it fell through to PR states it cannot satisfy.
2. The engine's `skipped_by_delivery_mode` hardcoded that `== "none"` comparison rather than reading a
   per-mode declaration.

A third factor let it survive 109 passing conformance tests: the reachability test asserted
reachability **from `DRAFT` under the default context**, and the default context is `pull_request`. The
dead end existed only in a parameter value the tests never used. I tested the path I expected
consumers to take rather than the declared parameter space.

## 4. Decisions

| # | Decision |
| --- | --- |
| D1 | **The database is authoritative; files are projections.** Unchanged from v1. |
| D2 | **DONE is the single terminal for every delivery mode.** Not adding a `DELIVERED` state — that would split the meaning of completion and reintroduce the two-ladders problem. `DONE` means the WorkItem's work is finished, whatever delivery that implies. |
| D3 | **Skipped states are bypassed by explicit conditional edges**, not by an engine that synthesises them. Every edge stays visible and auditable in the YAML. |
| D4 | **`branch_only` means committed to a branch, never a PR.** The branch and its commits are real; only the PR machinery is absent. |
| D5 | **The gate table learns `when: { delivery_mode: ... }`**, mirroring the state machine's existing condition syntax. One mechanism, not two. |

## 5. Goals and non-goals

### Goals

1. Every declared state is reachable from `DRAFT` under every delivery mode in which it is not skipped.
2. Every delivery mode can reach a terminal state.
3. The graph and the gates agree about what each delivery mode means.
4. A record cannot claim a pull request in a mode that forbids one.
5. Consumers can revert by re-pinning, without a code change.

### Non-goals

- No change to the 16 happy-path or 4 exceptional states.
- No new field, no removed field, no record migration.
- No change to `workhub`, no writer, no CLI.
- No change to identifier format, review policy, sizing policy, or the event model.
- Not a general fix for other parameter combinations this change may not have exercised. See §9.

## 6. The fix

### 6.1 `state-machine.yaml`

Replace the single skip list with per-mode declarations:

```yaml
parameters:
  delivery_mode:
    field: delivery.mode
    values: [pull_request, branch_only, none]
    default: pull_request
    # A state listed here is unreachable under that mode. Gates in policy.yaml
    # consult the same list via their own `when:` conditions, so the graph and
    # the gates cannot disagree about what a mode means.
    skips_states_by_mode:
      pull_request: []
      branch_only:  [PR_DRAFT, PR_READY]
      none:         [COMMITTED, PR_DRAFT, IMPLEMENTATION_COMPLETE, PR_READY]
```

Two new conditional edges, alongside the existing `VALIDATED → TESTING when delivery_mode: none`:

```yaml
- { from: COMMITTED, to: IMPLEMENTATION_COMPLETE, when: { delivery_mode: branch_only } }
- { from: REPORTING, to: DONE,                 when: { delivery_mode: branch_only } }
- { from: REPORTING, to: DONE,                 when: { delivery_mode: none } }
```

Resulting reachability:

| mode | skipped | reachable |
| --- | --- | --- |
| `pull_request` | — | 20 / 20 |
| `branch_only` | `PR_DRAFT`, `PR_READY` | 18 / 20 |
| `none` | `COMMITTED`, `PR_DRAFT`, `IMPLEMENTATION_COMPLETE`, `PR_READY` | 16 / 20 |

`DONE` is reachable in all three.

### 6.2 `transitions.py`

`skipped_by_delivery_mode` currently reads a fixed key and compares `== "none"`. It becomes a lookup of
`skips_states_by_mode[mode]`, defaulting to `[]` for an undeclared mode rather than silently skipping
nothing. No state name or edge appears in the module.

### 6.3 `policy.yaml`

`PR_DRAFT`'s gate gains the same condition syntax the state machine uses:

```yaml
- state: PR_DRAFT
  artifact_required: delivery.pull_request
  enforced: true
  predicate: check_declared_gates
  when: { delivery_mode: pull_request }
  note: "branch pushed and a draft PR exists using the repository PR template"
```

No other gate needs it. `COMMITTED` requires `artifacts.commits`, which holds for `branch_only`
(commits are real) and is moot for `none` (the state is skipped). `REPORTING` requires a completion
packet and `DONE` requires passed verification plus a packet — both apply under every mode.

### 6.4 `gates.py`

`check_declared_gates` skips any gate whose `when` does not match the record's `delivery.mode`. A gate
with no `when` applies unconditionally, exactly as today. The module still embeds no policy literal.

### 6.5 `v1.schema.json`

One constraint, so a record cannot contradict its own mode:

```json
"allOf": [
  {
    "if":   { "properties": { "delivery": { "properties": { "mode": { "enum": ["branch_only", "none"] } } } } },
    "then": { "properties": { "delivery": { "properties": { "pull_request": { "type": "null" } } } } }
  }
]
```

Without it, `branch_only` with a non-null `pull_request` is accepted — verified against the v1 schema:

```text
branch_only + pull_request:42   accepted today (0 errors)
branch_only + pull_request:null accepted today (0 errors)
```

The `if` is safe without an explicit `required`: `delivery` is in the schema's top-level `required`
list and `mode` is required within it, so neither can be absent for the `if` to match vacuously.
Asserted by a test rather than assumed.

**`delivery.branch` is deliberately left unconstrained.** An earlier draft of this design also required
`branch` to be non-null for `pull_request` mode. That is wrong: `WI-20261003-0005` is a live
`DRAFT` record with `delivery: {mode: pull_request, branch: null, pull_request: null}`, and a branch
does not exist until execution begins. Constraining it would invalidate the one record that exists,
for a condition that has nothing to do with reachability.

## 7. Versioning, pins, migration

| Change | File | Forces |
| --- | --- | --- |
| `skips_states_by_mode`, three conditional edges | `state-machine.yaml` | contract `workitem/v1.1` |
| `when:` on the `PR_DRAFT` gate | `policy.yaml` | contract `workitem/v1.1` |
| `allOf` delivery/mode constraints | `v1.schema.json` | contract `workitem/v1.1` |
| `skipped_by_delivery_mode` generalised | `transitions.py` | gate `workitem-gate/v3` |
| `check_declared_gates` honours `when` | `gates.py` | gate `workitem-gate/v3` |

**Migration: none.** No field is added or removed. `delivery.pull_request` was already
`integer | null`, so no existing record needs rewriting. This is recorded as a declared no-op rather
than an empty migration file — a migration that transforms nothing is noise.

Before cutting `workitem/v1.1`, every live record is validated against the new constraints. A record
carrying `mode: branch_only` with a non-null `pull_request` would be the only possible casualty; if
one exists it must be fixed by hand rather than migrated, because the correct value is a judgement.

**Rollback is a pin change.** `workitem/v1` + `workitem-gate/v2` remains a working combination, so a
consumer reverts by editing two lines. That is what the two-tag split bought, and it matters more now
than when it was introduced — the contract is becoming load-bearing for something that can actually
run.

## 8. Tests

The invariant that was missing:

> **Every declared state is reachable from `DRAFT` under every delivery mode in which it is not
> skipped, and every mode can reach a terminal state.**

Added to `workitem/conformance/tests/`:

| Test | Purpose |
| --- | --- |
| `test_every_state_is_reachable_under_every_applicable_mode` | The invariant above. Fails at v1. |
| `test_every_mode_can_reach_a_terminal_state` | `DONE` reachable under all three modes. Fails at v1 for `none`. |
| `test_skip_lists_match_the_declared_modes` | Every value in `values` has an entry in `skips_states_by_mode`. |
| `test_undeclared_mode_skips_nothing` | An unknown mode yields `[]`, not a silent pass or a crash. |
| `test_gate_with_when_is_skipped_for_other_modes` | `check_declared_gates` honours `when`. Fails at v1. |
| `test_pr_draft_gate_only_binds_for_pull_request` | The specific incoherence. Fails at v1. |
| `test_branch_only_record_with_a_pull_request_is_rejected` | Schema constraint. Fails at v1. |
| `test_none_record_with_a_pull_request_is_rejected` | Schema constraint. Fails at v1. |
| `test_draft_record_with_a_null_branch_stays_valid` | Guards the v1.1 schema against tightening `branch`. |
| `test_delivery_mode_conditionals_cannot_match_vacuously` | `delivery` and `mode` are always present. |
| `test_existing_records_satisfy_the_new_constraints` | Guards the no-migration claim. |

Four of these fail at v1, which is the evidence they test something real.

## 9. Risks

| Risk | Mitigation |
| --- | --- |
| A different parameter combination has a similar dead end | The reachability invariant is now over the whole declared delivery-mode space rather than one context. `review_policy` is the only other parameter with a state-graph effect; it affects gates, not edges, and is not covered here. |
| `workitem-gate/v1` is still pinned by anything | It carries the boolean-default bug that made every run `startup_failure`; it was never usable. Documented in #6. Nothing to migrate. |
| Tightening the schema invalidates a record nobody has seen | `test_existing_records_satisfy_the_new_constraints` plus a pre-tag validation pass over the live ledger. An earlier draft of this design would have broken `WI-20261003-0005` by constraining `branch`; §6.5 records why it was dropped. |
| `strict: true` on `main` blocks the consumer PR until it is up to date | Expected. Rebase and let the gate run green before merge. |

## 10. Open questions deferred

- Whether `review_policy` needs the same treatment in the gate table. It selects *which* evidence must
  pass, not *which states are reachable*, so the graph is unaffected — but the two parameters are now
  both expressed in `policy.yaml` and only one of them lives in `state-machine.yaml`'s parameters. Worth
  reconciling for symmetry once a second parameter actually needs graph semantics.
- Whether `delivery.mode` should gain a fourth value. `none` currently means "no delivery artifacts at
  all", which is right for an investigation but arguably wrong for a documentation change that does
  commit files. Splitting it would be a new mode, not a fix to this one.