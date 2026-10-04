import copy
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = json.loads((ROOT / "workitem" / "v2.schema.json").read_text())

# v2 requires all 20 fields, so a hand-written stub cannot validate. Start from a
# real example and restate only what each test is about.
EXAMPLE = yaml.safe_load((ROOT / "workitem" / "examples" / "task.yaml").read_text())


def base_record(**overrides):
    record = copy.deepcopy(EXAMPLE)
    record["schema_version"] = "2.0"
    record["id"] = "WI-20261004-0001"
    record["dependencies"] = []
    record["external_dependencies"] = []
    record.update(overrides)
    return record


def good_dep(**overrides):
    dep = {
        "repo": "harkers/workhub",
        "number": 64,
        "type": "REQUIRES",
        "resolved_by": "WI-20261004-0002",
        "note": "landed in harkers/workhub#65",
    }
    dep.update(overrides)
    return dep


def test_external_dependencies_is_required():
    record = base_record()
    del record["external_dependencies"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(record, SCHEMA)


def test_external_dependencies_may_be_empty():
    jsonschema.validate(base_record(), SCHEMA)


def test_minimal_external_dependency_validates():
    jsonschema.validate(base_record(external_dependencies=[good_dep()]), SCHEMA)


@pytest.mark.parametrize(
    "field,value",
    [
        ("repo", "no-slash"),
        ("repo", "harkers/workhub/extra"),
        ("number", 0),
        ("number", "64"),
        ("type", "DEPENDS_ON"),
        ("resolved_by", "harkers/workhub#64"),
        ("resolved_by", "not-an-id"),
        ("note", ""),
    ],
)
def test_malformed_external_dependency_is_rejected(field, value):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(base_record(external_dependencies=[good_dep(**{field: value})]), SCHEMA)


def test_every_member_of_the_dependency_enum_is_accepted():
    for rel in ("BLOCKS", "REQUIRES", "OPTIONAL", "QUALITY_GATE", "REVIEW_GATE"):
        jsonschema.validate(base_record(external_dependencies=[good_dep(type=rel)]), SCHEMA)


def test_internal_target_pattern_is_unchanged():
    deps = SCHEMA["properties"]["dependencies"]["items"]["properties"]["target"]
    assert deps["pattern"] == "^WI-[0-9]{8}-[0-9]{4}$"


def test_v2_carries_the_v1_delivery_constraints():
    """v2 supersedes v1.1, so it must keep the delivery-mode constraints.

    These live in the top-level allOf as if/then pairs, not inside
    properties.delivery -- which is what both the plan and the first cut of this
    test assumed, and both were wrong.
    """
    entries = SCHEMA["allOf"]
    modes = {
        entry["if"]["properties"]["delivery"]["properties"]["mode"]["const"] for entry in entries
    }
    assert modes == {"none", "branch_only"}


def test_delivery_constraints_still_reject_a_contradicting_record():
    none_mode = base_record(delivery={"mode": "none", "branch": "main", "pull_request": None})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(none_mode, SCHEMA)

    branch_only = base_record(delivery={"mode": "branch_only", "branch": "main", "pull_request": 7})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(branch_only, SCHEMA)


def test_v2_is_a_superset_of_v1_except_for_the_version_and_new_field():
    """v2 is v1.1 plus external_dependencies plus the version const. Anything else
    that differs is an accidental edit, not a deliberate change."""
    v1 = json.loads((ROOT / "workitem" / "v1.schema.json").read_text())
    # $id, title and required all change legitimately; properties is compared below.
    skip = {"properties", "$id", "title", "required"}
    a = {k: v for k, v in v1.items() if k not in skip}
    b = {k: v for k, v in SCHEMA.items() if k not in skip}
    assert a == b, "top-level metadata changed beyond the schema body"

    assert SCHEMA["$id"].endswith("v2.schema.json")
    assert SCHEMA["title"] == "WorkItem v2"

    v1_props = dict(v1["properties"])
    v2_props = dict(SCHEMA["properties"])
    assert set(v2_props) - set(v1_props) == {"external_dependencies"}
    assert set(v1_props) - set(v2_props) == set()

    for name, definition in v1_props.items():
        if name == "schema_version":
            continue
        assert v2_props[name] == definition, f"{name} changed between v1 and v2"

    assert v1["properties"]["schema_version"]["const"] == "1.0"
    assert SCHEMA["properties"]["schema_version"]["const"] == "2.0"

    # v2's required must be exactly v1's with external_dependencies inserted after
    # dependencies. Filter the same key out of both, or the comparison is between
    # two different lists and proves nothing.
    v2_required = [r for r in SCHEMA["required"] if r != "external_dependencies"]
    assert v1["required"] == v2_required
    assert SCHEMA["required"].index("external_dependencies") == (
        SCHEMA["required"].index("dependencies") + 1
    )
    assert len(SCHEMA["required"]) == len(v1["required"]) + 1
