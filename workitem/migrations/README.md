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
| `rename` | Rename a field, carrying its value |
| `drop` | Remove a field that no longer exists in the target version |
| `map_enum` | Remap an enum value through `mapping` |

Each step requires `id`, `target` and `transform`.

## Rules

- A migration MUST be idempotent: applying it twice equals applying it once.
- A migration MUST NOT invent data that cannot be derived from the source
  record. If a value cannot be defaulted, the migration declares
  `when_absent: false` and the consumer fails loudly rather than guessing.
- Contract versions are released only when a migration path exists from every
  previously released version.
- Migrating forward is the only supported direction. There is no down-migration;
  a consumer that has migrated must migrate forward again or restore from a
  snapshot taken before the migration.