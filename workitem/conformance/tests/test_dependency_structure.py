from pathlib import Path

from workitem_conformance.instances import check_ledger, find_cycles


def test_empty_graph_has_no_cycles():
    assert find_cycles({"a": [], "b": []}) == []


def test_dag_has_no_cycles():
    assert find_cycles({"a": ["b"], "b": ["c"], "c": []}) == []


def test_self_loop_is_a_cycle():
    assert find_cycles({"a": ["a"]}) == [["a", "a"]]


def test_two_node_cycle_is_detected():
    cycles = find_cycles({"a": ["b"], "b": ["a"]})
    assert len(cycles) == 1
    assert set(cycles[0][:2]) == {"a", "b"}


def test_long_cycle_is_detected():
    cycles = find_cycles({"a": ["b"], "b": ["c"], "c": ["d"], "d": ["a"]})
    assert len(cycles) == 1


def test_each_cycle_is_reported_once():
    """A 2-cycle is reachable from both nodes; report it once, not twice."""
    assert len(find_cycles({"a": ["b"], "b": ["a"]})) == 1


def test_two_distinct_cycles_are_both_reported():
    cycles = find_cycles(
        {
            "a": ["b"],
            "b": ["a"],
            "c": ["d"],
            "d": ["c"],
        }
    )
    assert len(cycles) == 2


def test_edges_to_unknown_nodes_are_ignored_by_the_cycle_check():
    """Unresolved targets are a separate problem code; the cycle walk must not
    crash on them, because a dangling edge is not a cycle."""
    assert find_cycles({"a": ["ghost"], "b": []}) == []


def test_deep_chain_does_not_recurse_to_death():
    graph = {f"n{i}": [f"n{i + 1}"] for i in range(5000)}
    graph["n5000"] = []
    assert find_cycles(graph) == []


def test_deep_chain_with_a_back_edge_terminates():
    graph = {f"n{i}": [f"n{i + 1}"] for i in range(5000)}
    graph["n5000"] = ["n0"]
    assert len(find_cycles(graph)) == 1


def codes_for(records):
    """check_ledger takes (path, record) pairs and InstanceProblem names the rule
    in .rule, not .code."""
    pairs = [(Path(f"{record['id']}/workitem.yaml"), record) for record in records]
    return sorted({p.rule for p in check_ledger(pairs)})


def test_resolved_by_must_name_a_record_in_the_ledger():
    record = {
        "id": "WI-20261004-0001",
        "dependencies": [],
        "external_dependencies": [
            {
                "repo": "harkers/workhub",
                "number": 64,
                "type": "REQUIRES",
                "resolved_by": "WI-20261004-9999",
                "note": "x",
            }
        ],
    }
    assert "unresolved-external-discharge" in codes_for([record])


def test_a_cycle_through_external_discharge_is_detected():
    a = {
        "id": "WI-20261004-0001",
        "dependencies": [],
        "external_dependencies": [
            {
                "repo": "harkers/workhub",
                "number": 1,
                "type": "REQUIRES",
                "resolved_by": "WI-20261004-0002",
                "note": "x",
            }
        ],
    }
    b = {
        "id": "WI-20261004-0002",
        "dependencies": [{"target": "WI-20261004-0001", "type": "REQUIRES"}],
        "external_dependencies": [],
    }
    assert "dependency-cycle" in codes_for([a, b])


def test_a_dangling_internal_target_is_still_reported():
    a = {
        "id": "WI-20261004-0001",
        "dependencies": [{"target": "WI-20261004-9999", "type": "REQUIRES"}],
        "external_dependencies": [],
    }
    codes = codes_for([a])
    assert "unresolved-dependency" in codes
    assert "dependency-cycle" not in codes
