"""Coverage for what the contract cannot express.

Every contract example either has no dependencies or depends on another example,
so nothing exercised the case that a WorkItem is blocked by work which has no
WorkItem yet. That case is the common one, and the schema cannot represent it --
see harkers/.github#4.

These tests pin the current behaviour so that fixing #4 is a deliberate,
visible change to a failing assertion rather than a silent drift.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from workitem_conformance.contract import load_contract

FIXTURE = "blocked-by-untracked-work"


def _fixture() -> dict:
    path = Path(__file__).parent / "fixtures" / f"{FIXTURE}.yaml"
    return yaml.safe_load(path.read_text())


def test_the_fixture_is_itself_a_valid_workitem() -> None:
    """The gap is not that such a WorkItem is invalid -- it is that it cannot say so."""
    schema = load_contract().schema
    errors = list(Draft202012Validator(schema).iter_errors(_fixture()))
    assert errors == [], [e.message for e in errors]


def test_no_dependency_form_can_name_an_external_issue() -> None:
    """Documents the gap: every `target` must be a WorkItem id.

    This assertion is expected to change when #4 is fixed. It should fail then,
    not silently pass.
    """
    schema = load_contract().schema
    target = schema["properties"]["dependencies"]["items"]["properties"]["target"]
    assert target["pattern"] == "^WI-[0-9]{8}-[0-9]{4}$", (
        "dependencies[].target now accepts a non-WorkItem reference. #4 may be "
        "fixed -- update this test to assert the new form and add a fixture that "
        "uses it."
    )


def test_an_external_reference_is_rejected_by_the_schema() -> None:
    """An external issue reference is not merely unsupported -- it is invalid."""
    schema = load_contract().schema
    item = _fixture()
    item["dependencies"] = [{"target": "harkers/workhub#14", "type": "BLOCKS"}]
    errors = list(Draft202012Validator(schema).iter_errors(item))
    assert errors, "an external issue reference was accepted as a dependency target"


def test_the_blockage_is_only_recorded_in_prose() -> None:
    """The fixture's own record of the blockage is untyped and unresolvable.

    Nothing in the WorkItem's structure marks this as blocking, so a scheduler
    traversing `dependencies` would treat the item as unblocked. That is the
    defect #4 describes, expressed as an executable claim.
    """
    item = _fixture()
    assert item["dependencies"] == [{"target": "WI-20261003-0001", "type": "REQUIRES"}]
    assert "harkers/workhub#14" in item["identity"]["description"]
    # No field anywhere carries the external reference structurally.
    serialised = json.dumps(item)
    assert serialised.count("harkers/workhub#14") == 1, (
        "the external reference appears more than once -- if it has escaped prose "
        "into structure, re-examine whether #4 is still needed"
    )


@pytest.mark.parametrize("reference", ["#14", "14", "harkers/workhub#14", "issue-14"])
def test_no_plausible_spelling_of_an_issue_reference_is_accepted(reference: str) -> None:
    schema = load_contract().schema
    item = _fixture()
    item["dependencies"] = [{"target": reference, "type": "BLOCKS"}]
    assert list(Draft202012Validator(schema).iter_errors(item)), (
        f"{reference!r} was accepted as a dependency target"
    )
