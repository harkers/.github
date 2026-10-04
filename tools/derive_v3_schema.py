"""Derive workitem/v3.schema.json from workitem/v2.schema.json.

v3 changes one thing: external_dependencies[] entries gain a second discharge
arm. v2 allowed only `resolved_by` (a WorkItem that must be DONE); v3 allows
*either* that *or* an attributed `attested` record, exclusively.

This is deliberately a SEPARATE tool from derive_v2_schema.py rather than a
--from flag on it. The two do different jobs -- v1->v2 added a field, v2->v3
restructured a field into an exclusive choice -- and
test_v2_generation.py asserts that committed v2 is exactly what derive_v2_schema
produces. Generalising that tool would put v2's reproducibility at risk for no
gain.

Idempotent, and refuses rather than guessing: if the anchor is absent, or the
source is not the expected shape, it raises instead of writing something.
"""

from __future__ import annotations

import collections
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "workitem" / "v2.schema.json"
DST = ROOT / "workitem" / "v3.schema.json"

ENTRY_PROPERTIES = ("repo", "number", "type", "note")

ATTESTED = {
    "type": "object",
    "additionalProperties": False,
    "required": ["by", "at", "note"],
    "properties": {
        "by": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Who confirmed it. An unowned attestation is not expressible: the "
                "whole mitigation for an unverifiable discharge is that it carries "
                "a name."
            ),
        },
        "at": {
            "type": "string",
            "format": "date-time",
            "description": "When they confirmed it.",
        },
        "note": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Why this is discharged. For a retrospective blocker, the commit or "
                "merge that discharged it."
            ),
        },
    },
}


def derive() -> str:
    """Return v3.schema.json as text, derived from v2.schema.json."""
    schema = json.loads(SRC.read_text(), object_pairs_hook=collections.OrderedDict)

    schema["$id"] = "https://github.com/harkers/.github/workitem/v3.schema.json"
    schema["title"] = "WorkItem v3"
    schema["properties"]["schema_version"]["const"] = "3.0"

    deps = schema["properties"]["external_dependencies"]
    v2_items = deps.get("items")
    if not isinstance(v2_items, dict) or "properties" not in v2_items:
        raise KeyError(
            "external_dependencies.items is not the expected v2 shape; refusing to "
            "guess where the discharge arms belong"
        )
    if "oneOf" in v2_items:
        raise ValueError("source already has oneOf; is this v3 or later?")

    shared = collections.OrderedDict(
        (name, v2_items["properties"][name]) for name in ENTRY_PROPERTIES
    )

    resolved_arm = collections.OrderedDict(
        [
            ("type", "object"),
            ("additionalProperties", False),
            ("required", [*ENTRY_PROPERTIES, "resolved_by"]),
            ("properties", {**shared, "resolved_by": v2_items["properties"]["resolved_by"]}),
        ]
    )
    attested_arm = collections.OrderedDict(
        [
            ("type", "object"),
            ("additionalProperties", False),
            ("required", [*ENTRY_PROPERTIES, "attested"]),
            ("properties", {**shared, "attested": ATTESTED}),
        ]
    )

    deps["items"] = collections.OrderedDict(
        [
            ("description", v2_items.get("description", "")),
            (
                "oneOf",
                [
                    {**resolved_arm, "title": "discharged by a completed WorkItem"},
                    {**attested_arm, "title": "discharged by recorded human confirmation"},
                ],
            ),
        ]
    )
    deps["description"] = (
        "Work this item is blocked by, living in another repository. Never resolvable "
        "by the contract, so an entry is discharged either by a WorkItem in this "
        "ledger that is itself DONE, or by an attributed human confirmation."
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
