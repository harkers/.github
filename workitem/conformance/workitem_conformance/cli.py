"""Validate a ledger of WorkItem instances against the contract.

This is the entry point the reusable CI gate calls. It exists so the gate and the
test suite run *the same* checks -- a gate with its own inline copy of the rules
is a second implementation of the contract, which is the thing the contract
exists to prevent.

    python -m workitem_conformance.cli \\
        --contract-root /path/to/.github \\
        --ledger-root . \\
        --pattern '.workhub/workitems/*/workitem.yaml'

Exits non-zero when any instance is invalid.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from workitem_conformance.contract import load_contract
from workitem_conformance.instances import (
    InstanceProblem,
    check_instance,
    check_ledger,
    discover,
    load_instance,
)
from workitem_conformance.transitions import TransitionEngine


def validate(contract_root: Path, ledger_root: Path, pattern: str) -> list[InstanceProblem]:
    contract = load_contract(contract_root)
    engine = TransitionEngine(contract.state_machine)
    validator = Draft202012Validator(contract.schema)

    paths = discover(ledger_root, pattern)
    if not paths:
        return [
            InstanceProblem(
                str(ledger_root / pattern),
                "no-instances",
                "matched no WorkItem instances. A gate that matches nothing cannot fail, "
                "so this is an error rather than a pass. Remove the caller instead.",
            )
        ]

    problems: list[InstanceProblem] = []
    records: list[tuple[Path, dict]] = []

    for path in paths:
        try:
            item = load_instance(path)
        except (ValueError, yaml.YAMLError) as exc:
            problems.append(InstanceProblem(str(path), "unreadable", str(exc)))
            continue
        records.append((path, item))

        for error in sorted(validator.iter_errors(item), key=str):
            location = "/".join(str(p) for p in error.path) or "<root>"
            problems.append(InstanceProblem(str(path), "schema", f"{location}: {error.message}"))

        problems.extend(check_instance(path, item, contract, engine))

    problems.extend(check_ledger(records))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate WorkItem instances against the canonical contract."
    )
    parser.add_argument("--contract-root", required=True, type=Path)
    parser.add_argument("--ledger-root", required=True, type=Path)
    parser.add_argument(
        "--pattern",
        default=".workhub/workitems/*/workitem.yaml",
        help="glob, relative to --ledger-root, locating WorkItem instances",
    )
    args = parser.parse_args(argv)

    problems = validate(args.contract_root, args.ledger_root, args.pattern)

    if problems:
        print(f"::group::{len(problems)} contract violation(s)")
        for problem in problems:
            print(f"::error file={problem.path}::[{problem.rule}] {problem.detail}")
            print(f"  {problem}")
        print("::endgroup::")
        return 1

    print(f"All {len(discover(args.ledger_root, args.pattern))} WorkItem instance(s) valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
