"""The release manifest must agree with the schema it points at.

A version entry that claims a schema_version with no matching file, or a `current`
that names an unreleased version, produces a release consumers cannot pin. These
are the mechanical checks that a cut is coherent before the tag exists.
"""

from __future__ import annotations

import json

import pytest
import yaml

from workitem_conformance.contract import load_contract


def manifest():
    return yaml.safe_load((load_contract().root / "workitem" / "contract-version.yaml").read_text())


def entry(tag):
    return next(v for v in manifest()["versions"] if v["tag"] == tag)


def test_the_manifest_parses():
    assert manifest()["versions"], "no versions declared"


@pytest.mark.parametrize("tag", [v["tag"] for v in manifest()["versions"]])
def test_every_declared_version_has_a_schema_file_at_its_major(tag):
    major = entry(tag)["schema_version"].split(".")[0]
    path = load_contract().root / "workitem" / f"v{major}.schema.json"
    assert path.is_file(), (
        f"{tag} declares schema_version {entry(tag)['schema_version']} but {path.name} is absent"
    )


@pytest.mark.parametrize("tag", [v["tag"] for v in manifest()["versions"]])
def test_a_schema_files_own_version_const_matches_its_declaration(tag):
    major = entry(tag)["schema_version"].split(".")[0]
    schema = json.loads((load_contract().root / "workitem" / f"v{major}.schema.json").read_text())
    const = schema["properties"]["schema_version"]["const"]
    assert const == entry(tag)["schema_version"], (
        f"{tag} declares {entry(tag)['schema_version']} but v{major}.schema.json "
        f"constrains records to {const}"
    )


def test_the_current_version_is_released():
    current = manifest()["current"]
    released = entry(f"workitem/{current}")["released"]
    assert released is not None, (
        f"current is {current} but it is not released; an unreleased version must not "
        "be pinnable by a consumer"
    )


def test_current_names_a_declared_version():
    declared = {v["tag"] for v in manifest()["versions"]}
    assert f"workitem/{manifest()['current']}" in declared


def test_a_superseded_version_points_at_a_declared_one():
    declared = {v["tag"] for v in manifest()["versions"]}
    for v in manifest()["versions"]:
        successor = v.get("superseded_by")
        if successor:
            assert successor in declared, f"{v['tag']} superseded_by unknown {successor}"


def test_a_superseded_version_is_not_current():
    current = f"workitem/{manifest()['current']}"
    for v in manifest()["versions"]:
        if v.get("superseded_by"):
            assert v["tag"] != current, f"{current} is both current and superseded"


def test_the_loader_resolves_the_current_schema():
    """End to end: the manifest, the resolver and the schema file must agree."""
    contract = load_contract()
    major = entry(f"workitem/{contract.version['current']}")["schema_version"].split(".")[0]
    assert contract.schema["$id"].endswith(f"v{major}.schema.json"), (
        f"load_contract resolved {contract.schema['$id']} but current is "
        f"{contract.version['current']} declaring major {major}"
    )
