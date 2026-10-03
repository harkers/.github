"""Version pinning, provenance records and the migration file format."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator

from workitem_conformance.contract import load_contract

SHA = "a" * 40
CHECKSUM = "b" * 64


def _provenance_schema() -> dict:
    return json.loads((load_contract().root / "workitem" / "provenance.schema.json").read_text())


def _record(**overrides: Any) -> dict[str, Any]:
    base = {
        "repo": "harkers/.github",
        "requested_ref": "workitem/v1",
        "resolved_sha": SHA,
        "path": "workitem/v1.schema.json",
        "contract_version": "v1",
        "fetched_at": "2026-10-03T12:00:00Z",
        "checksum": CHECKSUM,
    }
    base.update(overrides)
    return base


def test_provenance_schema_is_valid() -> None:
    Draft202012Validator.check_schema(_provenance_schema())


def test_a_resolved_contract_provenance_record_validates() -> None:
    errors = list(Draft202012Validator(_provenance_schema()).iter_errors(_record()))
    assert errors == [], [e.message for e in errors]


@pytest.mark.parametrize(
    "override",
    [
        {"requested_ref": "main"},
        {"requested_ref": "HEAD"},
        {"resolved_sha": "not-a-sha"},
        {"checksum": "xyz"},
        {"contract_version": "1.0"},
        {"repo": "someone/else"},
    ],
)
def test_provenance_rejects_unpinned_or_malformed_records(override: dict[str, Any]) -> None:
    errors = list(Draft202012Validator(_provenance_schema()).iter_errors(_record(**override)))
    assert errors, f"{override} was accepted but should be rejected"


def test_contract_version_matches_the_schema() -> None:
    c = load_contract()
    tags = {v["tag"] for v in c.version["versions"]}
    assert f"workitem/{c.version['current']}" in tags, (
        f"current {c.version['current']} has no matching tag in {sorted(tags)}"
    )
    # The release tag (v1) and the schema version (1.0) are different namespaces,
    # mapped by the versions list. Assert the mapping, not string equality.
    declared = c.schema["properties"]["schema_version"]["const"]
    current_tag = f"workitem/{c.version['current']}"
    mapped = [v["schema_version"] for v in c.version["versions"] if v["tag"] == current_tag]
    assert mapped == [declared], (
        f"{current_tag} maps to schema_version {mapped}, v1.schema.json says {declared}"
    )


def _ordering(tag: str) -> tuple[int, ...]:
    return tuple(int(p) for p in tag.removeprefix("workitem/v").split("."))


def test_every_declared_version_carries_a_tag_and_schema_version() -> None:
    c = load_contract()
    for entry in c.version["versions"]:
        assert entry["tag"].startswith("workitem/"), entry
        assert entry["schema_version"], entry
        assert re.fullmatch(r"workitem/v[0-9]+(\.[0-9]+)*", entry["tag"]), entry


def test_only_the_current_and_past_versions_are_released() -> None:
    """A declared-but-unreleased version must not be advertised as pinnable."""
    c = load_contract()
    current = _ordering(f"workitem/{c.version['current']}")
    for entry in c.version["versions"]:
        order = _ordering(entry["tag"])
        if order < current:
            assert entry["released"], f"{entry['tag']} is superseded but has no release date"
        elif order == current:
            assert entry["released"], f"{entry['tag']} is current but unreleased"
        else:
            assert entry["released"] is None, (
                f"{entry['tag']} is newer than current but claims a release date"
            )


def test_resolution_strategy_is_a_pinned_tag_with_provenance() -> None:
    c = load_contract()
    resolution = c.version["resolution"]
    assert resolution["repository"] == "harkers/.github"
    assert resolution["strategy"] == "pinned_git_tag"
    assert resolution["cache"]["required"] is True
    assert resolution["cache"]["retain_provenance"] is True


def test_the_provenance_schema_is_where_resolution_says_it_is() -> None:
    c = load_contract()
    named = c.version["resolution"]["cache"]["provenance_schema"]
    path = c.root / named
    assert path.is_file(), f"{named} does not exist"


def test_the_migration_format_is_documented() -> None:
    readme = (load_contract().root / "workitem" / "migrations" / "README.md").read_text()
    for token in ("from", "to", "steps", "id", "transform"):
        assert token in readme, token


def test_documented_migration_example_parses_as_yaml() -> None:
    """The format doc must not drift from a migration that actually loads."""
    readme = (load_contract().root / "workitem" / "migrations" / "README.md").read_text()
    blocks = re.findall(r"```yaml\n(.*?)```", readme, re.DOTALL)
    assert blocks, "the format documentation must contain a worked example"
    parsed = [yaml.safe_load(b) for b in blocks]
    for doc in parsed:
        if isinstance(doc, dict) and doc.get("schema") == "workitem-migration":
            assert set(doc) >= {"schema", "from", "to", "id", "steps"}, doc
            for step in doc["steps"]:
                assert set(step) >= {"id", "target", "transform"}, step
            return
    pytest.fail("no workitem-migration example found in migrations/README.md")


def test_v1_1_is_a_data_release_and_keeps_schema_version_1_0() -> None:
    """D8: tightening a schema does not bump schema_version.

    Bumping the const would invalidate every existing record and falsify the
    no-migration claim. So records stay "1.0" and the mapping is corrected.
    """
    c = load_contract()
    assert c.version["current"] == "v1.1"
    entry = [v for v in c.version["versions"] if v["tag"] == "workitem/v1.1"]
    assert entry, "v1.1 must be declared"
    assert entry[0]["schema_version"] == "1.0"
    assert entry[0]["released"] is not None


def test_a_contract_data_release_does_not_change_the_schema_version() -> None:
    """The tag and the schema version are different namespaces.

    Guards the reasoning in D8 so a future minor release cannot silently bump the
    schema version and break every record.
    """
    c = load_contract()
    declared = c.schema["properties"]["schema_version"]["const"]
    for entry in c.version["versions"]:
        if entry["tag"] == c.version["current"]:
            continue
        if entry["released"] is None:
            continue
        assert entry["schema_version"] == declared, (
            f"{entry['tag']} is released with schema_version {entry['schema_version']}, "
            f"but v1.schema.json pins {declared}"
        )
