"""Load the canonical WorkItem contract from a contract root.

The conformance suite reads the contract as data. It never restates the
lifecycle, the policy or the sizing bands in Python: doing so would make this
suite a fourth description of the contract rather than a check on it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_ROOT = Path(__file__).resolve().parents[3]


class ContractError(Exception):
    """Raised when a contract root is missing a required artifact."""


@dataclass(frozen=True)
class Contract:
    root: Path
    schema: dict[str, Any]
    state_machine: dict[str, Any]
    policy: dict[str, Any]
    sizing_policy: dict[str, Any]
    version: dict[str, Any]


def _read_json(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        raise ContractError(f"missing contract artifact: {path}")
    return json.loads(path.read_text())


def _read_yaml(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        raise ContractError(f"missing contract artifact: {path}")
    loaded = yaml.safe_load(path.read_text())
    if not isinstance(loaded, dict):
        raise ContractError(f"contract artifact is not a mapping: {path}")
    return loaded


@lru_cache(maxsize=8)
def load_contract(root: Path | None = None) -> Contract:
    base = (root or DEFAULT_ROOT).resolve()
    return Contract(
        root=base,
        schema=_read_json(base, "workitem/v1.schema.json"),
        state_machine=_read_yaml(base, "workitem/state-machine.yaml"),
        policy=_read_yaml(base, "workitem/policy.yaml"),
        sizing_policy=_read_yaml(base, "workitem/sizing-policy.yaml"),
        version=_read_yaml(base, "workitem/contract-version.yaml"),
    )


def load_example(root: Path, name: str) -> dict[str, Any]:
    return _read_yaml(root, f"workitem/examples/{name}.yaml")


def band_for(tokens: int, sizing_policy: dict[str, Any]) -> str:
    """Return the declared band name for a token estimate."""
    for band in sizing_policy["bands"]:
        max_tokens = band["max_tokens"]
        if max_tokens is None or tokens < max_tokens:
            return band["name"]
    raise ContractError(f"no sizing band matched {tokens} tokens")


def requires_decomposition(tokens: int, sizing_policy: dict[str, Any]) -> bool:
    """True when the derived band mandates decomposition before execution."""
    return band_for(tokens, sizing_policy) == sizing_policy["decomposition"]["required_when_band"]


def parameter_modes(contract: Contract) -> list[str]:
    """Declared delivery_mode values, in declaration order."""
    return list(contract.state_machine["parameters"]["delivery_mode"]["values"])


def parameter_policies(contract: Contract) -> list[str]:
    """Declared review_policy values, in declaration order."""
    return list(contract.policy["parameters"]["review_policy"]["values"])


def combinations(contract: Contract) -> list[tuple[str, str]]:
    """Every (delivery_mode, review_policy) pair the contract declares."""
    return [(m, p) for m in parameter_modes(contract) for p in parameter_policies(contract)]
