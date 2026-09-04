"""Cross-document validation for an agent-delivery directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from adc.schema import Block, Product, Roadmap, Task, load_yaml


@dataclass(frozen=True)
class Protocol:
    root: Path
    product: Product
    roadmap: Roadmap
    block: Block
    tasks: tuple[Task, ...]


def load_protocol(root: Path) -> Protocol:
    """Load and validate an entire ``.agent-delivery`` directory."""
    root = root.resolve()
    try:
        product = load_yaml(root / "product.yaml", Product)
        roadmap = load_yaml(root / "roadmap.yaml", Roadmap)
        block = load_yaml(root / "current" / "block.yaml", Block)
        tasks = tuple(
            load_yaml(path, Task) for path in sorted((root / "current" / "tasks").glob("*.yaml"))
        )
    except (OSError, ValueError, ValidationError) as exc:
        raise ValueError(str(exc)) from exc

    if not tasks:
        raise ValueError("current/tasks must contain at least one task YAML file")

    task_by_id = {task.id: task for task in tasks}
    if len(task_by_id) != len(tasks):
        raise ValueError("task ids must be unique")

    declared = set(block.task_ids)
    actual = set(task_by_id)
    if declared != actual:
        missing = sorted(declared - actual)
        unexpected = sorted(actual - declared)
        details = []
        if missing:
            details.append(f"missing tasks: {', '.join(missing)}")
        if unexpected:
            details.append(f"undeclared tasks: {', '.join(unexpected)}")
        raise ValueError("block task list mismatch (" + "; ".join(details) + ")")

    roadmap_ids = {item.id for item in roadmap.blocks}
    if block.id not in roadmap_ids:
        raise ValueError(f"current block {block.id!r} is not present in roadmap.yaml")

    owners: dict[str, str] = {}
    for task in tasks:
        for file_name in task.scope.files:
            if file_name in owners:
                raise ValueError(
                    f"scope overlap: {file_name!r} is owned by both "
                    f"{owners[file_name]} and {task.id}"
                )
            owners[file_name] = task.id
        _permissions_within_ceiling(task, product)

    return Protocol(root, product, roadmap, block, tasks)


def _permissions_within_ceiling(task: Task, product: Product) -> None:
    requested = task.permissions.model_dump()
    ceiling = product.action_ceiling.model_dump()
    excessive = sorted(key for key, enabled in requested.items() if enabled and not ceiling[key])
    if excessive:
        raise ValueError(f"task {task.id} exceeds product action ceiling: {', '.join(excessive)}")
