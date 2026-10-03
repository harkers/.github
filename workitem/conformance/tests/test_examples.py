"""The four canonical examples must validate, and invalid ones must be rejected."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from workitem_conformance.contract import ContractError, load_contract, load_example

EXAMPLE_NAMES = ["task", "bug", "feature", "investigation"]

INVALID_FIXTURES = [
    "invalid-mutable-type-in-id",
    "invalid-unknown-dependency-type",
    "invalid-unmeasurable-ac",
    "invalid-missing-privacy",
    "invalid-missing-scope",
]


def _validator() -> Draft202012Validator:
    return Draft202012Validator(load_contract().schema)


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_example_validates(name: str) -> None:
    errors = sorted(_validator().iter_errors(load_example(load_contract().root, name)), key=str)
    assert errors == [], "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


def test_schema_itself_is_valid() -> None:
    Draft202012Validator.check_schema(load_contract().schema)


def test_every_example_is_listed_on_disk() -> None:
    found = sorted(p.stem for p in (load_contract().root / "workitem" / "examples").glob("*.yaml"))
    assert found == sorted(EXAMPLE_NAMES)


@pytest.mark.parametrize("fixture", INVALID_FIXTURES)
def test_invalid_fixture_is_rejected(fixture: str) -> None:
    path = Path(__file__).parent / "fixtures" / f"{fixture}.yaml"
    bad = yaml.safe_load(path.read_text())
    errors = list(_validator().iter_errors(bad))
    assert errors, f"fixture {fixture} was accepted but should be rejected"


def test_missing_contract_root_raises() -> None:
    with pytest.raises(ContractError):
        load_contract(Path("/nonexistent-contract-root"))


@pytest.mark.parametrize(
    "fixture",
    ["branch-only-with-a-pull-request", "none-with-a-branch"],
)
def test_record_cannot_contradict_its_delivery_mode(fixture: str) -> None:
    path = Path(__file__).parent / "fixtures" / f"{fixture}.yaml"
    assert list(_validator().iter_errors(yaml.safe_load(path.read_text()))), (
        f"{fixture} was accepted but contradicts its own delivery.mode"
    )


def test_draft_record_with_a_null_branch_stays_valid() -> None:
    """branch is deliberately unconstrained for pull_request.

    WI-20261003-0005 is a live DRAFT with branch: null. A branch does not exist
    until execution begins, so requiring one would invalidate the only record that
    exists, for a condition unrelated to reachability.
    """
    item = load_example(load_contract().root, "task")
    assert item["delivery"]["branch"] is None
    assert not list(_validator().iter_errors(item))


def test_none_record_may_carry_neither_branch_nor_pull_request() -> None:
    item = load_example(load_contract().root, "investigation")
    assert item["delivery"]["mode"] == "none"
    assert not list(_validator().iter_errors(item))


def test_branch_only_record_with_a_null_pull_request_is_accepted() -> None:
    item = load_example(load_contract().root, "bug")
    item["delivery"] = {
        "mode": "branch_only",
        "branch": "wi/WI-20261003-0002/x",
        "pull_request": None,
    }
    assert not list(_validator().iter_errors(item))


def test_delivery_mode_conditionals_cannot_match_vacuously() -> None:
    """Every `if` keys on delivery.mode, so both must always be present."""
    schema = load_contract().schema
    assert "delivery" in schema["required"]
    assert "mode" in schema["properties"]["delivery"]["required"]
