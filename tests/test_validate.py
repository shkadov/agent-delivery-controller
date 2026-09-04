from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from adc.validate import load_protocol


def permissions(**overrides: bool) -> dict[str, bool]:
    result = {
        "repository_write": True,
        "merge": False,
        "external_write": False,
        "production_write": False,
        "workflow_write": False,
        "dependency_write": False,
        "infra_write": False,
    }
    result.update(overrides)
    return result


def task(task_id: str, files: list[str], **permission_overrides: bool) -> dict[str, Any]:
    return {
        "id": task_id,
        "goal": f"Implement {task_id}",
        "status": "ready",
        "owner": f"agent-{task_id.lower()}",
        "scope": {"files": files, "max_files": len(files)},
        "permissions": permissions(**permission_overrides),
        "acceptance": ["Tests pass"],
        "verification": {
            "commands": [f"pytest --junitxml=junit/{task_id}.xml"],
            "ci_tests": [f"test_{task_id.lower()}.py::test_passes"],
        },
        "stop_conditions": ["Scope expands"],
    }


def write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def protocol_dir(tmp_path: Path, tasks: list[dict[str, Any]]) -> Path:
    root = tmp_path / ".agent-delivery"
    write_yaml(
        root / "product.yaml",
        {
            "goal": "Reliable delivery",
            "constraints": ["GitHub Actions only"],
            "repositories": ["example/repo"],
            "agents": ["agent-bot"],
            "action_ceiling": permissions(workflow_write=True),
            "sensitive_paths": [".github/workflows/**", ".agent-delivery/**"],
        },
    )
    write_yaml(
        root / "roadmap.yaml",
        {"blocks": [{"id": "PHASE1", "goal": "Protocol", "exit_criteria": ["Validation passes"]}]},
    )
    write_yaml(
        root / "current" / "block.yaml",
        {
            "id": "PHASE1",
            "goal": "Protocol",
            "status": "implementing",
            "task_ids": [item["id"] for item in tasks],
        },
    )
    for item in tasks:
        write_yaml(root / "current" / "tasks" / f"{item['id']}.yaml", item)
    return root


def test_valid_protocol_loads(tmp_path: Path) -> None:
    root = protocol_dir(tmp_path, [task("B01", ["src/one.py"])])

    assert load_protocol(root).block.id == "PHASE1"


def test_overlapping_task_scope_is_rejected(tmp_path: Path) -> None:
    root = protocol_dir(
        tmp_path,
        [task("B01", ["src/shared.py"]), task("B02", ["src/shared.py"])],
    )

    with pytest.raises(ValueError, match="scope overlap"):
        load_protocol(root)


def test_permission_above_product_ceiling_is_rejected(tmp_path: Path) -> None:
    root = protocol_dir(tmp_path, [task("B01", ["src/one.py"], merge=True)])

    with pytest.raises(ValueError, match="exceeds product action ceiling: merge"):
        load_protocol(root)


def test_undeclared_task_is_rejected(tmp_path: Path) -> None:
    root = protocol_dir(tmp_path, [task("B01", ["src/one.py"])])
    write_yaml(root / "current" / "tasks" / "B02.yaml", task("B02", ["src/two.py"]))

    with pytest.raises(ValueError, match="undeclared tasks: B02"):
        load_protocol(root)


def test_current_block_must_exist_in_roadmap(tmp_path: Path) -> None:
    root = protocol_dir(tmp_path, [task("B01", ["src/one.py"])])
    block_path = root / "current" / "block.yaml"
    block = yaml.safe_load(block_path.read_text(encoding="utf-8"))
    block["id"] = "PHASE2"
    write_yaml(block_path, block)

    with pytest.raises(ValueError, match="not present in roadmap"):
        load_protocol(root)
