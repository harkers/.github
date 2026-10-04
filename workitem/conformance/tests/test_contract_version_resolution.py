import pytest

from workitem_conformance.contract import ContractError, _schema_filename


def test_data_release_keeps_the_same_schema_file():
    version = {
        "current": "v1.1",
        "versions": [{"tag": "workitem/v1.1", "schema_version": "1.0"}],
    }
    assert _schema_filename(version) == "workitem/v1.schema.json"


def test_major_bump_resolves_the_new_schema_file():
    version = {
        "current": "v2",
        "versions": [{"tag": "workitem/v2", "schema_version": "2.0"}],
    }
    assert _schema_filename(version) == "workitem/v2.schema.json"


def test_current_must_name_a_declared_version():
    version = {
        "current": "v9",
        "versions": [{"tag": "workitem/v2", "schema_version": "2.0"}],
    }
    with pytest.raises(ContractError):
        _schema_filename(version)


def test_the_real_manifest_resolves():
    """current is a short name; versions[].tag is the full tag. They must still meet."""
    version = {
        "current": "v1.1",
        "versions": [
            {"tag": "workitem/v1", "schema_version": "1.0"},
            {"tag": "workitem/v1.1", "schema_version": "1.0"},
            {"tag": "workitem/v2", "schema_version": "2.0", "released": None},
        ],
    }
    assert _schema_filename(version) == "workitem/v1.schema.json"
