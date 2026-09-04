"""Deterministic evidence serialization."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from adc.schema import CommandEvidence, Evidence

COMMAND_LIST = TypeAdapter(list[CommandEvidence])


def evidence_bytes(evidence: Evidence) -> bytes:
    """Serialize evidence canonically; identical model inputs produce identical bytes."""
    payload = evidence.model_dump(mode="json")
    return (json.dumps(payload, indent=2, sort_keys=True, separators=(",", ": ")) + "\n").encode()


def write_evidence(path: Path, evidence: Evidence) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(evidence_bytes(evidence))


def read_evidence(path: Path) -> Evidence:
    return Evidence.model_validate_json(path.read_bytes())


def write_command_evidence(path: Path, commands: list[CommandEvidence]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [command.model_dump(mode="json") for command in commands]
    content = json.dumps(payload, indent=2, sort_keys=True, separators=(",", ": ")) + "\n"
    path.write_text(content, encoding="utf-8")


def read_command_evidence(path: Path) -> list[CommandEvidence]:
    return COMMAND_LIST.validate_json(path.read_bytes())
