# Canonical WorkItem Contract — Design

- **Date:** 2026-10-03
- **Source issue:** `harkers/.github` #1 — *Canonical WorkItem contract and inherited task scaffolding across repositories*
- **Scope:** sub-projects **A+B** — vocabulary and state reconciliation, then the contract artifacts
- **Status:** design approved; implementation not yet planned
- **Canonical rule:** **No WorkItem → No Work.**

---

## 1. Summary

`harkers/.github` becomes the control plane for a single canonical **WorkItem**
contract. A WorkItem is the only authoritative description of a unit of
engineering work. Everything else — `TODO.md`, dashboards, GitHub issues, agent
task lists, completion packets — is either a projection of WorkItems or an
implementation artifact linked to one.

This document covers **only** sub-projects A and B: deciding the vocabulary and
lifecycle, and emitting the contract artifacts. It changes no production code.
Everything that enforces the contract is a follow-on issue.

---

## 2. Context: what already exists

Issue #1 was written as if the estate had no task representation. It has three,
and two of them were deliberate. Any design that ignores this will collide.

### 2.1 Three state machines exist today

| Source | States | Form | Status |
|---|---|---|---|
| `workhub/docs/process/task-state-machine.md` | 18 happy + `BLOCKED`, `FAILED` | prose, with gate definitions | live, referenced by `workhub/AGENTS.md` |
| `workhub/TODO.md` | 20 | hand-maintained markdown + inline YAML | live, **self-declared canonical** |
| `agent-fabric` `persistence/models/task.py` | 17 | `TaskState` StrEnum + `check_task_transition()` | **coded**, with an illegal-transition guard |

Issue #1 proposes a fourth (10 happy + 4 exceptional).

The 20 states in `workhub/TODO.md` are:

```text
DRAFT SPEC_READY PLAN_READY READY IN_PROGRESS TASK_IMPLEMENTED TASK_VALIDATED
COMMITTED PR_DRAFT IMPLEMENTATION_COMPLETE TESTING REVIEW_LOCAL REVIEW_CLOUD
SPECIALIST_REVIEW VERIFYING REPORTING PR_READY BLOCKED FAILED DONE
```

The 17 in `agent-fabric` are:

```text
CREATED PLANNED READY LEASED EXECUTING VALIDATING QUALITY_GATE REVIEW BLOCKED
STALE REMEDIATING COMPLETE CANCELLED FAILED FAILED_REMEDIATED NEEDS_HUMAN
HUMAN_DECISION
```

### 2.2 Two of issue #1's proposals contradict accepted decisions

**Storage.** Issue #1 makes YAML files canonical
(`.workhub/workitems/WI-*/workitem.yaml`). `agent-fabric`'s
`docs/adr/0003-postgresql-authoritative-state.md` is **Accepted** and states the
opposite for that estate: markdown/YAML/JSON artifacts are read-only
projections, never a second source of truth, with optimistic CAS on a `version`
column at `SERIALIZABLE` isolation.

**Delivery states.** Issue #1's 10-state ladder drops `COMMITTED`, `PR_DRAFT`,
`IMPLEMENTATION_COMPLETE` and `PR_READY`, which `workhub/AGENTS.md` explicitly
mandates as part of the required delivery flow.

### 2.3 Two of issue #1's policies already exist in agent-fabric

- **Sizing/decomposition** is already mechanical: `workers.yaml` `execution:`
  bounds reject oversized packets with `ESCALATE`; packets are capped at ≤6
  scope paths and ≤600 characters of completion criteria.
- **Evidence-based completion** is already doctrine: "a `COMPLETE` status means
  nothing until evidence is checked", plus `workhub/AGENTS.md`'s ten-item
  completion rule.

### 2.4 A third contract location, with fields issue #1 omits

`agent-fabric/src/agent_fabric/contracts/packet.py` defines a strict pydantic
`WorkPacket`: `task_id`, `capability`, `objective`, `worker`, `scope`
(traversal-safe `allowed_paths`), `constraints`, `known_context`,
`required_output`, `completion_criteria`, `escalate_if`, `privacy`
(`PUBLIC | INTERNAL | CLIENT_CONFIDENTIAL | LOCAL_ONLY`), `worktree`, `retries`,
`retry_guidance`.

It overlaps issue #1's proposed WorkItem on `id`, acceptance criteria, worker
role, max attempts and worktree — and carries `privacy`, `scope` and
`escalate_if`, which issue #1's schema omits. `privacy` in particular is
load-bearing: this machine's operating rules forbid client-confidential prompts
from reaching cloud models, and `WorkPacket.privacy.level` is where that
boundary is currently enforced.

### 2.5 `TODO.md` claims the opposite authority to the one issue #1 assigns it

`workhub/TODO.md` opens:

> This file is the canonical execution queue for WorkHub. […] This file defines
> **execution order, readiness, dependencies and current delivery state**.

Issue #1 requires `TODO.md` to become a generated, explicitly non-authoritative
projection. That inversion is the single highest-value change in the issue, and
it cannot be specified until the storage substrate is settled.

---

## 3. Decisions taken

These were resolved during design and are the basis of everything below.

| # | Decision |
|---|---|
| D1 | **The database is authoritative; files are projections.** Reverses issue #1's file-canonical proposal. Does not contradict ADR-0003, which claims authority *for Agent Fabric*, not for workhub's domain. |
| D2 | **Sub-projects A+B land first** — vocabulary and state reconciliation, then contract artifacts. Issue #1 schedules the contract first and the tooling eighth; that order is inverted. |
| D3 | **workhub owns the WorkItem ledger.** agent-fabric holds a read-only projection of execution-relevant fields for its dispatcher hot path. |
| D4 | **WorkItem and Run are different objects, not competing descriptions.** There is no state mapping table between them, because they measure different things. |
| D5 | **WorkItem owns `scope`, `privacy` and acceptance criteria.** agent-fabric's `WorkPacket` becomes an artifact generated from a WorkItem at dispatch time. |
| D6 | **Definition-only change-set.** No production code in this PR; enforcement is follow-on issues. |

---

## 4. Goals and non-goals

### Goals

1. One vocabulary and one canonical lifecycle for engineering work, with the
   relationship to agent execution stated explicitly rather than left implicit.
2. A versioned, machine-checkable contract that downstream repositories consume
   without being able to redefine.
3. A conformance suite that validates the contract standalone, before any
   consumer exists.
4. An explicit migration path from every existing representation.

### Non-goals

- Not an independent project-management database.
- Not a change to agent-fabric's runtime state authority (ADR-0003 stands).
- Not a rename of agent-fabric's `Task`/`TaskState`/`WorkPacket` symbols.
- Not enforcement. No gate in this change-set blocks any real work.
- Not `TODO.md` migration (sub-project D).
- Not the OpenCode intake gate (sub-project E).

---

## 5. Scope of this change-set

### In

| Artifact | Repo |
|---|---|
| `workitem/v1.schema.json` | `.github` |
| `workitem/state-machine.yaml` | `.github` |
| `workitem/policy.yaml` | `.github` |
| `workitem/sizing-policy.yaml` | `.github` |
| `workitem/README.md` | `.github` |
| `workitem/examples/{task,bug,feature,investigation}.yaml` | `.github` |
| `workitem/conformance/` | `.github` |
| `workitem/migrations/` | `.github` |
| ADR: WorkItem ↔ Run ↔ WorkPacket | `agent-fabric` |
| Decision record: WorkItem ledger ownership | `workhub` |

### Out

| Deferred | Becomes |
|---|---|
| Any workhub domain model | workhub #13 |
| `workhub work` CLI | sub-project C |
| `TODO.md` migration and demotion | sub-project D |
| OpenCode intake gate and global policy | sub-project E |
| PR/CI enforcement, Ranger, code generation | follow-on issues |

---

## 6. Entity model

```text
WorkItem ────── 1 ────── N ─────── Run ────── 1 ────── 1 ────── WorkPacket
 workhub                    agent-fabric                 agent-fabric
 authoritative              authoritative (ADR-0003)     generated artifact
 definition + delivery      one attempt                  bounded worker envelope
 lifecycle                  LEASED / EXECUTING /        privacy + scope +
                            STALE / NEEDS_HUMAN          criteria copied in
```

Three objects at three altitudes:

- **WorkItem** — *what work must happen.* Definition and delivery maturity.
- **Run** — *one attempt at executing it.* Lease, liveness, retry and
  human-escalation state.
- **WorkPacket** — *the bounded envelope handed to a worker.* Generated, not
  authoritative; carries `work_item_id` plus the fields a worker needs in
  isolation.

### Invariants

1. **A Run never sets WorkItem state.** WorkItem state advances only when
   workhub evaluates a gate against recorded evidence. This is what keeps
   `IMPLEMENTED != DONE` honest across the repository boundary.
2. **Every WorkPacket is generated from a WorkItem** and carries a resolvable
   `work_item_id`. An unresolvable `work_item_id` is a validation failure, not
   a warning.
3. **A packet may narrow `scope` but never widen `privacy`.** `CLIENT_CONFIDENTIAL`
   on a WorkItem forces `CLIENT_CONFIDENTIAL` on every packet beneath it.
4. **Run state is never copied onto a WorkItem.** The WorkItem records
   `attempts[].run_id` and `outcome` only. Copying Run state in would recreate
   the competing representation this contract exists to prevent.
5. **There is no WorkItem ↔ Run state mapping table**, and none may be added.
   The two measure different things; a mapping would imply they are the same.

### Naming

agent-fabric's `Task` is a `Run`; `TaskState` is the Run lifecycle; `WorkPacket`
is that Run's envelope. This alias is documented once. No rename occurs in this
change-set — that touches jury-reviewed code and belongs in a follow-on.

---

## 7. Canonical WorkItem lifecycle

16 happy-path states, 4 exceptional. Total 20.

```text
DRAFT → SPEC_READY → PLAN_READY → READY → IN_PROGRESS
      → IMPLEMENTED → VALIDATED → COMMITTED → PR_DRAFT
      → IMPLEMENTATION_COMPLETE → TESTING → REVIEWING
      → VERIFYING → REPORTING → PR_READY → DONE
```

### Exceptional states

```text
ANY (non-terminal) → BLOCKED;            BLOCKED → READY
execution states   → FAILED;             FAILED  → READY after a recovery decision
ANY (non-terminal) → CANCELLED           (terminal)
VALIDATED | TESTING | REVIEWING | VERIFYING → CHANGES_REQUIRED
CHANGES_REQUIRED   → IN_PROGRESS
```

### Changes from workhub's ladder

| Change | Reason |
|---|---|
| `TASK_IMPLEMENTED` → `IMPLEMENTED` | The `TASK_` prefix is redundant once the object is a WorkItem. |
| `TASK_VALIDATED` → `VALIDATED` | As above. |
| `REVIEW_LOCAL`, `REVIEW_CLOUD`, `SPECIALIST_REVIEW` → `REVIEWING` | The existing ladder runs them as a fixed chain, but its own document makes all three conditional. A low-risk task would traverse `REVIEW_CLOUD` and `SPECIALIST_REVIEW` vacuously. Review depth becomes policy data, not control flow. |
| Six implicit repair edges → `CHANGES_REQUIRED` → `IN_PROGRESS` | `TASK_VALIDATED \| TESTING \| REVIEW_* \| VERIFYING → IN_PROGRESS` silently loses how many rounds occurred. A real state makes the round count durable in the event stream, which is what the audit and metrics requirements need. |

### The graph is parameterised, not a chain

Two WorkItem fields change which edges are legal.

**`verification.review_policy: low_risk | normal | security_sensitive | high_risk`**
determines which review evidence must be `passed` before `REVIEWING → VERIFYING`
is legal:

| Policy | Required review evidence |
|---|---|
| `low_risk` | `local_review` |
| `normal` | `local_review`, `cloud_review` |
| `security_sensitive` | `local_review`, `cloud_review`, `specialist_review` |
| `high_risk` | `local_review`, `cloud_review`, `specialist_review` |

**`delivery.mode: pull_request | branch_only | none`** determines which delivery
edges are reachable. Under `none`, `COMMITTED`, `PR_DRAFT`,
`IMPLEMENTATION_COMPLETE` and `PR_READY` are unreachable and the ladder
short-circuits `VALIDATED → TESTING`. Without this, an investigation or
documentation WorkItem would be forced through a vacuous PR ceremony.

### Gate preconditions

Legal transition is evaluated against
`(current_state, evidence, review_policy, delivery.mode)` — never state alone.

| State | Precondition to enter |
|---|---|
| `SPEC_READY` | Goals, non-goals, interfaces, failure modes and acceptance criteria defined. |
| `PLAN_READY` | Bounded implementation tasks and validation steps exist. |
| `READY` | `acceptance_criteria` non-empty, every description measurable; `sizing` estimated; dependencies resolved or recorded as blocked; `scope` and `privacy` set. |
| `IMPLEMENTED` | Scoped implementation changes exist. |
| `VALIDATED` | Scoped validation passed. |
| `COMMITTED` | Approved changes committed atomically. *(skipped when `delivery.mode = none`)* |
| `PR_DRAFT` | Branch pushed and a draft PR exists using the repository PR template. *(skipped when `delivery.mode = none`)* |
| `IMPLEMENTATION_COMPLETE` | All planned implementation subtasks committed to the PR branch. *(skipped when `delivery.mode = none`)* |
| `TESTING` | Independent/required tests are exercising completion claims. |
| `REVIEWING` | All review evidence required by `review_policy` is `passed`. |
| `VERIFYING` | Material completion claims checked against resolved evidence. |
| `REPORTING` | Completion packet produced. |
| `PR_READY` | All configured gates passed; the draft PR may be marked ready. *(skipped when `delivery.mode = none`)* |
| `DONE` | Every `required` verification is `passed`, the completion packet exists, and `delivery.mode` prerequisites are met. Workers cannot self-transition to `DONE`. |

---

## 8. WorkItem schema surface

Issue #1's proposed shape is internally inconsistent: it defines
`verification: {required: [tests, local_review]}` as a bare list, then later
shows `verification.tests.status` and `.evidence`. Both cannot hold. The map
form is adopted, because it carries the evidence issue #1 requires.

```yaml
schema: workitem
schema_version: "1.0"          # contract version this record was written against

id: WI-20261003-0001           # CLI-generated, immutable, no type encoded

identity:
  type: TASK | BUG | FEATURE | INVESTIGATION | CHORE | DOCS | SPIKE | REFACTOR
  title: str
  description: str

hierarchy:
  epic: str | null
  parent: str | null

source:
  type: user_request | github_issue | review_finding | bug_report | decomposition | imported
  issue: int | null
  requested_by: str
  created_by: str

priority: HIGH | MEDIUM | LOW
state: <canonical state enum>

scope:                          # promoted from WorkPacket
  allowed_paths: [str]          # traversal-safe; same semantics as Scope.allows()
  denied_paths: [str]
privacy:                        # promoted from WorkPacket
  level: PUBLIC | INTERNAL | CLIENT_CONFIDENTIAL | LOCAL_ONLY
  network: allowed | denied

delivery:
  mode: pull_request | branch_only | none
  branch: str | null            # wi/WI-20261003-0012/dependency-resolver
  pull_request: int | null

execution:
  worker_role: str | null
  capability: str | null
  preferred_model: str | null
  resource_class: auto | str
  max_attempts: int

dependencies:
  - target: WI-…
    type: BLOCKS | REQUIRES | OPTIONAL | QUALITY_GATE | REVIEW_GATE

acceptance_criteria:            # must be non-empty before READY
  - id: AC-001
    description: str            # must be measurable — see below
    status: pending | met | unmet | waived
```

**"Measurable" is defined, not left to judgement.** An acceptance criterion is
measurable when a verifier other than its author can decide it from recorded
evidence, without asking the author's opinion. Concretely it names an observable
condition — a command and its expected result, an artifact and its expected
property, or a named check. "Code is clean", "works as expected" and "handles
the error case" are not measurable. This is what makes the `READY` gate
machine-decidable rather than a reviewer's opinion.

verification:
  review_policy: low_risk | normal | security_sensitive | high_risk
  required: [tests, local_review, cloud_review, specialist_review]
  tests:           { status: pending | passed | failed | not_applicable, evidence: [...] }
  local_review:    { status: …, evidence: [{ reviewer, report }] }
  cloud_review:    { status: …, evidence: [...] }
  specialist_review: { status: …, evidence: [...] }

sizing:
  estimated_complexity: SMALL | MEDIUM | LARGE | XL   # band; must agree with tokens
  estimated_context_tokens: int                         # the measure; the band derives from it

artifacts:
  specification: str | null
  implementation_plan: str | null
  commits: [str]
  completion_packet: str | null

attempts:                       # WorkItem's own record of Runs; never Run state
  - { run_id: str, dispatched_at: ts, outcome: str }

completion:
  status: incomplete | complete
  packet: str | null

timestamps:
  created_at: ts | null
  updated_at: ts | null
  started_at: ts | null
  completed_at: ts | null
```

### Corrections to issue #1

1. **`privacy` and `scope` added.** Without them the contract drops the
   confidentiality boundary `WorkPacket` already enforces, and a WorkItem could
   be dispatched at the wrong privacy level with nothing catching it.
2. `sizing.decomposition_required` is removed — it is derived, not stored.
   Store `estimated_context_tokens`; compute the band and the decomposition flag
   from `sizing-policy.yaml`. A stored boolean drifts from its own estimate as
   soon as the estimate is edited, which is the `TODO-003`–`TODO-008` failure
   already recorded in workhub's history (states read `PLAN_READY` with no spec
   or plan). For the same reason `estimated_complexity` is retained only as a
   human-readable band and must agree with `estimated_context_tokens` when both
   are present.
3. **`dependencies` gets a shape.** Issue #1 declares five relationship types
   and then writes `dependencies: []`.
4. **Run state is not stored on the WorkItem** — only `attempts[].run_id` and
   `outcome`.
5. **`hierarchy.sprint` dropped.** No sprints in this workflow.
6. **`identity.type` kept as metadata only**, per issue #1's own identifier
   policy: mutable semantics must not be encoded in an immutable identifier.

---

## 9. Contract artifacts, versioning, pinning

### Layout

```text
workitem/
├── v1.schema.json
├── state-machine.yaml
├── policy.yaml
├── sizing-policy.yaml
├── README.md
├── examples/
│   ├── task.yaml
│   ├── bug.yaml
│   ├── feature.yaml
│   └── investigation.yaml
├── conformance/
└── migrations/
```

### The load-bearing rule: nothing restates the ladder

`state-machine.yaml` is the single definition of the lifecycle. workhub's future
domain models and CLI **load** it; they do not declare a parallel Python enum.
That is how "downstream repositories cannot redefine the state machine" becomes
mechanically true without a code generator. agent-fabric's `TaskState` is
legitimately exempt — it is the Run axis.

`sizing-policy.yaml` is written as the **canonical statement that agent-fabric's
`workers.yaml` bounds implement**, not as a third copy of them. Where the two
disagree, `workers.yaml` is the enforcement point and this contract records the
intent.

### Versioning and pinning

Contract versions are git tags in `harkers/.github`:

```text
workitem/v1
workitem/v1.1
workitem/v2
```

Consumers resolve a **pinned ref**, never an unpinned `main`:

```text
workhub contract sync --ref workitem/v1
```

The local cache retains provenance, as issue #1 requires:

```yaml
repo: harkers/.github
requested_ref: workitem/v1
resolved_sha: <40-hex>
path: workitem/v1.schema.json
contract_version: v1
fetched_at: <ts>
checksum: <sha256>
```

Every WorkItem carries the `schema_version` it was written against, so
`workhub contract migrate --to v1.1` walks existing records deterministically.
Migrations are declarative files in `migrations/`, not code. GitHub's default
community-file inheritance is not relied upon for schema resolution; the
WorkHub integration resolves the contract explicitly.

### The event stream

Every material lifecycle change emits an append-only event. This is workhub's
existing typed event model (`workhub` issue #14), not a parallel mechanism; the
WorkItem contract defines which events are mandatory and what payload each
carries. Transitions are stored event-sourced with current state derived from
the log, matching agent-fabric's transition-log discipline.

---

## 10. Conformance suite

Runs standalone. Neither workhub nor agent-fabric has the domain models yet, so
the suite must not depend on either. It asserts:

**Schema**

1. All four examples validate against `v1.schema.json`.
2. Every example's declared state is reachable from `DRAFT` through legal edges.
3. Invalid fixtures are rejected: empty `acceptance_criteria` at `READY`, missing
   `privacy`, missing `scope`, unknown `state`, unknown `dependencies[].type`,
   mutable type encoded in the identifier, an unmeasurable acceptance criterion,
   and a `sizing` band that disagrees with `estimated_context_tokens`.

**Transitions**

4. Every edge in `state-machine.yaml` is legal.
5. Every non-edge is rejected. Specifically `READY → DONE`, `IN_PROGRESS → DONE`
   and `IMPLEMENTED → DONE` are all refused.
6. `CHANGES_REQUIRED → IN_PROGRESS` is the only route back into execution, so no
   state can be re-entered from `DONE`.
7. Legality is evaluated against `(state, evidence, review_policy, delivery.mode)`,
   not state alone — `REVIEWING → VERIFYING` is refused under `high_risk` while
   `cloud_review` is `failed`.
8. Under `delivery.mode = none`, `COMMITTED`, `PR_DRAFT`,
   `IMPLEMENTATION_COMPLETE` and `PR_READY` are unreachable.

**Gates**

9. `READY` is refused when `acceptance_criteria` is empty.
10. `DONE` is refused unless every `required` verification is `passed` **and** a
    completion packet exists.
11. Success cannot be defined retrospectively: an AC added to a WorkItem already
    past `IMPLEMENTED` fails validation.

**Internal consistency**

12. Every `dependencies[].type` is declared in the schema.
13. Every state named in `policy.yaml` exists in `state-machine.yaml`.
14. Every state in `state-machine.yaml` is documented in the README.

---

## 11. Reconciliation mappings

### workhub's 20 → canonical 20

| workhub | Canonical | Note |
|---|---|---|
| `TASK_IMPLEMENTED` | `IMPLEMENTED` | rename |
| `TASK_VALIDATED` | `VALIDATED` | rename |
| `REVIEW_LOCAL` | `REVIEWING` | `review_policy` recorded per WorkItem |
| `REVIEW_CLOUD` | `REVIEWING` | ditto |
| `SPECIALIST_REVIEW` | `REVIEWING` | ditto |
| all other states | unchanged | |
| `TASK_VALIDATED \| TESTING \| REVIEW_* \| VERIFYING → IN_PROGRESS` | `→ CHANGES_REQUIRED → IN_PROGRESS` | round count becomes durable |

Because the state names carry over, `TODO.md` migration in sub-project D is
mechanical rather than a judgement call.

### agent-fabric's 17 → not mapped

Documented once as `Task == Run`, `TaskState` = Run lifecycle, `WorkPacket` =
that Run's envelope. **No mapping table**, per invariant 5.

### Ranger

`Ranger` exists only as a planned service in agent-fabric's Dockerised topology
(`agent-api, scheduler, worker-manager, ranger, reporter`). There is no code.
Issue #1's stale/stalled-detection phase targets something unbuilt, so it
becomes a follow-on that depends on agent-fabric's service work landing first.

---

## 12. Follow-on issues

None of these are in this change-set.

| Repo | Issue |
|---|---|
| `agent-fabric` | `WorkPacket` gains a required `work_item_id`; is generated from a WorkItem at dispatch; `privacy`/`scope` copied, never widened. |
| `agent-fabric` | Alias `Task` → `Run`; document `TaskState` as the Run lifecycle. |
| `agent-fabric` | Read projection of execution-relevant WorkItem fields into Postgres. |
| `workhub` | #13 domain models must **load** `state-machine.yaml`, not restate it. |
| `workhub` | `workhub contract sync` / `migrate` with provenance cache. |
| `workhub` | `workhub work` CLI — sub-project C. |
| `workhub` | Migrate and demote `TODO.md` — sub-project D. |
| `opencode-config` | Intake gate and global policy — sub-project E. |
| `.github` | PR/CI WorkItem enforcement; branch, commit-trailer and PR-template wiring. |
| `.github` | Ranger observability, after the service exists. |

---

## 13. Source-of-truth table

To be reproduced in `workitem/README.md`.

| Thing | Status |
|---|---|
| WorkItem | canonical unit of work |
| WorkItem lifecycle (`state-machine.yaml`) | canonical dependency/DAG definition |
| WorkItem event | canonical execution/history record |
| Run / `TaskState` | canonical execution state (agent-fabric, ADR-0003) |
| WorkPacket | generated dispatch artifact |
| `TODO.md` | generated projection, non-authoritative |
| GitHub Issue | external representation and link |
| PR | implementation artifact |
| Dashboard | projection |
| Reporter output | projection and evidence consumer |
| Completion packet | generated WorkItem evidence |

There must be no competing canonical TODO or task representation.

---

## 14. Risks

| Risk | Mitigation |
|---|---|
| The contract is written but never enforced, becoming a fourth description | Sub-projects C and D are pre-scoped. This change-set deliberately ships no enforcement; the follow-on list is the commitment. |
| `state-machine.yaml` drifts from workhub's existing `docs/process/task-state-machine.md` | That document is replaced by a pointer to the contract in the same change-set. |
| `review_policy` and `delivery.mode` reintroduce the vacuous-pass problem they were meant to solve | Conformance assertions 7 and 8 test both directions: over- and under-requiring. |
| agent-fabric's `workers.yaml` sizing bounds contradict `sizing-policy.yaml` | `sizing-policy.yaml` is written as the statement those bounds implement; disagreement is resolved in agent-fabric, not by forking the contract. |
| A 16-state ladder is too fine-grained to use | The gate table (§7) is the enforcement surface; states exist to make gates nameable, and `CHANGES_REQUIRED` collapses the six repair edges that previously made the graph hard to reason about. Revisit after sub-project C. |

---

## 15. Open questions deferred to later sub-projects

- Whether sizing policy should additionally drive model routing (today it only
  gates decomposition).
- The exact DAG semantics for the `QUALITY_GATE` and `REVIEW_GATE` dependency
  edge types. `BLOCKS`, `REQUIRES` and `OPTIONAL` are unambiguous; the two gate
  types need semantics before the DAG is load-bearing (workhub issue #26).

These are recorded so they are not silently decided in sub-project C. The
ledger-ownership question is **not** open: decision D3 settles it.