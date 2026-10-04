"""One-shot migration of examples and fixtures to contract v2.

v2 requires external_dependencies, and the canonical examples declare
schema_version 1.0. Once contract-version.yaml sets current: v2 the checker
resolves v2.schema.json, and every 1.0-shaped example fails on both the version
const and the missing key.

Idempotent: a file that already carries external_dependencies is left alone, so
running this twice is safe. It refuses to touch a file that declares a
schema_version it does not recognise, rather than guessing.

Deliberately does NOT touch harkers/workhub's live ledger. That is a consumer's
records to migrate, with tools/migrate_examples_to_v2.py only covering this repo.
"""

from __future__ import annotations

import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGETS = [
    *sorted((ROOT / "workitem" / "examples").glob("*.yaml")),
    *sorted((ROOT / "workitem" / "conformance" / "tests" / "fixtures").glob("*.yaml")),
]
TARGET_VERSION = "2.0"


def candidates() -> list[pathlib.Path]:
    out = []
    for path in TARGETS:
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and "schema_version" in data:
            out.append(path)
    return out


def main() -> int:
    todo = candidates()
    if not todo:
        print("no candidates: every example and fixture already declares schema_version")
        return 0

    migrated, skipped = [], []
    for path in todo:
        text = path.read_text()
        if "external_dependencies" in text:
            skipped.append(path.name)
            continue
        data = yaml.safe_load(text)
        current = str(data.get("schema_version"))
        if current != "1.0":
            print(
                f"  refusing {path.name}: schema_version {current!r} is neither 1.0 "
                "nor already migrated",
                file=sys.stderr,
            )
            return 1

        # Rewrite the scalar in place rather than re-dumping the file: these are
        # hand-maintained examples whose comments and key order carry meaning, and
        # a yaml.safe_dump round-trip would discard both.
        #
        # Both quoted styles occur in this tree, so the pattern accepts either and
        # preserves whichever is used -- otherwise the rewrite is an unrequested
        # formatting change, and the first run refused rather than guessing.
        match = re.search(r"""(schema_version:\s*)(["']?)1\.0\2""", text)
        if not match:
            print(
                f"  refusing {path.name}: could not locate a schema_version of 1.0",
                file=sys.stderr,
            )
            return 1
        quote = match.group(2)
        text = (
            text[: match.start()]
            + f"{match.group(1)}{quote}{TARGET_VERSION}{quote}"
            + text[match.end() :]
        )

        path.write_text(text.rstrip("\n") + "\nexternal_dependencies: []\n")
        migrated.append(path.name)

    print(f"migrated {len(migrated)} of {len(todo)} candidates")
    for name in migrated:
        print(f"  + {name}")
    if skipped:
        print(f"  already migrated, left alone: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
