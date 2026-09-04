"""Machine-checkable local, pull-request, and post-merge assertions."""

from __future__ import annotations

import fnmatch
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from adc.schema import CommandEvidence, Product, Task

TestStatus = Literal["passed", "failed", "skipped", "missing"]


class CheckFailed(ValueError):
    """One or more delivery assertions failed."""


@dataclass(frozen=True)
class CommitIdentity:
    sha: str
    author: str
    message: str


@dataclass(frozen=True)
class CheckOutcome:
    changed_files: tuple[str, ...]
    commands: tuple[CommandEvidence, ...]
    ci_tests: dict[str, TestStatus]


class GitRepository:
    """Small subprocess adapter around git; intentionally easy to exercise in fixture repos."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def run(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise CheckFailed(f"git {' '.join(args)} failed: {detail}")
        return completed.stdout

    def staged_files(self) -> tuple[str, ...]:
        output = self.run("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
        return tuple(sorted(item for item in output.split("\0") if item))

    def configured_author(self) -> str:
        identity = self.run("var", "GIT_AUTHOR_IDENT").strip()
        return identity.split(" <", 1)[0]

    def head_sha(self) -> str:
        return self.run("rev-parse", "HEAD").strip()

    def commit_time(self, sha: str) -> str:
        return self.run("show", "-s", "--format=%cI", sha).strip()

    def commits(self, base_sha: str, head_sha: str) -> tuple[CommitIdentity, ...]:
        shas = self.run("rev-list", "--reverse", f"{base_sha}..{head_sha}").splitlines()
        return tuple(
            CommitIdentity(
                sha=sha,
                author=self.run("show", "-s", "--format=%an", sha).strip(),
                message=self.run("show", "-s", "--format=%B", sha).strip(),
            )
            for sha in shas
        )

    def blob_hash(self, commit_sha: str, file_name: str) -> str:
        return self.run("rev-parse", f"{commit_sha}:{file_name}").strip()


def check_local(
    repo: GitRepository,
    product: Product,
    task: Task,
    *,
    commit_message: str | None = None,
) -> CheckOutcome:
    changed_files = repo.staged_files()
    check_changed_files(product, task, changed_files)
    check_author(repo.configured_author(), task)
    if commit_message is not None:
        check_task_trailer(commit_message, task)
    return CheckOutcome(changed_files=changed_files, commands=(), ci_tests={})


def check_pull_request(
    product: Product,
    task: Task,
    *,
    actor: str,
    changed_files: Sequence[str],
    commits: Sequence[CommitIdentity],
    pr_head_sha: str,
    tested_sha: str,
    junit_paths: Sequence[Path],
    command_evidence: Sequence[CommandEvidence] = (),
) -> CheckOutcome:
    if actor not in product.agents:
        return CheckOutcome(changed_files=tuple(sorted(changed_files)), commands=(), ci_tests={})

    check_changed_files(product, task, changed_files)
    if not commits:
        raise CheckFailed("PR contains no commits")
    for commit in commits:
        check_author(commit.author, task, context=f"commit {commit.sha}")
        check_task_trailer(commit.message, task, context=f"commit {commit.sha}")
    check_tested_sha(pr_head_sha, tested_sha)
    check_commands(task, command_evidence)
    observed = read_junit(junit_paths)
    required = require_ci_tests(task, observed)
    return CheckOutcome(
        changed_files=tuple(sorted(changed_files)),
        commands=tuple(command_evidence),
        ci_tests=required,
    )


def check_changed_files(product: Product, task: Task, changed_files: Sequence[str]) -> None:
    changed = set(changed_files)
    outside = sorted(changed - set(task.scope.files))
    failures: list[str] = []
    if outside:
        failures.append("files outside task scope: " + ", ".join(outside))
    if len(changed) > task.scope.max_files:
        failures.append(
            f"changed file count {len(changed)} exceeds max_files {task.scope.max_files}"
        )

    for file_name in sorted(changed):
        permission = required_sensitive_permission(product, file_name)
        if permission == "controller_only":
            failures.append(f"controller-owned path changed: {file_name}")
        elif permission is not None and not getattr(task.permissions, permission):
            failures.append(f"{file_name} requires permissions.{permission}=true")
    if failures:
        raise CheckFailed("; ".join(failures))


def required_sensitive_permission(product: Product, file_name: str) -> str | None:
    matching = [pattern for pattern in product.sensitive_paths if _path_matches(file_name, pattern)]
    if not matching:
        return None
    if file_name == ".agent-delivery" or file_name.startswith(".agent-delivery/"):
        return "controller_only"
    if file_name.startswith(".github/workflows/"):
        return "workflow_write"
    dependency_names = (".lock", "package-lock.json", "requirements", "pyproject.toml")
    if any(fragment in file_name for fragment in dependency_names):
        return "dependency_write"
    infrastructure_names = ("/terraform/", "/infra/", "Dockerfile")
    padded = f"/{file_name}"
    if any(fragment in padded for fragment in infrastructure_names):
        return "infra_write"
    raise CheckFailed(
        f"sensitive path {file_name!r} matches {matching!r} but has no permission mapping"
    )


def _path_matches(file_name: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(file_name, pattern) or (
        pattern.startswith("**/") and fnmatch.fnmatchcase(file_name, pattern[3:])
    )


def check_author(author: str, task: Task, *, context: str = "commit") -> None:
    if author != task.owner:
        raise CheckFailed(f"{context} author {author!r} does not match task owner {task.owner!r}")


def check_task_trailer(message: str, task: Task, *, context: str = "commit") -> None:
    expected = f"ADC-Task: {task.id}"
    trailers = [line.strip() for line in message.splitlines() if line.startswith("ADC-Task:")]
    if trailers != [expected]:
        raise CheckFailed(f"{context} must contain exactly one {expected!r} trailer")


def check_tested_sha(pr_head_sha: str, tested_sha: str) -> None:
    if pr_head_sha != tested_sha:
        raise CheckFailed(f"PR head {pr_head_sha} differs from CI-tested SHA {tested_sha}")


def check_commands(task: Task, evidence: Sequence[CommandEvidence]) -> None:
    actual = [item.command for item in evidence]
    if actual != task.verification.commands:
        raise CheckFailed("command evidence does not match verification.commands")
    failures = [item.command for item in evidence if item.exit_code != 0]
    if failures:
        raise CheckFailed("verification commands failed: " + ", ".join(failures))


def read_junit(paths: Sequence[Path]) -> dict[str, TestStatus]:
    results: dict[str, TestStatus] = {}
    xml_files = sorted(
        path
        for supplied in paths
        for path in ([supplied] if supplied.is_file() else supplied.rglob("*.xml"))
    )
    if not xml_files:
        raise CheckFailed("no junit XML files found")
    for path in xml_files:
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as exc:
            raise CheckFailed(f"cannot read junit XML {path}: {exc}") from exc
        for case in root.iter("testcase"):
            status: TestStatus = "passed"
            if case.find("failure") is not None or case.find("error") is not None:
                status = "failed"
            elif case.find("skipped") is not None:
                status = "skipped"
            for test_id in _junit_ids(case):
                results[test_id] = _worse_status(results.get(test_id), status)
    return results


def _junit_ids(case: ET.Element) -> set[str]:
    name = case.attrib.get("name", "")
    classname = case.attrib.get("classname", "")
    file_name = case.attrib.get("file")
    ids = {f"{classname}::{name}"}
    if file_name:
        ids.add(f"{file_name}::{name}")
    parts = classname.split(".")
    class_parts: list[str] = []
    if parts and parts[-1].startswith("Test"):
        class_parts.append(parts.pop())
    if parts:
        module_path = "/".join(parts) + ".py"
        ids.add("::".join([module_path, *class_parts, name]))
    return {
        test_id for test_id in ids if not test_id.startswith("::") and not test_id.endswith("::")
    }


def _worse_status(current: TestStatus | None, new: TestStatus) -> TestStatus:
    priority = {"missing": 3, "failed": 2, "skipped": 1, "passed": 0}
    return new if current is None or priority[new] > priority[current] else current


def require_ci_tests(task: Task, observed: dict[str, TestStatus]) -> dict[str, TestStatus]:
    required: dict[str, TestStatus] = {
        test_id: observed.get(test_id, "missing") for test_id in task.verification.ci_tests
    }
    failures = [test_id for test_id, status in required.items() if status != "passed"]
    if failures:
        detail = ", ".join(f"{test_id} ({required[test_id]})" for test_id in failures)
        raise CheckFailed(f"required CI tests did not pass: {detail}")
    return required


def compare_scoped_blobs(
    repo: GitRepository, task: Task, *, reviewed_sha: str, merged_sha: str
) -> None:
    mismatches: list[str] = []
    for file_name in task.scope.files:
        try:
            reviewed_blob = repo.blob_hash(reviewed_sha, file_name)
            merged_blob = repo.blob_hash(merged_sha, file_name)
        except CheckFailed as exc:
            mismatches.append(f"{file_name} ({exc})")
            continue
        if reviewed_blob != merged_blob:
            mismatches.append(file_name)
    if mismatches:
        raise CheckFailed("merged blobs differ from reviewed head: " + ", ".join(mismatches))
