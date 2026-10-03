# Delivery-mode reachability — Design

- **Date:** 2026-10-03
- **Fixes:** `harkers/.github`#8 — *delivery_mode `branch_only` and `none` cannot reach `DONE`*
- **Scope:** the canonical contract and its checker. No change to `workhub`, no writer, no consumer behaviour beyond a pin.
- **Status:** revised after cloud review; not yet implemented
- **Review:** `reviewer-cloud`, 2026-10-03. Its Critical finding -- that the fix as first specified
  does not fix the bug, because duplicate `(from, to)` conditionals shadow each other in
  `check()` -- was reproduced before being accepted.
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
| D6 | **The reachability invariant spans the full cross product of both parameters**, 12 combinations. `review_policy` has no graph effect today — verified — so it is covered as regression protection rather than because it fixes a live dead end. |
| D7 | **Multiple conditional edges may share one `(from, to)` pair.** `check()` scans every conditional for the pair and succeeds if any condition matches; `edge_spec()` returns all matching variants. See 6.2. |
| D8 | **Tightening a schema does not bump `schema_version`.** Records stay `\"1.0\"`. See 6.7. |

## 5. Goals and non-goals

### Goals

1. Every declared state is reachable from `DRAFT` under every combination of `delivery_mode` and
   `review_policy` in which it is not skipped.
2. Every combination can reach `DONE`. (`DONE` is the only completion outcome; `CANCELLED` is an
   abandonment, not a finish. An earlier draft said "a terminal state", which was wrong — `CANCELLED`
   is reachable from `DRAFT` under every mode at v1, so that phrasing passed while the defect stood.)
3. No reachable state has a gate that is *structurally unsatisfiable* — a gate demanding a field
   that the active mode forbids.
4. A record cannot claim a pull request in a mode that forbids one.
5. Consumers can revert by re-pinning, without a code change.

Invariant 3 is stated separately from 1 and 2 because it is a different kind of failure. 1 and 2
are about the graph; 3 is about the graph and the gates disagreeing. The `branch_only` defect is
purely 3 — every state was reachable, and the work could still not be completed.

### Non-goals

- No change to the 16 happy-path or 4 exceptional states.
- No new field, no removed field, no record migration.
- No change to `workhub`, no writer, no CLI.
- No change to identifier format, review policy, sizing policy, or the event model.
- Not a fix for any parameter combination beyond `delivery_mode` and `review_policy`.
  Those two are now exhaustively covered; anything added later is covered automatically
  by the cross-product test, which enumerates declared values rather than a literal.

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

Two changes, both of which the fix **requires**.

**Per-mode skip lookup.** `skipped_by_delivery_mode` currently reads a fixed key and compares
`== "none"`. It becomes a lookup of `skips_states_by_mode[mode]`, defaulting to `[]` for an
undeclared mode rather than silently skipping nothing.

**Conditional edges must not shadow each other.** The fix needs two `REPORTING -> DONE` edges — one
per mode — so the same `(from, to)` pair appears twice with different conditions. The current
`check()` returns on the *first* matching conditional in declaration order, and `_specs[(frm, to)] = edge`
means `edge_spec()` returns the *last*. First-wins in one place, last-wins in the other.

Measured against the fix as originally specified, with `check()` unchanged:

```text
delivery.mode=pull_request   DONE reachable: True   20/20
delivery.mode=branch_only    DONE reachable: True    18/20
delivery.mode=none           DONE reachable: False   15/20   <- unchanged from v1
```

**The fix as specified does not fix the bug.** Under `none`, `check()` hits the `branch_only` edge
first and refuses.

So:

- `check()` scans **all** conditionals for the `(from, to)` pair and returns legal if *any* condition
  matches, illegal only after exhausting them.
- `edge_spec()` returns **every** matching variant rather than one, so a duplicate can never be
  invisible again.
- A test asserts that two conditionals sharing a pair are both honoured.

No state name or edge appears in the module, and this is the first consumer of the duplicate-pair
case — which is exactly why it is specified rather than left to the implementation.

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

### 6.4 Parameter spaces become enumerable

The cross-product test must enumerate declared values rather than hardcode them. `delivery_mode`
already declares its `values`; `review_policy` does not declare anything about *where* it applies.
It now says so:

```yaml
parameters:
  review_policy:
    field: verification.review_policy
    values: [low_risk, normal, security_sensitive, high_risk]
    affects: gates        # not edges -- selecting which evidence must pass changes no state graph
```

This is a comment expressed as data. The asymmetry between the two parameters is a real fact — one
governs edges, the other gates — and stating it means the next reader does not have to infer it, and
the test can fail loudly if that ever stops being true.

### 6.5 `gates.py`

`check_declared_gates` skips any gate whose `when` does not match the record's `delivery.mode`. A gate
with no `when` applies unconditionally, exactly as today. The module still embeds no policy literal.

### 6.6 `v1.schema.json`

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

`mode: none` also forbids `branch`. `none` is defined as *"no delivery artifacts at all"*, and a
branch name is a delivery artifact. The two constraints are therefore:

```json
"allOf": [
  {
    "if":   { "properties": { "delivery": { "properties": { "mode": { "const": "none" } } } } },
    "then": { "properties": { "delivery": { "properties": { "branch": { "type": "null" },
                                                                 "pull_request": { "type": "null" } } } } }
  },
  {
    "if":   { "properties": { "delivery": { "properties": { "mode": { "const": "branch_only" } } } } },
    "then": { "properties": { "delivery": { "properties": { "pull_request": { "type": "null" } } } } }
  }
]
```

Verified safe against everything that exists: `workitem/examples/investigation.yaml` is `mode: none`
with both fields null and passes; the live `WI-20261003-0005` is `pull_request` and is unaffected.

**`delivery.branch` is otherwise deliberately left unconstrained.** An earlier draft of this design also required
`branch` to be non-null for `pull_request` mode. That is wrong: `WI-20261003-0005` is a live
`DRAFT` record with `delivery: {mode: pull_request, branch: null, pull_request: null}`, and a branch
does not exist until execution begins. Constraining it would invalidate the one record that exists,
for a condition that has nothing to do with reachability.

### 6.7 `schema_version` — the coupling that had to be decided

`v1.schema.json` declares `"schema_version": { "const": "1.0" }`. `contract-version.yaml` already
declares `workitem/v1.1 -> schema_version: "1.1"`. `test_provenance.py` asserts the current tag's
declared `schema_version` equals the schema's `const`.

When `current` flips to `v1.1` those three collide, and every option has a cost:

| Option | Consequence |
| --- | --- |
| const -> `"1.1"` | Every record and fixture fails validation. **"Migration: none" becomes false** and the live ledger breaks. |
| const stays `"1.0"` | The declared `v1.1 -> "1.1"` mapping is wrong. |
| const -> enum | `test_provenance.py:70` reads `["const"]` and raises `KeyError`. |

**Decision (D8): tightening a schema does not bump `schema_version`.** Records stay `"1.0"`, the
const stays `"1.0"`, and `contract-version.yaml`'s `workitem/v1.1` entry is corrected to
`schema_version: "1.0"` — because `v1.1` is a *contract data* release (state machine, policy) that
adds no field. `test_provenance.py` passes unchanged.

This is a documented policy, not an accident: the tag and the schema version are different
namespaces, and a minor contract release does not imply a schema change. The risk it creates — a
consumer's record silently failing a tightened constraint with no version signal — is managed by the
pre-tag validation pass in section 7, which must cover every live record.

## 7. Versioning, pins, migration

| Change | File | Forces |
| --- | --- | --- |
| `skips_states_by_mode`, three conditional edges | `state-machine.yaml` | contract `workitem/v1.1` |
| `when:` on the `PR_DRAFT` gate | `policy.yaml` | contract `workitem/v1.1` |
| `allOf` delivery/mode constraints (`none` forbids `branch` and `pull_request`; `branch_only` forbids `pull_request`) | `v1.schema.json` | contract `workitem/v1.1` |
| `skipped_by_delivery_mode` generalised; conditional edges no longer shadow; `edge_spec` returns all variants | `transitions.py` | gate `workitem-gate/v3` |
| `check_declared_gates` honours `when` | `gates.py` | gate `workitem-gate/v3` |

**Migration: none.** No field is added or removed. `delivery.pull_request` was already
`integer | null`, so no existing record needs rewriting. This is recorded as a declared no-op rather
than an empty migration file — a migration that transforms nothing is noise.

Before cutting `workitem/v1.1`, every live record is validated against the new constraints. A record
carrying `mode: branch_only` with a non-null `pull_request` would be the only possible casualty; if
one exists it must be fixed by hand rather than migrated, because the correct value is a judgement.

`contract-version.yaml` gains one correction: `workitem/v1.1` currently declares
`schema_version: "1.1"`, which per D8 becomes `"1.0"`. `current` flips to `v1.1`. Without this
correction `test_provenance.py` fails and the declared mapping is simply wrong.

**Rollback is a pin change.** `workitem/v1` + `workitem-gate/v2` remains a working combination, so a
consumer reverts by editing two lines. That is what the two-tag split bought, and it matters more now
than when it was introduced — the contract is becoming load-bearing for something that can actually
run.

## 8. Tests

### 8.1 What was measured before designing this

Reachability and gate satisfiability were computed across the full cross product of both parameters
(3 delivery modes x 4 review policies = 12 combinations) before this design was written.

**`review_policy` has no effect on reachability.** Within every mode, all four policies reach exactly
the same states. It selects *which evidence must have passed*, never *which states exist*. That is the
asymmetry section 6.4 now declares rather than leaves to be inferred.

**So the cross product finds no second live defect.** What it buys is regression protection: a future
change that made a review policy block a state would be caught, where today nothing would notice.

The one structural incoherence it does find is `branch_only` x every policy:

```text
WITHOUT the fix (gate has no `when`):
  (branch_only, low_risk,           PR_DRAFT, delivery.pull_request)
  (branch_only, normal,             PR_DRAFT, delivery.pull_request)
  (branch_only, security_sensitive, PR_DRAFT, delivery.pull_request)
  (branch_only, high_risk,          PR_DRAFT, delivery.pull_request)

WITH the fix:  none -- the invariant holds across all 12 combinations
```

`none` does not appear: `PR_DRAFT` is skipped there, so it is never reachable and cannot carry an
unsatisfiable gate.

### 8.2 Invariants under test

> **I1** Every declared state is reachable from `DRAFT` under every `(delivery_mode, review_policy)`
> combination in which it is not skipped.
>
> **I2** Every such combination can reach `DONE`.
>
> I2 is implied by I1, since `DONE` appears in no skip list. It is kept as a separate named assertion
> because "the work must be finishable" is the property a reader actually cares about, and a
> derived property worth reading is worth asserting explicitly.
>
> **I3** No reachable state carries a gate that is structurally unsatisfiable -- one demanding a field
> the active mode forbids.

I3 is stated separately from I1 and I2 because it is a different kind of failure. I1 and I2 are about
the graph; I3 is about the graph and the gates *disagreeing*. The `branch_only` defect is purely I3:
every state was reachable, and the work still could not be completed.

**I3's test is born green, and that is correct.** I3 is decidable only once the schema constraint
exists -- that constraint is what turns "the mode forbids this field" into a machine-checkable fact
rather than a comment, which is why sections 6.3 and 6.6 have to land together. So a test for I3
cannot fail before the schema lands.

The `branch_only` defect at v1 is *semantic*: it lives in the definition of `branch_only` in prose,
not in anything the schema forbids. `v1.schema.json` accepts `branch_only` with `pull_request: 42`
(verified). So the tests that are born red for that defect are the gate-`when` test and the two
schema-rejection tests. I3's test guards the invariant against *future* incoherence; it does not
demonstrate a present one, and it is excluded from the failure count accordingly.

### 8.3 Tests

| Test | Invariant | Fails at v1 |
| --- | --- | --- |
| `test_every_state_is_reachable_under_every_applicable_combination` | I1 | yes (`none`, all policies) |
| `test_every_combination_can_reach_DONE` | I2 | yes (`none`, all policies) |
| `test_no_reachable_state_has_an_unsatisfiable_gate` | I3 | **no** -- born green, see 8.2 |
| `test_parameter_spaces_are_enumerable_from_the_contract` | -- | no (guards the test itself) |
| `test_review_policy_declares_that_it_affects_gates_not_edges` | -- | no (guards 6.4) |
| `test_skip_lists_match_the_declared_modes` | -- | yes |
| `test_undeclared_mode_skips_nothing` | -- | no |
| `test_gate_with_when_is_skipped_for_other_modes` | -- | yes |
| `test_both_conditionals_for_one_edge_pair_are_honoured` | -- | no (needs the D7 fix to exist) |
| `test_branch_only_record_with_a_pull_request_is_rejected` | -- | yes |
| `test_none_record_with_a_pull_request_is_rejected` | -- | yes |
| `test_draft_record_with_a_null_branch_stays_valid` | -- | no (guards 6.6 against tightening `branch`) |
| `test_delivery_mode_conditionals_cannot_match_vacuously` | -- | no |
| `test_existing_records_satisfy_the_new_constraints` | -- | no (guards the no-migration claim) |

**Five of fourteen fail at v1.** An earlier draft of this spec claimed seven. That was wrong twice
over: I2 as originally worded ("a terminal state") passed at v1 because `CANCELLED` is reachable from
`DRAFT` under every mode, and I3's test cannot fail before the schema constraint it depends on exists.

The nine that do not fail are guards on the fix rather than demonstrations of the defect, and they
pass today by construction. Claiming a larger number would have been the easy thing to do and would
have been false.

`test_parameter_spaces_are_enumerable_from_the_contract` is the one that stops this class of bug
recurring silently: it asserts the tests read their combinations from the contract's declared
`values` rather than from a literal. A fourth delivery mode added to `state-machine.yaml` would then
be covered without touching a test file.
## 9. Risks

| Risk | Mitigation |
| --- | --- |
| A different parameter combination has a similar dead end | The reachability invariant is now over the whole declared delivery-mode space rather than one context. `review_policy` is the only other parameter with a state-graph effect; it affects gates, not edges, and is not covered here. |
| `workitem-gate/v1` is still pinned by anything | It carries the boolean-default bug that made every run `startup_failure`; it was never usable. Documented in #6. Nothing to migrate. |
| Tightening the schema invalidates a record nobody has seen | `test_existing_records_satisfy_the_new_constraints` plus a pre-tag validation pass over the live ledger. An earlier draft of this design would have broken `WI-20261003-0005` by constraining `branch`; §6.5 records why it was dropped. |
| `strict: true` on `main` blocks the consumer PR until it is up to date | Expected. Rebase and let the gate run green before merge. |
| **The fix reintroduces a graph/checker disagreement.** Two conditionals sharing a pair diverged between `check()` and `edge_spec()`, and that is the same failure class as the original defect | This is why D7 and section 6.2 specify the engine change rather than leaving it to implementation. A test asserts both conditionals are honoured, and `edge_spec()` now returns every variant. |
| **Tightening a schema with no version signal (D8).** A consumer's record could start failing a constraint it never saw a version bump for | Accepted deliberately, because the alternative breaks the live ledger and falsifies the no-migration claim. Managed by the pre-tag validation pass over every live record, plus `contract-version.yaml` recording that `v1.1` is a data release with `schema_version: "1.0"`. |
| **`check()` semantics change for every conditional edge, not just this pair** | Scan-all is strictly more permissive than first-match. No edge becomes illegal that was legal; edges previously refused because a shadowing sibling matched first now correctly evaluate. Every existing test must pass unchanged, which is the evidence. |

## 10. Open questions deferred

- Whether the `when:` mechanism should be generalised beyond `delivery_mode`. Both parameters use it
  now, but `review_policy` never needed it for an *edge* condition — only the gate table reads it. A
  parameter that genuinely affects edges *and* gates would justify a single shared parameter
  declaration block rather than one per file.
- Whether `delivery.mode` should gain a fourth value. `none` currently means "no delivery artifacts at
  all", which is right for an investigation but arguably wrong for a documentation change that does
  commit files. Splitting it would be a new mode, not a fix to this one — and the cross-product test
  would cover it automatically, which is part of why it is cheap to add later.
- Whether `execution.resource_class` and `execution.max_attempts` should be declared parameters at all.
  Neither affects reachability or gates today. If a future change made either gate-relevant, it would
  need declaring the same way, and `test_parameter_spaces_are_enumerable_from_the_contract` is where
  that omission would show up.
- Whether a *fourth* invariant is warranted: that every gate, on every reachable path, is satisfiable
  by a record that would actually be written. That is stronger than I3, which only asks whether the
  required field is forbidden by the mode. The full version needs a synthesiser for a valid record per
  state, which is more machinery than this fix warrants.
- Whether `schema_version` should eventually become an enum rather than a `const`, so a contract can
  declare which record versions it accepts. D8 works around the collision rather than solving it, and
  `test_provenance.py:70` will have to be enum-aware when that happens.