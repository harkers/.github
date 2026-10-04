"""Adoption migrations must be well-formed and must never invent a boundary field.

The contract's central safety property is that a missing confidentiality or
blast-radius field fails loudly instead of being defaulted. These tests are the
mechanical form of that promise.
"""

from __future__ import annotations

import json
import re

import jsonschema
import pytest
import yaml

from workitem_conformance.contract import load_contract, load_example

MIGRATIONS = "workitem/migrations"
BOUNDARY_FIELDS = {"scope", "privacy"}

DOCUMENTED_TRANSFORMS = {
    "set_default",
    "derive",
    "rename",
    "coerce",
    "drop",
    "require",
    "map_enum",
}


def _migration_files() -> list:
    root = load_contract().root
    return sorted(p for p in (root / MIGRATIONS).glob("*.yaml"))


def _load(path) -> dict:
    return yaml.safe_load(path.read_text())


def test_there_is_an_adoption_migration() -> None:
    assert _migration_files(), "the contract must document how pre-contract records are adopted"


@pytest.mark.parametrize("path", _migration_files(), ids=lambda p: p.name)
def test_migration_is_well_formed(path) -> None:
    doc = _load(path)
    assert doc["schema"] == "workitem-migration"
    assert doc["from"] and doc["to"], "a migration must name both versions"
    assert doc["id"], "a migration must have a stable id"
    assert doc["steps"], "a migration must have at least one step"
    ids = [s["id"] for s in doc["steps"]]
    assert len(ids) == len(set(ids)), f"duplicate step ids in {path.name}: {ids}"
    for step in doc["steps"]:
        assert {"id", "target", "transform"} <= set(step), step
        assert step["transform"] in DOCUMENTED_TRANSFORMS, step


@pytest.mark.parametrize("path", _migration_files(), ids=lambda p: p.name)
def test_filename_matches_the_versions_it_migrates(path) -> None:
    """Filenames use tag form (v1, v1.1); from/to are schema versions (1.0)."""
    doc = _load(path)

    def tag(version: str) -> str:
        return "v" + version.removesuffix(".0")

    expected = f"{tag(doc['from'])}-to-{tag(doc['to'])}.yaml"
    assert path.name == expected, f"{path.name} should be {expected}"


@pytest.mark.parametrize("path", _migration_files(), ids=lambda p: p.name)
def test_migration_is_referenced_in_the_format_doc(path) -> None:
    readme = (load_contract().root / MIGRATIONS / "README.md").read_text()
    assert path.name in readme, f"{path.name} is not documented in migrations/README.md"


@pytest.mark.parametrize("path", _migration_files(), ids=lambda p: p.name)
def test_no_migration_defaults_a_boundary_field(path) -> None:
    """The safety property: scope and privacy are never invented."""
    doc = _load(path)
    for step in doc["steps"]:
        target = step["target"].split(".")[0]
        if target not in BOUNDARY_FIELDS:
            continue
        assert step["transform"] == "require", (
            f"{path.name} step {step['id']} touches {target} with {step['transform']}; "
            "boundary fields must use `require` so the consumer fails loudly"
        )
        assert step.get("reason", "").strip(), f"{path.name} step {step['id']} must say why"


def test_every_boundary_field_the_target_schema_requires_is_required_by_some_step() -> None:
    """If v1 requires scope/privacy, the adoption path must demand them explicitly."""
    c = load_contract()
    required = set(c.schema["required"])
    doc = _load(_migration_files()[0])
    demanded = {s["target"].split(".")[0] for s in doc["steps"] if s["transform"] == "require"}
    assert (required & BOUNDARY_FIELDS) <= demanded, (
        f"v1 requires {sorted(required & BOUNDARY_FIELDS)} but the adoption migration "
        f"only demands {sorted(demanded)}"
    )


def test_the_adoption_migration_demands_every_added_required_field() -> None:
    """Anything v1 newly requires must be derived or demanded — never quietly absent."""
    c = load_contract()
    root = c.root
    adoption = root / MIGRATIONS / "v0.9-to-v1.yaml"
    assert adoption.is_file(), f"the adoption migration must exist: {adoption}"
    doc = _load(adoption)
    handled: set[str] = set()
    for step in doc["steps"]:
        handled.add(step["target"].split(".")[0])
        source = step.get("from")
        if isinstance(source, dict):
            handled.update(str(v).split(".")[0] for v in source.values())
        elif isinstance(source, str):
            handled.add(source.split(".")[0])
    # Fields v1 requires that the 0.9 shape also had need no step.
    pre_existing = {
        "schema",
        "schema_version",
        "id",
        "identity",
        "hierarchy",
        "source",
        "priority",
        "state",
        "execution",
        "dependencies",
        "acceptance_criteria",
        "verification",
        "sizing",
        "artifacts",
        "attempts",
        "completion",
        "timestamps",
    }
    # Against the v1 schema specifically, not load_contract().schema: this
    # migration's declared `to` is 1.0, so validating it against the current schema
    # made it demand a v2 field it has no business knowing about. Comparing a
    # migration to the version it targets is the whole point of its `to:` key.
    v1 = json.loads((c.root / "workitem" / "v1.schema.json").read_text())
    assert doc["to"] == str(v1["properties"]["schema_version"]["const"]), (
        f"this migration targets {doc['to']} but v1.schema.json declares "
        f"{v1['properties']['schema_version']['const']}"
    )
    unhandled = set(v1["required"]) - handled - pre_existing
    assert not unhandled, f"v1 requires {sorted(unhandled)} but no step addresses them"


def test_drop_steps_only_target_fields_v1_does_not_carry() -> None:
    c = load_contract()
    doc = _load(_migration_files()[0])
    for step in doc["steps"]:
        if step["transform"] != "drop":
            continue
        head = step["target"].split(".")[0]
        props = c.schema["properties"]
        assert head in props, step
        leaf = step["target"].split(".")[-1]
        assert leaf not in props[head].get("properties", {}), (
            f"{step['target']} still exists in v1 and must be renamed, not dropped"
        )


def test_the_adoption_migration_documents_which_records_it_applies_to() -> None:
    doc = _load(load_contract().root / MIGRATIONS / "v0.9-to-v1.yaml")
    applied = doc.get("applied_to")
    assert applied, "an adoption migration must record the records it was applied to"
    for entry in applied:
        assert re.fullmatch(r"WI-\d{8}-\d{4}", entry["id"]), entry


# --- v1 -> v2: external_dependencies -------------------------------------------


def _v1_to_v2() -> dict:
    root = load_contract().root
    return _load(root / MIGRATIONS / "v1-to-v2.yaml")


def test_v1_to_v2_exists() -> None:
    """v2 makes external_dependencies required, so a migration must exist. Without
    one, every v1-shaped record silently fails v2 validation."""
    root = load_contract().root
    assert (root / MIGRATIONS / "v1-to-v2.yaml").is_file()


def test_v1_to_v2_declares_the_versions_it_migrates() -> None:
    migration = _v1_to_v2()
    assert migration["schema"] == "workitem-migration"
    assert migration["from"] == "1.0"
    assert migration["to"] == "2.0"


def test_v1_to_v2_has_exactly_one_step_and_it_defaults_to_empty() -> None:
    steps = _v1_to_v2()["steps"]
    assert len(steps) == 1, f"expected one step, got {[s['id'] for s in steps]}"
    step = steps[0]
    assert step["target"] == "external_dependencies"
    assert step["transform"] == "set_default"
    assert step["value"] == []
    assert step["when_absent"] is True


def test_v1_to_v2_invents_nothing() -> None:
    """Every step must be an empty default. A non-empty value here would fabricate
    dependency data that the v1 record never carried."""
    for step in _v1_to_v2()["steps"]:
        assert step["transform"] == "set_default", step["id"]
        assert step["value"] == [], step["id"]
        assert step.get("when_absent") is True, step["id"]


def test_v1_to_v2_does_not_touch_dependencies_or_a_boundary_field() -> None:
    targets = {s["target"].split(".")[-1] for s in _v1_to_v2()["steps"]}
    assert "dependencies" not in targets
    assert not targets & BOUNDARY_FIELDS


def test_v1_to_v2_leaves_applied_to_empty_until_rollout() -> None:
    """Naming a record claims work that has not happened. The ledger is not
    migrated until the release, and this migration is not applied before then."""
    assert _v1_to_v2().get("applied_to") == []


def test_v2_requires_exactly_the_field_the_migration_adds() -> None:
    """The migration and the schema must agree: v2 adds one required field, and the
    migration adds exactly that one."""
    root = load_contract().root
    v1 = json.loads((root / "workitem" / "v1.schema.json").read_text())
    v2 = json.loads((root / "workitem" / "v2.schema.json").read_text())
    added_required = set(v2["required"]) - set(v1["required"])
    added_properties = set(v2["properties"]) - set(v1["properties"])
    assert added_required == added_properties == {"external_dependencies"}

    targets = {s["target"] for s in _v1_to_v2()["steps"]}
    assert targets == added_required


def test_a_v1_shaped_record_fails_v2_and_passes_v1() -> None:
    """The migration is necessary, not decorative: the gap it closes is real.

    Built from a real example then rolled back to 1.0, because examples/ is
    v2-shaped since the v2 release -- an example is no longer a v1 record.
    """
    root = load_contract().root
    v1 = json.loads((root / "workitem" / "v1.schema.json").read_text())
    v2 = json.loads((root / "workitem" / "v2.schema.json").read_text())
    record = load_example(root, "task")
    record["schema_version"] = "1.0"
    record.pop("external_dependencies", None)

    jsonschema.validate(record, v1)
    record["schema_version"] = "2.0"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(record, v2)

    migrated = dict(record, external_dependencies=[])
    jsonschema.validate(migrated, v2)
