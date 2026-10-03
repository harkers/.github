# Contract migrations

A migration is a **declarative YAML file**. Migrations are never code: a
consumer must be able to apply one without executing anything from this
repository.

## File naming

```text
v1-to-v1.1.yaml
v1.1-to-v2.yaml
```

## Format

```yaml
schema: workitem-migration
from: "1.0"
to: "1.1"
id: 2026-10-03-add-network-privacy
description: Adds privacy.network so a WorkItem can declare egress policy.

steps:
  - id: default-network
    target: privacy.network
    transform: set_default
    value: denied
    when_absent: true
```

## Required keys

| Key | Meaning |
| --- | --- |
| `schema` | must be `workitem-migration` |
| `from` | source `schema_version` |
| `to` | target `schema_version` |
| `id` | stable migration identifier |
| `steps` | ordered list of `transform` operations |

## Transform operations

| `transform` | Behaviour |
| --- | --- |
| `set_default` | Set `value` when the field is absent (`when_absent: true`) |
| `derive` | Compute `target` from other fields via a named `rule` |
| `rename` | Move a field's value to a new `target`, optionally `coerce`d |
| `coerce` | Change a value's type without changing its meaning (`url_to_number`) |
| `drop` | Remove a field that no longer exists in the target version |
| `require` | **Fail loudly** unless a human supplies the value. Never invents one |
| `map_enum` | Remap an enum value through `mapping` |

Each step requires `id`, `target` and `transform`.

## Rules

- A migration MUST be idempotent: applying it twice equals applying it once.
- A migration MUST NOT invent data that cannot be derived from the source
  record. Where a value cannot be derived, the step uses `require` and the
  consumer fails loudly rather than guessing. **`require` is the correct answer
  for a confidentiality, authorisation or blast-radius field** — a default there
  is a silent widening of the boundary the field exists to hold.
- Contract versions are released only when a migration path exists from every
  previously released version.
- Migrating forward is the only supported direction. There is no down-migration;
  a consumer that has migrated must migrate forward again or restore from a
  snapshot taken before the migration.

## Adoption migrations

A shape that shipped before the contract existed is treated as version `0.9`,
even if it labelled itself with the current version string. Two shapes must never
share a version number.

| Migration | From | To | Purpose |
| --- | --- | --- | --- |
| [`v0.9-to-v1.yaml`](v0.9-to-v1.yaml) | 0.9 | 1.0 | Adopts `harkers/workhub`'s `.workhub/workitems` compatibility protocol to contract v1 |