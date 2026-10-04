"""The gate must catch what a schema cannot: single-record semantics and ledger integrity.

Every case here is one that passes ``v1.schema.json`` cleanly. That is the point:
these are the defects a shape validator cannot see, and they were found by cloud
review of the reusable gate, which was validating shape only.
"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
import yaml

from workitem_conformance.cli import validate
from workitem_conformance.contract import load_contract
from workitem_conformance.instances import check_instance, check_ledger, discover, load_instance
from workitem_conformance.transitions import TransitionEngine

LEDGER_PATTERN = ".workhub/workitems/*/workitem.yaml"


@pytest.fixture
def contract():
    return load_contract()


@pytest.fixture
def engine(contract):
    return TransitionEngine(contract.state_machine)


@pytest.fixture
def ledger(tmp_path: Path, contract):
    """A minimal valid ledger the tests then break in one specific way."""
    root = tmp_path / "repo"
    record = load_example(contract.root, "task")
    write_record(root, "WI-20261003-0001", record)
    return root


def load_example(contract_root: Path, name: str) -> dict:
    return yaml.safe_load((contract_root / "workitem" / "examples" / f"{name}.yaml").read_text())


def write_record(repo: Path, identifier: str, record: dict) -> Path:
    directory = repo / ".workhub" / "workitems" / identifier
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "workitem.yaml"
    path.write_text(yaml.safe_dump(record, sort_keys=False, width=100))
    return path


def mutate(repo: Path, identifier: str, **changes) -> dict:
    path = repo / ".workhub" / "workitems" / identifier / "workitem.yaml"
    record = yaml.safe_load(path.read_text())
    for key, value in changes.items():
        record[key] = copy.deepcopy(value)
    path.write_text(yaml.safe_dump(record, sort_keys=False, width=100))
    return record


def rules(problems) -> set[str]:
    return {p.rule for p in problems}


# --- the five bypasses the cloud review demonstrated against the schema alone ---


def test_a_hand_bumped_done_is_caught(ledger, contract):
    record = yaml.safe_load(
        (ledger / ".workhub/workitems/WI-20261003-0001/workitem.yaml").read_text()
    )
    record["state"] = "DONE"
    record["completion"] = {"status": "incomplete", "packet": None}
    write_record(ledger, "WI-20261003-0001", record)

    problems = validate(contract.root, ledger, LEDGER_PATTERN)
    assert "state-gate" in rules(problems), [str(p) for p in problems]
    assert any("DONE" in p.detail for p in problems)


def test_an_unknown_state_is_caught(ledger, contract):
    mutate(ledger, "WI-20261003-0001", state="BANANA")
    problems = validate(contract.root, ledger, LEDGER_PATTERN)
    assert "unknown-state" in rules(problems)


def test_a_sizing_band_mismatch_is_caught(ledger, contract):
    mutate(
        ledger,
        "WI-20261003-0001",
        sizing={"estimated_complexity": "SMALL", "estimated_context_tokens": 28000},
    )
    problems = validate(contract.root, ledger, LEDGER_PATTERN)
    assert "sizing" in rules(problems)


def test_an_unresolvable_dependency_is_caught(ledger, contract):
    mutate(
        ledger,
        "WI-20261003-0001",
        dependencies=[{"target": "WI-19700101-0001", "type": "REQUIRES"}],
    )
    problems = validate(contract.root, ledger, LEDGER_PATTERN)
    assert "unresolved-dependency" in rules(problems)


def test_an_id_that_does_not_match_its_directory_is_caught(ledger, contract):
    mutate(ledger, "WI-20261003-0001", id="WI-99999999-9999")
    problems = validate(contract.root, ledger, LEDGER_PATTERN)
    assert "id-path-mismatch" in rules(problems)


# --- ledger integrity, which needs every record at once ---


def test_duplicate_ids_across_directories_are_caught(ledger, contract):
    record = yaml.safe_load(
        (ledger / ".workhub/workitems/WI-20261003-0001/workitem.yaml").read_text()
    )
    write_record(ledger, "WI-20261003-0002", record)  # same id, different directory
    problems = validate(contract.root, ledger, LEDGER_PATTERN)
    assert "duplicate-id" in rules(problems)


def test_an_unresolvable_parent_is_caught(ledger, contract):
    mutate(ledger, "WI-20261003-0001", hierarchy={"epic": None, "parent": "WI-19700101-0009"})
    problems = validate(contract.root, ledger, LEDGER_PATTERN)
    assert "unresolved-parent" in rules(problems)


def test_a_resolvable_dependency_is_accepted(tmp_path, contract):
    root = tmp_path / "repo"
    first = load_example(contract.root, "task")
    first["dependencies"] = [{"target": "WI-20261003-0002", "type": "REQUIRES"}]
    write_record(root, "WI-20261003-0001", first)

    # examples/bug.yaml (WI-20261003-0002) declares its own dependency on
    # WI-20261003-0001. Combined with the edge above that closes a cycle, so this
    # fixture was asserting a clean ledger while building an invalid one. The test
    # is about target resolution, not about the bug example's edges, so those are
    # cleared rather than the assertion relaxed.
    second = load_example(contract.root, "bug")
    second["dependencies"] = []
    write_record(root, "WI-20261003-0002", second)

    problems = validate(contract.root, root, LEDGER_PATTERN)
    assert problems == [], [str(p) for p in problems]


def test_the_canonical_examples_do_not_form_a_cycle(contract):
    """The four shipped examples are copied into ledgers by other tests. Together
    they must stay acyclic, or every one of those ledgers inherits a cycle."""
    from workitem_conformance.instances import build_dep_map, find_cycles

    records = [
        (Path(f"{name}/workitem.yaml"), load_example(contract.root, name))
        for name in ("task", "bug", "feature", "investigation")
    ]
    assert find_cycles(build_dep_map(records)) == []


def test_an_external_dependency_target_is_reported_as_unsupported(ledger, contract):
    mutate(
        ledger,
        "WI-20261003-0001",
        dependencies=[{"target": "harkers/workhub#14", "type": "BLOCKS"}],
    )
    problems = validate(contract.root, ledger, LEDGER_PATTERN)
    assert "external-dependency" in rules(problems)
    assert any("#4" in p.detail for p in problems), "should point at the open issue"


# --- the gate's own contract ---


def test_an_empty_ledger_is_an_error_not_a_pass(tmp_path, contract):
    """A gate that matches nothing cannot fail, so it must not report success."""
    problems = validate(contract.root, tmp_path / "empty", LEDGER_PATTERN)
    assert "no-instances" in rules(problems)


def test_a_valid_ledger_reports_no_problems(tmp_path, contract):
    root = tmp_path / "repo"
    for identifier, example in (
        ("WI-20261003-0001", "task"),
        ("WI-20261003-0002", "bug"),
        ("WI-20261003-0003", "feature"),
        ("WI-20261003-0004", "investigation"),
    ):
        write_record(root, identifier, load_example(contract.root, example))
    problems = validate(contract.root, root, LEDGER_PATTERN)
    # feature.yaml depends on WI-20261003-0001, which exists in this ledger.
    assert problems == [], [str(p) for p in problems]


def test_unreadable_yaml_is_reported_not_raised(ledger, contract):
    (ledger / ".workhub/workitems/WI-20261003-0001/workitem.yaml").write_text("a: [1,\n  b: :\n")
    problems = validate(contract.root, ledger, LEDGER_PATTERN)
    assert "unreadable" in rules(problems)


def test_instance_checks_do_not_mutate_the_record(ledger, contract, engine):
    path = ledger / ".workhub/workitems/WI-20261003-0001/workitem.yaml"
    before = path.read_text()
    check_instance(path, load_instance(path), contract, engine)
    assert path.read_text() == before
    assert discover(ledger, LEDGER_PATTERN) == [path]


def test_ledger_check_is_pure(ledger):
    records = [(p, load_instance(p)) for p in discover(ledger, LEDGER_PATTERN)]
    first = check_ledger(records)
    second = check_ledger(records)
    assert first == second


def test_a_copy_of_the_ledger_root_can_be_validated_in_isolation(tmp_path, contract):
    """Proves validation depends only on contract + ledger, not on ambient state."""
    source = tmp_path / "repo"
    record = load_example(contract.root, "task")
    write_record(source, "WI-20261003-0001", record)
    copy = tmp_path / "elsewhere" / "repo"
    copy.parent.mkdir(parents=True)
    shutil.copytree(source, copy)
    assert validate(contract.root, copy, LEDGER_PATTERN) == []
