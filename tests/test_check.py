from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from adc.check import (
    CheckFailed,
    CommitIdentity,
    GitRepository,
    check_changed_files,
    check_local,
    check_pull_request,
    compare_scoped_blobs,
)
from adc.schema import CommandEvidence, Product, Task


def run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    run_git(tmp_path, "init", "-q")
    run_git(tmp_path, "config", "user.name", "automation-bot")
    run_git(tmp_path, "config", "user.email", "automation@example.invalid")
    (tmp_path / "owned.py").write_text("before\n", encoding="utf-8")
    run_git(tmp_path, "add", "owned.py")
    run_git(tmp_path, "commit", "-q", "-m", "chore: initialize fixture")
    return tmp_path


def product_data() -> dict[str, Any]:
    return {
        "goal": "Reliable delivery",
        "constraints": ["GitHub Actions only"],
        "repositories": ["example/repo"],
        "agents": ["agent-bot"],
        "action_ceiling": {
            "repository_write": True,
            "merge": False,
            "external_write": False,
            "production_write": False,
            "workflow_write": True,
            "dependency_write": True,
            "infra_write": True,
        },
    }


def task_data(files: list[str] | None = None, **permissions: bool) -> dict[str, Any]:
    allowed = {
        "repository_write": True,
        "merge": False,
        "external_write": False,
        "production_write": False,
        "workflow_write": False,
        "dependency_write": False,
        "infra_write": False,
    }
    allowed.update(permissions)
    return {
        "id": "B02",
        "goal": "Enforce checks",
        "status": "implementing",
        "owner": "automation-bot",
        "scope": {"files": files or ["owned.py"], "max_files": 3},
        "permissions": allowed,
        "acceptance": ["Checks fail closed"],
        "verification": {
            "commands": ["pytest --junitxml=junit/B02.xml"],
            "ci_tests": ["tests/test_check.py::test_expected"],
        },
        "stop_conditions": ["Scope expands"],
    }


def models(files: list[str] | None = None, **permissions: bool) -> tuple[Product, Task]:
    return Product.model_validate(product_data()), Task.model_validate(
        task_data(files, **permissions)
    )


def successful_command(task: Task) -> list[CommandEvidence]:
    return [
        CommandEvidence(command=task.verification.commands[0], exit_code=0, output_sha256="a" * 64)
    ]


def test_file_outside_scope_fails() -> None:
    product, task = models()

    with pytest.raises(CheckFailed, match=r"outside task scope: other\.py"):
        check_changed_files(product, task, ["other.py"])


def test_sensitive_path_requires_matching_permission() -> None:
    product, task = models(["pyproject.toml"])

    with pytest.raises(CheckFailed, match="dependency_write"):
        check_changed_files(product, task, ["pyproject.toml"])


def test_protocol_path_is_always_controller_owned() -> None:
    product, task = models()

    with pytest.raises(CheckFailed, match="controller-owned"):
        check_changed_files(product, task, [".agent-delivery/product.yaml"])


def test_local_check_uses_real_staged_diff(git_repo: Path) -> None:
    product, task = models()
    (git_repo / "owned.py").write_text("after\n", encoding="utf-8")
    run_git(git_repo, "add", "owned.py")

    outcome = check_local(
        GitRepository(git_repo),
        product,
        task,
        commit_message="feat: update fixture\n\nADC-Task: B02\n",
    )

    assert outcome.changed_files == ("owned.py",)


def test_wrong_trailer_fails(git_repo: Path) -> None:
    product, task = models()

    with pytest.raises(CheckFailed, match="ADC-Task: B02"):
        check_local(
            GitRepository(git_repo),
            product,
            task,
            commit_message="feat: update fixture\n\nADC-Task: OTHER\n",
        )


def test_pr_head_mismatch_fails() -> None:
    product, task = models()

    with pytest.raises(CheckFailed, match="differs from CI-tested SHA"):
        check_pull_request(
            product,
            task,
            actor="agent-bot",
            changed_files=["owned.py"],
            commits=[CommitIdentity("a" * 40, "automation-bot", "ADC-Task: B02")],
            pr_head_sha="a" * 40,
            tested_sha="b" * 40,
            junit_paths=[],
        )


def test_missing_ci_test_fails(tmp_path: Path) -> None:
    product, task = models()
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuite><testcase classname="tests.test_check" name="test_other" /></testsuite>',
        encoding="utf-8",
    )

    with pytest.raises(CheckFailed, match="missing"):
        check_pull_request(
            product,
            task,
            actor="agent-bot",
            changed_files=["owned.py"],
            commits=[CommitIdentity("a" * 40, "automation-bot", "ADC-Task: B02")],
            pr_head_sha="a" * 40,
            tested_sha="a" * 40,
            junit_paths=[junit],
            command_evidence=successful_command(task),
        )


def test_fully_qualified_ci_test_passes(tmp_path: Path) -> None:
    product, task = models()
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuite><testcase classname="tests.test_check" name="test_expected" /></testsuite>',
        encoding="utf-8",
    )

    outcome = check_pull_request(
        product,
        task,
        actor="agent-bot",
        changed_files=["owned.py"],
        commits=[CommitIdentity("a" * 40, "automation-bot", "ADC-Task: B02")],
        pr_head_sha="a" * 40,
        tested_sha="a" * 40,
        junit_paths=[junit],
        command_evidence=successful_command(task),
    )

    assert outcome.ci_tests == {"tests/test_check.py::test_expected": "passed"}


def test_post_merge_compares_scoped_blobs(git_repo: Path) -> None:
    _, task = models()
    reviewed = run_git(git_repo, "rev-parse", "HEAD")
    (git_repo / "owned.py").write_text("changed after review\n", encoding="utf-8")
    run_git(git_repo, "add", "owned.py")
    run_git(git_repo, "commit", "-q", "-m", "fix: alter reviewed file")
    merged = run_git(git_repo, "rev-parse", "HEAD")

    with pytest.raises(CheckFailed, match=r"owned\.py"):
        compare_scoped_blobs(
            GitRepository(git_repo), task, reviewed_sha=reviewed, merged_sha=merged
        )
