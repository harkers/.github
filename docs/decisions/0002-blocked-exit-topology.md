# Decision 0002: how a WorkItem leaves `BLOCKED`

**Date:** 2026-10-04
**Status:** Proposed
**Canonical contract:** `harkers/.github` `workitem/` at tag `workitem/v3`
**Supersedes:** `0001-blocked-resume-position.md` (rejected on review)
**Related:** harkers/.github#22, #26, #29; `harkers/workhub` `src/workhub/cli/commands.py`

## The real question

`0001` framed this as *how to record the resume position*. That was the wrong question, and the framing is what made the record wrong: it assumed a mechanism (`hierarchy.blocked_from` driving the exit) that the engine cannot express, and never checked.

The question is **how does a record leave `BLOCKED`?** — a transition-table question. `BLOCKED`'s only declared exit is `READY`:

```yaml
- { from: BLOCKED,  to: READY }
```

Resuming enters at `READY`, so everything from `IN_PROGRESS` onward re-traverses. A problem found during `REVIEWING` re-enters `IMPLEMENTED`: correct work is re-implemented in order to be re-reviewed.

Measured, because the engine is authoritative and `0001` did not check it:

```text
BLOCKED -> READY          legal=True   declared edge
BLOCKED -> REVIEWING      legal=False  no declared edge
BLOCKED -> TESTING        legal=False  no declared edge
BLOCKED -> IMPLEMENTED    legal=False  no declared edge
BLOCKED -> PLAN_READY     legal=False  no declared edge
```

## Options

**(a) Declare every exit per-edge, and let the caller choose.**

```yaml
  - { from: BLOCKED, to: REVIEWING }
  - { from: BLOCKED, to: TESTING }
  # ... one per non-terminal state
block:
  state: BLOCKED
  entry_states: [IN_PROGRESS, IMPLEMENTED, VALIDATED, TESTING, REVIEWING, VERIFYING, REPORTING]
```

Executable today — verified: declaring `BLOCKED -> REVIEWING` makes `check()` legal, and `CANCELLED` stays reachable from every non-terminal state, so the anti-trap invariant in `test_antitrap_invariant.py` survives intact.

`0001` rejected this on an **inverted quote**. The actual text at `state-machine.yaml:34-36` is *"The contract states its own repair topology so downstream checks do not have to hard-code it"* — the contract declares topology centrally **precisely so downstream code need not**. `repair` hard-codes it twice (`entry_states:40`, `execution_entry_states:44`) and `test_transitions.py:136-139` pins the two lists against drift. That is precedent **for** declaration, not against.

*Against:* a record blocked at `REVIEWING` can be resumed at `IMPLEMENTED`, redoing work unnecessarily. The machine permits more than is sensible.

**(b) Add a dynamic exit to `TransitionEngine`.** `exit_to: {from_field: hierarchy.blocked_from}`.

*For:* the caller cannot get it wrong; one declared mechanism rather than seven edges.
*Against:* a new feature in the transition engine, which is the component everything else trusts. Larger than the defect.

## Decision

**(a).**

It is the only option executable with the engine that exists, and the declaration it mirrors is the pattern `repair` already uses and its tests already pin against drift. (b) is the better design in the abstract and the wrong order: an engine feature is a larger change than the defect, and (a) does not foreclose it — a future (b) could subsume the declared edges without changing what callers write.

## `hierarchy.blocked_from` — assertion, not mechanism

`0001` wanted this field to *drive* the resume. It should not: the exit edge is the mechanism, and a field that must agree with it is a second source of truth that can drift.

It is still worth recording, as **an assertion of where the block actually happened**, so a wrong resume is *detectable* rather than silent:

```yaml
hierarchy:
  epic: null
  parent: null
  blocked_from: REVIEWING   # required when state == BLOCKED
```

Required-when-`BLOCKED`, not optional. Optional would let every existing and hand-edited `BLOCKED` record validate without it and silently resume at `READY` — reproducing #22 forever. The conditional is expressible: `v3.schema.json` already uses `if`/`then`/`allOf`.

**The migration cannot derive it.** Both live `BLOCKED` records (`WI-20261003-0001`, `WI-20261003-0013`) have `started_at: null`, `attempts: []`, `artifacts.commits: []` — nothing distinguishes `DRAFT` from `READY` for them. A `v3-to-v4` migration must require hand-set values, and say so.

## Consequences

- A WorkItem blocked during `REVIEWING` may be resumed at `REVIEWING`, or at any other non-terminal state. The machine allows more than is sensible; the choice is the caller's.
- `CANCELLED` remains reachable from every non-terminal state unconditionally, so **no record can be trapped regardless of where it blocks**. This is the anti-trap invariant and per-edge exits do not weaken it.
- `blocked_from` is position metadata, written on transition and **not** subject to `immutable_after` — consistent with `timestamps`.
- `hierarchy` gains a property, so `additionalProperties: false` must admit it. **`workitem/v4`, `schema_version: "4.0"`.** No contract *data* release, since `check_retroactive_criteria` is a separate decision below.

## What is deliberately NOT in this decision

**`resume_requires: unblock_decision` is struck.** `0001` required it normatively and justified it by analogy with `FAILED`'s `recovery_decision`. Nothing reads `resume_requires` anywhere — it appears once in `state-machine.yaml:53`, its own declaration — and there is no schema field for either decision, so `recovery_decision` is an unenforced annotation. Adding a second one would be a second decoration. If leaving `BLOCKED` should be a recorded act, that needs its own decision with a schema home for the record. Striking it here keeps the anti-trap invariant intact; enforcing it through `required_before` would fail `test_antitrap_invariant.py:49` and red both live records.

**`visited_states` (#26) is separate, not merged.** `0001` called them "the same change: one field, one version, one decision". They are independent, and the two fields have **opposite** semantics:

- `visited_states` — accumulating history. Correct for a monotonic freeze: "was this criterion closed at or beyond `PLAN_READY`?"
- `blocked_from` — single-valued current position.

`0001`'s own accumulation argument, generalised, would condemn the mechanism #26 needs. Accumulation is *exactly right* for the freeze, and wrong for the resume. Fixing only #26 — legalise `visited_states`, wire the call — delivers the retroactive guarantee with no `blocked_from` anywhere. They share a version bump, which is packaging, not a decision.

**`check_retroactive_criteria` is not wired here (#29).** Wiring it produces **11 false positives on 14 live records**, because it has no baseline: it checks whether the frozen state is *reachable*, never whether a criterion actually changed, so it is equivalent to `state == DRAFT`. Making it a real check needs a prior-value baseline or an edit event log — a third change, orthogonal to both. Shipping it in this release would ship a gate that is red on arrival.

## Verification before ratification

Each of these must fail before the change and pass after:

1. `BLOCKED -> REVIEWING` is legal, and `BLOCKED -> CANCELLED` remains legal from every non-terminal state.
2. A record at `BLOCKED` with `blocked_from: REVIEWING` and no such edge is **refused** — this is the assertion earning its keep.
3. A record at `BLOCKED` with no `blocked_from` is refused by the schema.
4. `test_antitrap_invariant.py` still passes — no `required_before` entry for `BLOCKED`.
5. The two live `BLOCKED` records are hand-migrated, and the migration says the value cannot be derived.

## What this decision does not settle

- Whether resuming at a state *earlier* than `blocked_from` should be permitted. It is, today. Arguably it should not, which is (b)'s real appeal.
- Whether the three `REVIEWING` records in `harkers/workhub` are in violation or represent a policy disagreement — `local_review: not_applicable` under a `normal` policy. That is a question for whoever owns those WorkItems, and it gates #29's sequencing rather than this record.