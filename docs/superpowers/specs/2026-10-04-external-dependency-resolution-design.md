# External dependency resolution — design

Date: 2026-10-04
Closes: harkers/.github#4
Related: harkers/.github#8 (closed), #15 (open), #26 (aspirational dag-scheduler)

## Problem

A WorkItem cannot declare that it is blocked by work outside this repository.

`workitem/v1.schema.json:96` constrains `dependencies[].target` to
`^WI-[0-9]{8}-[0-9]{4}$`. External dependency references are therefore
unexpressible, and the loader actively rejects them:

```python
# workitem/conformance/workitem_conformance/instances.py:26,28
ID_PATTERN  = re.compile(r"^WI-\d{8}-\d{4}$")
EXTERNAL_REF = re.compile(r"^(?!\d)(?!WI-).+")
```

`instances.py:102-110` matches anything non-`WI-` against `EXTERNAL_REF` and
raises `external-dependency`, citing this issue.

The gap is executable, not just documented:
`workitem/conformance/tests/fixtures/blocked-by-untracked-work.yaml` is the
reproduction, and `test_dependency_coverage.py:80` parametrises four rejected
spellings
(`#14`, `14`, `harkers/workhub#14`, `issue-14`).

## Three claims this issue previously contained, all wrong

Recorded because each was asserted without checking, and each would have
justified a much larger and more expensive design than the problem needs.

**1. "`dag-scheduler` handles external sentinels, so we must research it."**
It does not exist.

```text
$ find /Users/stu/projects -iname "*dag-scheduler*"; rg -l "dag.scheduler|dag_scheduler" /Users/stu/projects
(no output)
```

`dag-scheduler` is aspirational prose in `workitem/examples/feature.yaml:7,26,59`
(issue #26). No topological sort, no cycle detection, no id resolution, no
sentinel concept. There is nothing to research, and no scheduler to satisfy.

**2. "The schema forbids non-WorkItem targets while `of_type` allows
`External` — a contradiction."** There is no `of_type` field.

```text
$ grep -c of_type workitem/v1.schema.json
0
```

The field is `type`, and its enum holds *relation kinds*
(`BLOCKS`, `REQUIRES`, `OPTIONAL`, `QUALITY_GATE`, `REVIEW_GATE`), not target
kinds. `"External"` appears nowhere in the contract. So there is no
contradiction to resolve — only a missing capability. This is the smaller and
more tractable problem, and it is the one that exists.

**3. "A sentinel WorkItem would self-deadlock, because it would participate in
gates and holds."** Nothing evaluates dependencies mechanically today.

```text
$ grep -c dependenc workitem/conformance/workitem_conformance/gates.py
0
```

`policy.yaml` mentions dependencies only in prose; no `required_before` block
contains one. Nothing waits, so nothing can deadlock. The example offered in
support of this claim also contained a literal cycle, which deadlocks any
scheduler with or without sentinels — so it was never evidence for what it was
offered as evidence for.

The correction that matters: `review_policy` *is* a declared contract parameter
with `affects: gates`, and `dependencies` is not a parameter at all. This issue
is about ledger data, not about a contract parameter.

## Blast radius, measured

Before designing, the live ledger was probed. `harkers/workhub` is the only
real consumer and holds 14 records.

| Check | Result |
|---|---|
| Dependency cycles | none — the graph is a DAG |
| Unresolved `target`s | none — every target exists |
| Records in a terminal state | **none** |
| Records a new dep gate would newly block | none |

No record has reached `DONE` or `CANCELLED`, so enforcing dependencies changes
nothing for existing data. There is no migration pressure from the current
ledger.

Shape matters for a different reason. `WI-20261003-0001` requires 11 of the 13
other records, and `WI-20261003-0011` requires 8. Wide fan-in means a single
unsatisfied leaf can hold most of the ledger, which is why reachability becomes
a tested invariant below rather than an assumption.

## Decision

Approach **B**: keep `dependencies[]` internal and untouched; add a separate
top-level `external_dependencies[]`.

Rejected alternatives:

- **Polymorphic `target`** — widen the pattern to also match
  `owner/repo#123`. One list, but `target` stops being reliably a WorkItem id,
  and consumers must regex-sniff to learn which kind they hold. Spends an
  invariant that is currently free.
- **Union plus a `kind` discriminator** — as above with an explicit field.
  Same loss of `target`'s invariant, plus a redundant field.

The deciding argument is not tidiness. Internal and external dependencies
resolve by *different mechanisms*, and one list would force them to share a
field that means neither:

- an **internal** target resolves *mechanically*, against the ledger, right now;
- an **external** target can **never** be resolved by this contract — only a
  recorded assertion discharges it.

Under approach B the two never share a field, `repo` and `number` are
structured rather than parsed back out of a composite string, and all four
rejected spellings stay rejected — a cross-repo reference needs a canonical
form, which is the intent those test cases were already stating.

## Data model

`dependencies[]` is unchanged. `target` keeps `^WI-[0-9]{8}-[0-9]{4}$`.

```yaml
external_dependencies:
  - repo: harkers/workhub          # ^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$
    number: 64                     # ^[0-9]+$
    type: REQUIRES                 # same 5-value enum as dependencies[].type
    resolved_by: WI-20261003-0021  # ^WI-[0-9]{8}-[0-9]{4}$; must exist in this ledger
    note: "landed in harkers/workhub#65"   # required, free text
```

`resolved_by` is required, not optional. Absence means unresolved, so every
entry is outstanding until discharged. All five relation types require
discharge, per decision — there is no way to declare an external dependency as
informational.

`resolved_by` names a WorkItem and **not** a free-form reference, a commit, or
an `assertion` kind. Discharge must be traceable to completed work in this
ledger. This closes the escape hatch that `not_required` was in the original
issue draft: an unfalsifiable assertion is not a discharge.

`number` covers pull requests as well as issues. They share a GitHub number
space, and `harkers/workhub#64` is genuinely ambiguous between the two. The
field records the reference; disambiguating it is the author's job.

## Enforcement

One rule, applied twice:

> A dependency is satisfied only when its target is in state `DONE`. Nothing
> else satisfies it.

- **Internal** — every `dependencies[].target` must be `DONE`.
- **External** — every `external_dependencies[].resolved_by` must name a
  WorkItem that is itself `DONE`. Discharge is compositional: it is always
  traceable to real completed work.

### Why `CANCELLED` does not satisfy a dependency

`CANCELLED` is the fork, and getting it wrong reintroduces the #8 bug class.

- If `CANCELLED` **satisfies**, then cancelling one WorkItem silently releases
  everything downstream. With `0001` requiring 11 others, a single cancellation
  collapses the graph. That is a bypass.
- If it does **not** satisfy, a dependent of a cancelled WorkItem cannot reach
  `DONE`. This looks like a trap and is not: `CANCELLED` remains reachable for
  every record, unconditionally. Every WorkItem can always reach *a* terminal
  state.

The invariant:

> For every record, at least one terminal state is reachable. `DONE` is
> reachable if and only if every dependency is `DONE`.

Nothing is ever stuck. The only thing forbidden is finishing on the strength of
work that was abandoned.

### Cycle detection becomes mandatory

Enforcing dependencies makes a cycle fatal rather than merely odd. The current
ledger is a DAG, but that is a property of today's data, not of the schema.
Cycle detection therefore belongs in the ledger checker alongside the existing
`unresolved-dependency` rule (`instances.py:147`), not in prose.

## Tests

Extends the invariants added in #8.

| | Invariant |
|---|---|
| **I1** | Every non-skipped state is reachable from `DRAFT`. |
| **I2′** | Every record can reach a terminal state under every dependency configuration. |
| **I3′** | No reachable state has a structurally unsatisfiable gate. |
| **I4** | The dependency graph is acyclic. |
| **I5** | `DONE` is reachable **iff** every dependency is `DONE`. |
| **I6** | `resolved_by` always names a WorkItem that exists in the same ledger. |

I2′ generalises #8's I2. #8 checked `DONE` reachability across the
`(delivery_mode, review_policy)` cross product — contract *parameters*. I2′
treats the **ledger itself** as a variable, because dependencies are per-record
data rather than a declared parameter. This is a real expansion of the
parameter-space test: it must now enumerate ledgers, including synthetic ones
containing cycles, self-loops, and wide fan-in.

`test_dependency_coverage.py:45` asserts the `target` pattern is *still*
`^WI-...$`; it is written to fail loudly when this issue is fixed, and is
expected to be flipped as part of that work. Its four rejected-spelling cases
are retained — they remain invalid.

## Versioning

**This is `workitem/v2`, `schema_version: "2.0"`.**

Adding `resolved_by` adds a field. D8 holds that only a *data* release — one
changing the state machine or policy without adding, removing or retyping a
field — keeps `schema_version`. This adds a field, so `schema_version` moves
`1.0 → 2.0`. `contract-version.yaml` already declares `workitem/v2` at
`schema_version: "2.0"` with `released: null`, so this lands in a slot that is
reserved and empty.

**Rollout is no longer a pin change.** Every existing record is v1-shaped.
A consumer pinning v2 needs a migration; `workitem/migrations/v0.9-to-v1.yaml`
is the precedent, so `workitem/migrations/v1-to-v2.yaml` will be required.
The measured blast radius is nil (no record is terminal), so the migration is
expected to be a no-op on today's ledgers — but it must exist and be tested,
not assumed.

Rollback remains a pin change to `workitem/v1.1` + `workitem-gate/v4`.

## Sequencing

This work is a tightening — it adds a gate that will reject records that
currently pass. That is the class of change `harkers/.github`#15 governs, and
#15 is unresolved: "every live record" in the pre-tag pass is undefined
(main-only, or every branch carrying a ledger).

Sequence #4 behind #15. Cutting v2 first would repeat the failure #15 was
filed about.

## Non-goals

- **Building the scheduler.** #26 stays aspirational. Nothing here depends on
  it existing.
- **Resolving external references automatically.** The contract cannot see
  into another repository and will not pretend to. Discharge is a human
  assertion backed by a real WorkItem.
- **Rewriting `dependencies[]`.** Its `target` pattern is unchanged.
- **Deciding #4's original framing.** Where the decision belongs is settled
  above; the issue's superseded reasoning is corrected rather than inherited.