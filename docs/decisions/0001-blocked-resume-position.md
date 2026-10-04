# Decision 0001: `BLOCKED` must preserve progress position

**Date:** 2026-10-04
**Status:** Proposed
**Canonical contract:** `harkers/.github` `workitem/` at tag `workitem/v3`
**Related:** harkers/.github#22, #8 (closed); harkers/workhub ADR 0005
**Scope:** contract. The schema and state machine are `harkers/.github`'s to change.

## Context

`BLOCKED` is entered from any non-terminal state and has exactly one exit:

```yaml
# workitem/state-machine.yaml
- { from: "*",      to: BLOCKED,   when: { source_not_terminal: true } }
- { from: BLOCKED,  to: READY }
```

There is no `block:` declaration, so `BLOCKED` has no `resume_state` and no
`resume_requires`. Its two siblings both declare theirs:

| | resume_state | resume_requires |
|---|---|---|
| `CHANGES_REQUIRED` (`repair`) | `IN_PROGRESS` | — |
| `FAILED` (`failure`) | `READY` | `recovery_decision` |
| **`BLOCKED`** | undeclared | undeclared |

Resuming enters at `READY`, so everything from `IN_PROGRESS` onward re-traverses.
A problem found **during `REVIEWING`** therefore re-enters `IMPLEMENTED`: correct
work is re-implemented in order to be re-reviewed. `REVIEWING` is where a review
finding or an unmet dependency most often blocks.

## Options

**(a) Record the source state on entry.** A transition into `BLOCKED` sets
`hierarchy.blocked_from`, and the exit reads it.

```yaml
block:
  state: BLOCKED
  resume_requires: unblock_decision
  entry_states: [IN_PROGRESS, IMPLEMENTED, VALIDATED, TESTING, REVIEWING, VERIFYING, REPORTING]
```

*For:* explicit, and `hierarchy` is already the home for position
(`visited_states` lives there). The record survives being read, so a reader can
see where it blocked without inferring.
*Against:* a new field on every record, and a write on transition — the first
time this contract mutates a record on a state change. `immutable_after` already
freezes `acceptance_criteria`; position metadata is not frozen, so that is
consistent, but it is a new class of behaviour.

**(b) Derive from `visited_states`.** The highest non-terminal state in the list
is where it left off. Zero new fields.

*For:* smallest possible change, and the data is already collected.
*Against:* inference, not declaration. Wrong if a state was visited on an earlier
attempt — a WorkItem that reached REVIEWING, blocked, resumed, and blocked again
would resume at the wrong place. Silent, which is the failure mode this whole
contract keeps having to guard against.

**(c) Per-edge resume, as `repair` does.** Declare `BLOCKED -> <each
non-terminal state>` with a condition.

*For:* the mechanism already proven in this file; `CHANGES_REQUIRED` does exactly
this and is commented as deliberate.
*Against:* multiplies edges, and — as `repair`'s own comment says — the contract
"does not want to hard-code" that. Following that reasoning here would be
inconsistent.

## Decision

**(a).**

`visited_states` is inference over a list that accumulates across attempts, so
(b) cannot distinguish "blocked here" from "was here once" — and resuming at the
wrong state is the same class of silent-wrong-position bug this decision exists to
remove. (c) is the mechanism `repair` uses precisely because `CHANGES_REQUIRED` is
a *repair* loop with a known small set of entry states; `BLOCKED` is entered from
anywhere, so the edge set would be unbounded.

The cost of (a) is a new field and a write on transition. That is worth paying:
position is the thing being lost, and an inferred position is not a position.

### Constraint

`resume_requires: unblock_decision`. Leaving `BLOCKED` should be a recorded act,
the way leaving `FAILED` requires a `recovery_decision`. Without it, a block is
as cheap to clear as to enter, and a blocked WorkItem becomes a state that can be
left silently — which is how `WI-20261003-0005`'s `dependencies: []` survived.

## Consequences

- A WorkItem blocked during `REVIEWING` resumes at `REVIEWING`.
- `blocked_from` is position metadata, not record content: it is written on
  transition and is **not** subject to `immutable_after`.
- Cycle detection is unaffected — `blocked_from` is not a dependency edge.
- The reachability invariant is unchanged. `CANCELLED` remains the unconditional
  exit, so no record is ever trapped regardless of where it blocks.
- **Not a data release.** Adding `hierarchy.blocked_from` is adding a field, which
  D8 excludes. This is `workitem/v4`, `schema_version: "4.0"`.

## Interaction with the external-dependency work

`workitem/v3` lets an external dependency discharge by attestation, so a WorkItem
blocked on untracked external work can now legitimately sit in `BLOCKED`. That
makes this decision *more* load-bearing than it was: attested blockers are
expected to be common, and each one is a `BLOCKED` whose position must survive.

This is the second time `BLOCKED`'s lack of a declared resume has mattered. The
first was found while implementing external dependencies; it was left filed as
#22 rather than fixed, because the fix is a schema change and shipping one
contract decision while a parallel ADR was proposing the opposite of another is
how `harkers/workhub` ADR 0005 and `workitem/v2.1` came to contradict each other.

## What this decision does not settle

- Whether `unblock_decision` is a recorded field or a gate on the exit edge.
- Whether `FAILED` should also preserve position. It has the same position loss,
  but it is at least declared and gated.
- Whether the anti-trap invariant needs the executable pin `test_antitrap_invariant.py`
  now provides, which it does.
