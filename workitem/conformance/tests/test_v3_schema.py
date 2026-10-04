"""v3: an external dependency discharges either by a DONE WorkItem or by attestation.

v2 allowed only resolved_by. v3 allows exactly one of two arms, and the exclusivity
is the point: an entry with both is not "belt and braces", it is two conflicting
claims about the same edge, and one of them is wrong.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from workitem_conformance.instances import check_ledger

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = json.loads((ROOT / "workitem" / "v3.schema.json").read_text())
EXAMPLE = yaml.safe_load((ROOT / "workitem" / "examples" / "task.yaml").read_text())

ATTESTED = {
    "by": "stu",
    "at": "2026-10-04T12:00:00Z",
    "note": "merged as 9b0929c; WorkItem not raised retrospectively",
}


def base_record(**overrides):
    record = copy.deepcopy(EXAMPLE)
    record["schema_version"] = "3.0"
    record["id"] = "WI-20261004-0001"
    record["dependencies"] = []
    record["external_dependencies"] = []
    record.update(overrides)
    return record


def entry(**overrides):
    # `note` has been required on every external dependency entry since v2; omitting
    # it here made every assertion in this file fail for an unrelated reason.
    dep = {
        "repo": "harkers/workhub",
        "number": 13,
        "type": "REQUIRES",
        "note": "blocked by an issue with no WorkItem",
    }
    dep.update(overrides)
    return dep


def codes_for(records):
    pairs = [(Path(f"{r['id']}/workitem.yaml"), r) for r in records]
    return {p.rule for p in check_ledger(pairs)}


def test_resolved_by_alone_still_validates():
    jsonschema.validate(
        base_record(external_dependencies=[entry(resolved_by="WI-20261004-0002")]),
        SCHEMA,
    )


def test_attested_alone_validates():
    jsonschema.validate(base_record(external_dependencies=[entry(attested=ATTESTED)]), SCHEMA)


def test_both_arms_together_are_rejected():
    """Two conflicting claims about one edge. Accepting it would let a stale
    resolved_by sit alongside a fresh attestation indefinitely."""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            base_record(
                external_dependencies=[entry(resolved_by="WI-20261004-0002", attested=ATTESTED)]
            ),
            SCHEMA,
        )


def test_neither_arm_is_rejected():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(base_record(external_dependencies=[entry()]), SCHEMA)


@pytest.mark.parametrize("missing", ["by", "at", "note"])
def test_attestation_must_be_attributed_and_complete(missing):
    broken = {k: v for k, v in ATTESTED.items() if k != missing}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(base_record(external_dependencies=[entry(attested=broken)]), SCHEMA)


def test_attestation_by_cannot_be_empty():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            base_record(external_dependencies=[entry(attested={**ATTESTED, "by": ""})]),
            SCHEMA,
        )


def test_a_stray_field_cannot_defeat_exclusivity():
    """Both arms set additionalProperties:false precisely so an entry cannot add a
    key and satisfy one arm while carrying the other's data."""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            base_record(
                external_dependencies=[
                    entry(resolved_by="WI-20261004-0002", attested=ATTESTED, note="x")
                ]
            ),
            SCHEMA,
        )


def test_attested_entry_is_not_reported_as_an_unresolved_discharge():
    records = [
        base_record(external_dependencies=[entry(attested=ATTESTED)]),
        {**base_record(), "id": "WI-20261004-0002"},
    ]
    assert "unresolved-external-discharge" not in codes_for(records)


def test_attested_entry_satisfies_done():
    """The point of the amendment: an attributed attestation carries the record
    through DONE, because PR_READY precedes DONE in the ladder.

    Mechanism worth being precise about, because it is not what the name suggests:
    the checker is NOT taught about attestations to reach this verdict. An attested
    entry has no `resolved_by`, so the `isinstance(edge.get("resolved_by"), str)`
    filter in unmet_targets excludes it and it contributes no unmet target.

    Removing the attestation skip from unresolved-external-discharge -- the one place
    the checker does branch on it -- was tried and changes nothing here, because that
    loop also keys off resolved_by. So this test verifies the OUTCOME, and the
    branch in the other loop is guarded by test_attested_entry_is_not_reported_as_an
    _unresolved_discharge instead. Both are worth having; neither is load-bearing on
    its own, and pretending otherwise would be the same overclaim this session has
    already made twice.
    """
    records = [
        base_record(state="DONE", external_dependencies=[entry(attested=ATTESTED)]),
        {**base_record(), "id": "WI-20261004-0002", "state": "DONE"},
    ]
    assert "dependency-not-satisfied" not in codes_for(records)


def test_unresolved_resolved_by_is_still_refused_at_done():
    records = [
        base_record(state="DONE", external_dependencies=[entry(resolved_by="WI-20261004-0002")]),
        {**base_record(), "id": "WI-20261004-0002", "state": "DRAFT"},
    ]
    assert "dependency-not-satisfied" in codes_for(records)


def test_the_live_case_that_motivated_v3():
    """WI-20261003-0005's shape: three finished issues, no WorkItems, blockers named
    only in prose. Under v2 this record could not finish without manufacturing three
    retrospective WorkItems. Under v3 it records reality and completes."""
    blockers = [
        entry(
            repo="harkers/workhub",
            number=n,
            attested={
                "by": "stu",
                "at": "2026-10-04T12:00:00Z",
                "note": f"issue #{n} merged before the ledger tracked it",
            },
        )
        for n in (13, 14, 15)
    ]
    record = base_record(
        id="WI-20261003-0005",
        state="DONE",
        delivery={"mode": "none", "branch": None, "pull_request": None},
        external_dependencies=blockers,
    )
    jsonschema.validate(record, SCHEMA)
    assert "dependency-not-satisfied" not in codes_for([record])
    assert "unresolved-external-discharge" not in codes_for([record])


def test_v3_is_v2_plus_one_arm():
    """v3 differs from v2 in exactly one place. Anything else is an accident."""
    v2 = json.loads((ROOT / "workitem" / "v2.schema.json").read_text())
    skip = {"$id", "title", "properties", "required"}
    a = {k: v for k, v in v2.items() if k not in skip}
    b = {k: v for k, v in SCHEMA.items() if k not in skip}
    assert a == b, "top-level metadata changed beyond the schema body"

    v2_props = {k: v for k, v in v2["properties"].items() if k != "external_dependencies"}
    v3_props = {k: v for k, v in SCHEMA["properties"].items() if k != "external_dependencies"}
    for name in v2_props:
        if name == "schema_version":
            continue
        assert v3_props[name] == v2_props[name], f"{name} changed between v2 and v3"

    # Each arm carries v2's field set plus, on the new arm only, `attested`. The
    # resolved_by arm is v2's arm unchanged -- it must NOT gain attested, or the two
    # arms would overlap and exclusivity would be enforced only by required-keys.
    v2_keys = set(v2["properties"]["external_dependencies"]["items"]["properties"])
    arms = {
        arm["title"]: arm for arm in SCHEMA["properties"]["external_dependencies"]["items"]["oneOf"]
    }
    allowed = v2_keys | {"attested"}

    resolved = arms["discharged by a completed WorkItem"]
    assert set(resolved["properties"]) == v2_keys, "the v2 arm gained or lost a field"
    assert resolved["required"] == ["repo", "number", "type", "note", "resolved_by"]

    # The attested arm REPLACES resolved_by rather than adding to it. Carrying both
    # would defeat exclusivity: oneOf would match, and the entry would hold two
    # conflicting claims about the same edge.
    attested = arms["discharged by recorded human confirmation"]
    assert set(attested["properties"]) == (v2_keys - {"resolved_by"}) | {"attested"}
    assert "resolved_by" not in attested["properties"]
    assert attested["required"] == ["repo", "number", "type", "note", "attested"]

    for arm in arms.values():
        assert set(arm["properties"]) <= allowed, arm["title"]
        assert arm["additionalProperties"] is False, arm["title"]
