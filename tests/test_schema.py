from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from adc.schema import Task, TaskStatus, export_json_schemas


def task_data() -> dict[str, Any]:
    return {
        "id": "B01",
        "goal": "Verify identity",
        "status": "ready",
        "owner": "agent-1",
        "scope": {"files": ["src/identity.py"], "max_files": 1},
        "permissions": {
            "repository_write": True,
            "merge": False,
            "external_write": False,
            "production_write": False,
            "workflow_write": False,
            "dependency_write": False,
            "infra_write": False,
        },
        "acceptance": ["Exact head SHA is verified"],
        "verification": {
            "commands": ["pytest tests/test_identity.py --junitxml=junit/B01.xml"],
            "ci_tests": ["test_identity.py::test_head_sha_verified"],
        },
        "stop_conditions": ["Required scope expands"],
    }


def test_unknown_field_is_rejected() -> None:
    data = task_data()
    data["surprise"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Task.model_validate(data)


def test_missing_permissions_are_rejected() -> None:
    data = task_data()
    del data["permissions"]

    with pytest.raises(ValidationError, match="permissions"):
        Task.model_validate(data)


def test_protocol_directory_is_rejected_from_scope() -> None:
    data = task_data()
    data["scope"]["files"] = [".agent-delivery/current/tasks/B01.yaml"]

    with pytest.raises(ValidationError, match="controller-owned"):
        Task.model_validate(data)


def test_parent_traversal_is_rejected_from_scope() -> None:
    data = task_data()
    data["scope"]["files"] = ["../outside.py"]

    with pytest.raises(ValidationError, match="repository-relative"):
        Task.model_validate(data)


def test_complexity_budget_may_exceed_declared_scope() -> None:
    data = task_data()
    data["scope"]["max_files"] = 2

    assert Task.model_validate(data).scope.max_files == 2


def test_ci_test_id_must_be_fully_qualified() -> None:
    data = task_data()
    data["verification"]["ci_tests"] = ["test_head_sha_verified"]

    with pytest.raises(ValidationError, match="fully qualified"):
        Task.model_validate(data)


def test_cancelled_is_a_valid_terminal_state() -> None:
    data = task_data()
    data["status"] = "cancelled"

    assert Task.model_validate(data).status is TaskStatus.CANCELLED


def test_schema_export_is_deterministic(tmp_path: Path) -> None:
    export_json_schemas(tmp_path)
    first = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    export_json_schemas(tmp_path)
    second = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    assert first == second
    assert json.loads(first["task.schema.json"])["additionalProperties"] is False
