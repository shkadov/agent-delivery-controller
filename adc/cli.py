"""Command-line interface for ADC."""

from __future__ import annotations

import subprocess
from pathlib import Path

import click

from adc import __version__
from adc.check import (
    CheckFailed,
    GitRepository,
    TestStatus,
    check_local,
    check_pull_request,
    check_pull_request_policy,
    compare_scoped_blobs,
)
from adc.evidence import read_command_evidence, write_command_evidence, write_evidence
from adc.github import GitHubClient
from adc.schema import (
    CommandEvidence,
    Evidence,
    EvidenceBody,
    EvidenceMeta,
    Task,
    export_json_schemas,
)
from adc.validate import load_protocol


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="agent-delivery-controller")
def main() -> None:
    """Enforce machine-checkable delivery controls for coding agents."""


@main.command("validate")
@click.argument(
    "protocol_dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path(".agent-delivery"),
)
def validate_command(protocol_dir: Path) -> None:
    """Validate all protocol files and cross-file invariants."""
    try:
        protocol = load_protocol(protocol_dir)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"valid: block {protocol.block.id}, {len(protocol.tasks)} task(s), "
        f"{sum(len(task.scope.files) for task in protocol.tasks)} owned file(s)"
    )


@main.command("schema")
@click.option(
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("docs/schema"),
    show_default=True,
)
def schema_command(output: Path) -> None:
    """Export JSON Schema files for editor and CI validation."""
    written = export_json_schemas(output)
    click.echo(f"wrote {len(written)} schemas to {output}")


@main.command("ci-run")
@click.argument("task_id")
@click.option(
    "--protocol-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path(".agent-delivery"),
    show_default=True,
)
@click.option(
    "--result",
    type=click.Path(path_type=Path, dir_okay=False),
    required=True,
    help="Write deterministic command provenance JSON.",
)
def ci_run_command(task_id: str, protocol_dir: Path, result: Path) -> None:
    """Run a task's declared verification commands in the CI test job."""
    try:
        protocol = load_protocol(protocol_dir)
        task = _find_task(protocol.tasks, task_id)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    failures: list[str] = []
    evidence: list[CommandEvidence] = []
    for command in task.verification.commands:
        click.echo(f"verification: {command}")
        completed = subprocess.run(command, shell=True, check=False, capture_output=True)
        click.echo(completed.stdout.decode(errors="replace"), nl=False)
        click.echo(completed.stderr.decode(errors="replace"), nl=False, err=True)
        evidence.append(
            CommandEvidence(
                command=command,
                exit_code=completed.returncode,
            )
        )
        if completed.returncode != 0:
            failures.append(f"{command!r} exited {completed.returncode}")
    write_command_evidence(result, evidence)
    if failures:
        raise click.ClickException("; ".join(failures))


@main.command("check")
@click.argument("task_id")
@click.option("--local", "local_mode", is_flag=True, help="Check the staged local change.")
@click.option("--pr", "pr_number", type=click.IntRange(min=1), help="Check a GitHub pull request.")
@click.option("--post-merge", is_flag=True, help="Compare reviewed and merged scoped blobs.")
@click.option(
    "--protocol-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path(".agent-delivery"),
    show_default=True,
)
@click.option(
    "--repo-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("."),
    show_default=True,
)
@click.option("--commit-msg-file", type=click.Path(path_type=Path, dir_okay=False))
@click.option("--junit", "junit_paths", multiple=True, type=click.Path(path_type=Path, exists=True))
@click.option("--tested-sha-file", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option("--command-results", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option(
    "--policy-only",
    is_flag=True,
    help="Evaluate policy from trusted base code without reading CI artifacts.",
)
@click.option("--reviewed-sha")
@click.option("--merged-sha")
def check_command(
    task_id: str,
    local_mode: bool,
    pr_number: int | None,
    post_merge: bool,
    protocol_dir: Path,
    repo_dir: Path,
    commit_msg_file: Path | None,
    junit_paths: tuple[Path, ...],
    tested_sha_file: Path | None,
    command_results: Path | None,
    policy_only: bool,
    reviewed_sha: str | None,
    merged_sha: str | None,
) -> None:
    """Check TASK_ID locally, on a PR, or after merge."""
    selected = sum((local_mode, pr_number is not None, post_merge))
    if selected != 1:
        raise click.UsageError("select exactly one of --local, --pr, or --post-merge")
    try:
        protocol = load_protocol(protocol_dir)
        task = _find_task(protocol.tasks, task_id)
        repo = GitRepository(repo_dir)

        if local_mode:
            message = commit_msg_file.read_text(encoding="utf-8") if commit_msg_file else None
            outcome = check_local(repo, protocol.product, task, commit_message=message)
            click.echo(f"passed: {task.id} local ({len(outcome.changed_files)} changed file(s))")
            return

        if pr_number is not None:
            github = GitHubClient(protocol.product.repositories[0])
            pull = github.pull_request(pr_number)
            if pull.actor not in protocol.product.agents:
                click.echo(f"exempt: PR #{pr_number} actor {pull.actor!r} is not an ADC agent")
                return
            if policy_only:
                outcome = check_pull_request_policy(
                    protocol.product,
                    task,
                    actor=pull.actor,
                    changed_files=pull.changed_files,
                    commits=pull.commits,
                )
                click.echo(
                    f"passed: {task.id} PR #{pr_number} policy "
                    f"({len(outcome.changed_files)} changed file(s))"
                )
                return
            if tested_sha_file is None or command_results is None or not junit_paths:
                raise click.UsageError(
                    "--pr requires --tested-sha-file, --command-results, and at least one --junit"
                )
            tested_sha = tested_sha_file.read_text(encoding="utf-8").strip()
            outcome = check_pull_request(
                protocol.product,
                task,
                actor=pull.actor,
                changed_files=pull.changed_files,
                commits=pull.commits,
                pr_head_sha=pull.head_sha,
                tested_sha=tested_sha,
                junit_paths=junit_paths,
                command_evidence=read_command_evidence(command_results),
            )
            evidence = _evidence(
                task,
                pull.head_sha,
                repo,
                outcome.changed_files,
                outcome.commands,
                outcome.ci_tests,
            )
            output = protocol.root / "evidence" / f"{task.id}.json"
            write_evidence(output, evidence)
            click.echo(f"passed: {task.id} PR #{pr_number}; wrote {output}")
            return

        if reviewed_sha is None or merged_sha is None:
            raise click.UsageError("--post-merge requires --reviewed-sha and --merged-sha")
        compare_scoped_blobs(repo, task, reviewed_sha=reviewed_sha, merged_sha=merged_sha)
        evidence = _evidence(task, merged_sha, repo, task.scope.files, (), {})
        output = protocol.root / "evidence" / f"{task.id}.merged.json"
        write_evidence(output, evidence)
        click.echo(f"passed: {task.id} post-merge; wrote {output}")
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


def _find_task(tasks: tuple[Task, ...], task_id: str) -> Task:
    try:
        return next(task for task in tasks if task.id == task_id)
    except StopIteration as exc:
        raise CheckFailed(f"unknown active task: {task_id}") from exc


def _evidence(
    task: Task,
    commit_sha: str,
    repo: GitRepository,
    changed_files: tuple[str, ...] | list[str],
    commands: tuple[CommandEvidence, ...],
    ci_tests: dict[str, TestStatus],
) -> Evidence:
    return Evidence(
        body=EvidenceBody(
            task_id=task.id,
            commit_sha=commit_sha,
            changed_files=sorted(changed_files),
            commands=list(commands),
            ci_tests=ci_tests,
            passed=True,
        ),
        meta=EvidenceMeta(generated_at=repo.commit_time(commit_sha), adc_version=__version__),
    )


if __name__ == "__main__":
    main()
