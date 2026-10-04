"""Derive workitem/v2.schema.json from workitem/v1.schema.json.

v2 is v1.1 plus exactly two things: the schema_version const moves to 2.0, and a
required top-level external_dependencies[] is added. Deriving it mechanically
rather than hand-editing a copy is what makes
test_v2_schema.py::test_v2_is_a_superset_of_v1_except_for_the_version_and_new_field
meaningful -- an accidental edit to a shared constraint shows up as a diff.
"""

import collections
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "workitem" / "v1.schema.json"
DST = ROOT / "workitem" / "v2.schema.json"

EXTERNAL_DEPENDENCY = {
    "type": "array",
    "description": (
        "Work this item is blocked by, living in another repository. Never "
        "resolvable by the contract; discharged only by a completed WorkItem in "
        "this ledger."
    ),
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["repo", "number", "type", "resolved_by", "note"],
        "properties": {
            "repo": {
                "type": "string",
                "pattern": "^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",
                "description": (
                    "owner/repo. A cross-repo reference needs a canonical form; "
                    "the four spellings the v1 tests rejected stay rejected."
                ),
            },
            "number": {
                "type": "integer",
                "minimum": 1,
                "description": (
                    "Issue or pull request number. The two share a GitHub number "
                    "space, so this field is ambiguous by nature; disambiguating "
                    "it is the author's job."
                ),
            },
            "type": {
                "enum": [
                    "BLOCKS",
                    "REQUIRES",
                    "OPTIONAL",
                    "QUALITY_GATE",
                    "REVIEW_GATE",
                ],
                "description": (
                    "Same relation kinds as dependencies[].type. All five require "
                    "discharge; none is informational."
                ),
            },
            "resolved_by": {
                "type": "string",
                "pattern": "^WI-[0-9]{8}-[0-9]{4}$",
                "description": (
                    "A WorkItem in this ledger that is itself DONE. There is no "
                    "assertion variant: discharge must be traceable to completed "
                    "work."
                ),
            },
            "note": {
                "type": "string",
                "minLength": 1,
                "description": ("Why this WorkItem discharges the external reference."),
            },
        },
    },
}


def insert_after(mapping, anchor, key, value):
    """Rebuild a dict with `key` placed immediately after `anchor`."""
    if anchor not in mapping:
        raise KeyError(f"anchor {anchor!r} absent; refusing to guess a position")
    out = {}
    for existing_key, existing_value in mapping.items():
        out[existing_key] = existing_value
        if existing_key == anchor:
            out[key] = value
    if key not in out:
        raise KeyError(f"failed to insert {key!r} after {anchor!r}")
    return out


def insert_into_list(items, anchor, value):
    """Rebuild a list with `value` placed immediately after `anchor`."""
    if anchor not in items:
        raise ValueError(f"anchor {anchor!r} absent; refusing to guess a position")
    out = []
    for existing in items:
        out.append(existing)
        if existing == anchor:
            out.append(value)
    if value not in out:
        raise ValueError(f"failed to insert {value!r} after {anchor!r}")
    return out


def derive() -> str:
    """Return v2.schema.json as text, derived from v1.schema.json."""
    schema = json.loads(SRC.read_text(), object_pairs_hook=collections.OrderedDict)

    # The identity of the schema changes with the major. Leaving $id pointing at
    # v1.schema.json would make a v2 failure resolve to the wrong document.
    schema["$id"] = "https://github.com/harkers/.github/workitem/v2.schema.json"
    schema["title"] = "WorkItem v2"

    schema["properties"]["schema_version"]["const"] = "2.0"

    schema["properties"] = insert_after(
        schema["properties"],
        "dependencies",
        "external_dependencies",
        EXTERNAL_DEPENDENCY,
    )
    schema["required"] = insert_into_list(
        schema["required"], "dependencies", "external_dependencies"
    )

    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def main(out: pathlib.Path | None = None) -> int:
    target = out or DST
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(derive())
    try:
        shown = target.relative_to(ROOT)
    except ValueError:
        shown = target
    print(f"wrote {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
