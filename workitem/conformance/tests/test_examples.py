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
