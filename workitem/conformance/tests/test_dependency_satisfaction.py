from pathlib import Path

from workitem_conformance.instances import check_ledger


def codes_for(records):
    pairs = [(Path(f"{r['id']}/workitem.yaml"), r) for r in records]
    return sorted({p.rule for p in check_ledger(pairs)})


def rec(wid, state, deps=None, ext=None):
    return {
        "id": wid,
        "state": state,
        "dependencies": [{"target": t, "type": "REQUIRES"} for t in (deps or [])],
        "external_dependencies": ext or [],
    }


def external(discharge):
    return [
        {
            "repo": "harkers/workhub",
            "number": 64,
            "type": "REQUIRES",
            "resolved_by": discharge,
            "note": "x",
        }
    ]


def test_done_with_all_dependencies_done_is_clean():
    records = [
        rec("WI-20261004-0001", "DONE", ["WI-20261004-0002"]),
        rec("WI-20261004-0002", "DONE"),
    ]
    assert "dependency-not-satisfied" not in codes_for(records)


def test_done_with_an_unfinished_dependency_is_refused():
    records = [
        rec("WI-20261004-0001", "DONE", ["WI-20261004-0002"]),
        rec("WI-20261004-0002", "DRAFT"),
    ]
    assert "dependency-not-satisfied" in codes_for(records)


def test_cancelled_dependency_does_not_satisfy():
    """The load-bearing case. If CANCELLED satisfied, cancelling one WorkItem would
    silently release everything downstream."""
    records = [
        rec("WI-20261004-0001", "DONE", ["WI-20261004-0002"]),
        rec("WI-20261004-0002", "CANCELLED"),
    ]
    assert "dependency-not-satisfied" in codes_for(records)


def test_cancelled_is_always_available_as_an_exit():
    """Not being able to reach DONE is not a trap: the dependent can always be
    cancelled instead, and a cancelled record is never flagged."""
    records = [
        rec("WI-20261004-0001", "CANCELLED", ["WI-20261004-0002"]),
        rec("WI-20261004-0002", "CANCELLED"),
    ]
    assert "dependency-not-satisfied" not in codes_for(records)


def test_unfinished_dependencies_are_fine_while_not_done():
    records = [
        rec("WI-20261004-0001", "DRAFT", ["WI-20261004-0002"]),
        rec("WI-20261004-0002", "DRAFT"),
    ]
    assert "dependency-not-satisfied" not in codes_for(records)


def test_a_long_unfinished_chain_is_fine_until_it_reaches_done():
    records = [rec("WI-20261004-0001", "DRAFT", ["WI-20261004-0002"])]
    records += [rec(f"WI-20261004-{i:04d}", "DRAFT") for i in range(2, 12)]
    assert "dependency-not-satisfied" not in codes_for(records)

    records[0]["state"] = "DONE"
    assert "dependency-not-satisfied" in codes_for(records)


def test_external_discharge_must_itself_be_done():
    records = [
        rec("WI-20261004-0001", "DONE", ext=external("WI-20261004-0002")),
        rec("WI-20261004-0002", "REVIEWING"),
    ]
    assert "dependency-not-satisfied" in codes_for(records)


def test_external_discharge_that_is_done_is_clean():
    records = [
        rec("WI-20261004-0001", "DONE", ext=external("WI-20261004-0002")),
        rec("WI-20261004-0002", "DONE"),
    ]
    assert "dependency-not-satisfied" not in codes_for(records)


def test_every_relation_type_requires_discharge():
    for relation in ("BLOCKS", "REQUIRES", "OPTIONAL", "QUALITY_GATE", "REVIEW_GATE"):
        dep = {"target": "WI-20261004-0002", "type": relation}
        records = [
            rec("WI-20261004-0001", "DONE"),
            rec("WI-20261004-0002", "DRAFT"),
        ]
        records[0]["dependencies"] = [dep]
        assert "dependency-not-satisfied" in codes_for(records), relation


def test_every_relation_type_requires_external_discharge():
    for relation in ("BLOCKS", "REQUIRES", "OPTIONAL", "QUALITY_GATE", "REVIEW_GATE"):
        dep = external("WI-20261004-0002")
        dep[0]["type"] = relation
        records = [
            rec("WI-20261004-0001", "DONE", ext=dep),
            rec("WI-20261004-0002", "DRAFT"),
        ]
        assert "dependency-not-satisfied" in codes_for(records), relation


def test_the_message_names_the_dependency_and_its_actual_state():
    records = [
        rec("WI-20261004-0001", "DONE", ["WI-20261004-0002"]),
        rec("WI-20261004-0002", "BLOCKED"),
    ]
    problems = check_ledger([(Path(f"{r['id']}/workitem.yaml"), r) for r in records])
    details = [p.detail for p in problems if p.rule == "dependency-not-satisfied"]
    assert details, "expected a dependency-not-satisfied problem"
    assert "WI-20261004-0002" in details[0]
    assert "BLOCKED" in details[0]
