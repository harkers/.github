"""v2.schema.json must be exactly what the generator produces.

tools/derive_v2_schema.py exists so that v2 is v1 plus two deliberate changes
rather than a hand-edited copy that drifts. Unwired, it is the worst kind of
generator: trusted enough to keep, able to silently betray.

The asymmetry matters. v1 -> v2 drift is *loud* -- the superset test compares
every shared key and fails. Generator -> committed-file drift is *silent*:
properties.external_dependencies is the one section the generator authors and no
other test pins, so a hand-edit there survives review, and the next innocent
re-run of the tool reverts it and ships the result in the workitem/v2 tag.

So: run the derivation into memory and compare byte-for-byte. This fails on a
hand-edit to v2 and on a change to the generator that was not re-run.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import jsonschema
import pytest

from workitem_conformance.contract import load_contract

TOOL = Path(__file__).resolve().parents[3] / "tools" / "derive_v2_schema.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("derive_v2_schema", TOOL)
    assert spec is not None and spec.loader is not None, f"cannot load {TOOL}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_generator_exists() -> None:
    assert TOOL.is_file(), f"missing generator: {TOOL}"


def test_committed_v2_schema_is_exactly_what_the_generator_produces(tmp_path) -> None:
    module = _load_generator()
    root = load_contract().root
    out = tmp_path / "v2.schema.json"

    assert module.main(out) == 0

    generated = out.read_text()
    committed = (root / "workitem" / "v2.schema.json").read_text()
    assert generated == committed, (
        "workitem/v2.schema.json has drifted from tools/derive_v2_schema.py. "
        "Re-run the generator and commit the result -- do not hand-edit v2."
    )


def test_the_generator_is_idempotent(tmp_path) -> None:
    """Running it twice must produce identical bytes, or the check above is
    comparing against noise."""
    module = _load_generator()
    out = tmp_path / "v2.schema.json"

    assert module.main(out) == 0
    first = out.read_text()
    assert module.main(out) == 0
    second = out.read_text()
    assert first == second


def test_the_generator_refuses_to_guess_a_position(tmp_path, monkeypatch) -> None:
    """It renames the anchor key. If a future v1 drops `dependencies`, the tool must
    fail loudly rather than append the new key somewhere arbitrary."""
    module = _load_generator()
    with pytest.raises(KeyError):
        module.insert_after({"a": 1}, "dependencies", "external_dependencies", {})
    with pytest.raises(ValueError):
        module.insert_into_list(["a", "b"], "dependencies", "external_dependencies")


def test_external_dependencies_block_is_strict() -> None:
    """The section the generator authors and no superset test pins. Pin its
    container strictness here, so a loosening edit cannot pass unnoticed."""
    schema = json.loads((load_contract().root / "workitem" / "v2.schema.json").read_text())
    block = schema["properties"]["external_dependencies"]
    assert block["type"] == "array"
    item = block["items"]
    assert item["additionalProperties"] is False, (
        "external_dependencies items must reject unknown keys; without this an "
        "unrecognised field is silently ignored"
    )
    assert set(item["required"]) == {
        "repo",
        "number",
        "type",
        "resolved_by",
        "note",
    }
    assert set(item["properties"]) == set(item["required"])


def test_the_v2_example_is_a_real_record_not_a_synthetic_stub() -> None:
    """A shipped v2-shaped record, so the field has an example that exercises the
    whole shape rather than only the block under test.

    It cannot live in workitem/examples/ yet: contract-version.yaml still has
    current: v1.1, so that directory is v1-shaped and validated against v1. It
    moves to examples/ when v2 is cut.
    """
    import yaml

    from workitem_conformance.instances import check_ledger

    root = load_contract().root
    path = root / "workitem" / "conformance" / "tests" / "fixtures" / "v2-external-blocked.yaml"
    assert path.is_file(), f"missing v2 example: {path}"
    record = yaml.safe_load(path.read_text())

    schema = json.loads((root / "workitem" / "v2.schema.json").read_text())
    jsonschema.validate(record, schema)

    assert len(record["external_dependencies"]) == 2
    relations = {e["type"] for e in record["external_dependencies"]}
    assert relations == {"REQUIRES", "OPTIONAL"}, (
        "the example should show that OPTIONAL is not informational either"
    )
    for edge in record["external_dependencies"]:
        assert re.fullmatch(r"WI-\d{8}-\d{4}", edge["resolved_by"])

    # The record is DRAFT and its discharges are not in this ledger, so the
    # checker must reject the discharge references. That is the capability
    # working: `resolved_by` must name real work here, not an assertion.
    problems = check_ledger([(path, record)])
    found = {p.rule for p in problems}
    assert "unresolved-external-discharge" in found, found
    assert "dependency-not-satisfied" not in found, (
        "DONE-only satisfaction must not fire while the record is still DRAFT"
    )
