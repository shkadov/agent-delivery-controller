"""Strict models for the ``.agent-delivery`` protocol."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_-]*$")]
NonEmpty = Annotated[str, Field(min_length=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TaskStatus(StrEnum):
    READY = "ready"
    IMPLEMENTING = "implementing"
    VERIFIED = "verified"
    MERGED = "merged"
    ARCHIVED = "archived"
    CANCELLED = "cancelled"


class ActionCeiling(StrictModel):
    repository_write: bool
    merge: bool
    external_write: bool
    production_write: bool
    workflow_write: bool = False
    dependency_write: bool = False
    infra_write: bool = False


DEFAULT_SENSITIVE_PATHS = [
    ".github/workflows/**",
    ".agent-delivery/**",
    "**/*.lock",
    "**/package-lock.json",
    "**/requirements*.txt",
    "**/pyproject.toml",
    "**/.env*",
    "**/terraform/**",
    "**/infra/**",
    "**/Dockerfile*",
]


class Product(StrictModel):
    goal: NonEmpty
    constraints: list[NonEmpty] = Field(min_length=1)
    repositories: list[NonEmpty] = Field(min_length=1)
    agents: list[NonEmpty] = Field(min_length=1)
    action_ceiling: ActionCeiling
    sensitive_paths: list[NonEmpty] = Field(
        default_factory=lambda: list(DEFAULT_SENSITIVE_PATHS), min_length=1
    )

    @field_validator("agents", "repositories", "sensitive_paths")
    @classmethod
    def entries_are_unique(cls, values: list[str]) -> list[str]:
        _require_unique(values, "entry")
        return values


class RoadmapBlock(StrictModel):
    id: Identifier
    goal: NonEmpty
    exit_criteria: list[NonEmpty] = Field(min_length=1)


class Roadmap(StrictModel):
    blocks: list[RoadmapBlock] = Field(min_length=1)

    @model_validator(mode="after")
    def block_ids_are_unique(self) -> Roadmap:
        _require_unique([block.id for block in self.blocks], "roadmap block id")
        return self


class Block(StrictModel):
    id: Identifier
    goal: NonEmpty
    status: TaskStatus
    task_ids: list[Identifier] = Field(min_length=1)

    @model_validator(mode="after")
    def task_ids_are_unique(self) -> Block:
        _require_unique(self.task_ids, "task id")
        return self


class Scope(StrictModel):
    files: list[NonEmpty] = Field(min_length=1)
    max_files: int = Field(gt=0)

    @field_validator("files")
    @classmethod
    def files_are_safe_repo_paths(cls, files: list[str]) -> list[str]:
        _require_unique(files, "scope file")
        for value in files:
            path = PurePosixPath(value)
            if path.is_absolute() or ".." in path.parts or value.endswith("/"):
                raise ValueError(f"scope file must be a repository-relative file: {value!r}")
            if path.parts and path.parts[0] == ".agent-delivery":
                raise ValueError(".agent-delivery/** is controller-owned and cannot be task scope")
        return files


class Permissions(ActionCeiling):
    pass


class Verification(StrictModel):
    commands: list[NonEmpty] = Field(min_length=1)
    ci_tests: list[NonEmpty] = Field(min_length=1)

    @model_validator(mode="after")
    def entries_are_unique(self) -> Verification:
        _require_unique(self.commands, "verification command")
        _require_unique(self.ci_tests, "CI test id")
        unqualified = sorted(test_id for test_id in self.ci_tests if "::" not in test_id)
        if unqualified:
            raise ValueError(
                "ci_tests must use fully qualified test IDs: " + ", ".join(unqualified)
            )
        return self


class Task(StrictModel):
    id: Identifier
    goal: NonEmpty
    status: TaskStatus
    owner: NonEmpty
    scope: Scope
    permissions: Permissions
    acceptance: list[NonEmpty] = Field(min_length=1)
    verification: Verification
    stop_conditions: list[NonEmpty] = Field(min_length=1)


class CommandEvidence(StrictModel):
    command: NonEmpty
    exit_code: int
    output_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class EvidenceBody(StrictModel):
    task_id: Identifier
    commit_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    changed_files: list[str]
    commands: list[CommandEvidence]
    ci_tests: dict[str, Literal["passed", "failed", "skipped", "missing"]]
    passed: bool


class EvidenceMeta(StrictModel):
    generated_at: NonEmpty
    adc_version: NonEmpty


class Evidence(StrictModel):
    body: EvidenceBody
    meta: EvidenceMeta


MODEL_REGISTRY: dict[str, type[StrictModel]] = {
    "product": Product,
    "roadmap": Roadmap,
    "block": Block,
    "task": Task,
    "evidence": Evidence,
}


def _require_unique(values: list[str], label: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"duplicate {label}(s): {', '.join(duplicates)}")


def load_yaml[ModelT: StrictModel](path: Path, model: type[ModelT]) -> ModelT:
    """Load one YAML file and validate it against ``model``."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if raw is None:
        raise ValueError(f"empty YAML document: {path}")
    return model.model_validate(raw)


def export_json_schemas(destination: Path) -> list[Path]:
    """Write deterministic JSON schemas for all public protocol documents."""
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, model in sorted(MODEL_REGISTRY.items()):
        path = destination / f"{name}.schema.json"
        content = json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
