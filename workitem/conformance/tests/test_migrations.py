"""Adoption migrations must be well-formed and must never invent a boundary field.

The contract's central safety property is that a missing confidentiality or
blast-radius field fails loudly instead of being defaulted. These tests are the
mechanical form of that promise.
"""

from __future__ import annotations

import re

import pytest
import yaml

from workitem_conformance.contract import load_contract

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
    doc = _load(_migration_files()[0])
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
    unhandled = set(c.schema["required"]) - handled - pre_existing
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
    doc = _load(_migration_files()[0])
    applied = doc.get("applied_to")
    assert applied, "an adoption migration must record the records it was applied to"
    for entry in applied:
        assert re.fullmatch(r"WI-\d{8}-\d{4}", entry["id"]), entry
