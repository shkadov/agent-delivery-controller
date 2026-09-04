"""Thin, read-only wrapper around the authenticated GitHub CLI."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any

from adc.check import CheckFailed, CommitIdentity


@dataclass(frozen=True)
class PullRequest:
    number: int
    actor: str
    base_sha: str
    head_sha: str
    changed_files: tuple[str, ...]
    commits: tuple[CommitIdentity, ...]


class GitHubClient:
    def __init__(self, repository: str) -> None:
        if repository == "self":
            repository = os.environ.get("GITHUB_REPOSITORY", "")
            if not repository:
                raise CheckFailed("GITHUB_REPOSITORY is required when repository is 'self'")
        self.repository = repository

    def api(self, endpoint: str, *, paginate: bool = False) -> Any:
        command = ["gh", "api", endpoint]
        if paginate:
            command.extend(["--paginate", "--slurp"])
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise CheckFailed(f"gh api failed: {completed.stderr.strip()}")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise CheckFailed("gh api returned invalid JSON") from exc

    def pull_request(self, number: int) -> PullRequest:
        prefix = f"repos/{self.repository}/pulls/{number}"
        raw = self.api(prefix)
        pages = self.api(f"{prefix}/files?per_page=100", paginate=True)
        file_records = [record for page in pages for record in page]
        commit_pages = self.api(f"{prefix}/commits?per_page=100", paginate=True)
        commit_records = [record for page in commit_pages for record in page]
        return PullRequest(
            number=number,
            actor=str(raw["user"]["login"]),
            base_sha=str(raw["base"]["sha"]),
            head_sha=str(raw["head"]["sha"]),
            changed_files=tuple(sorted(str(record["filename"]) for record in file_records)),
            commits=tuple(
                CommitIdentity(
                    sha=str(record["sha"]),
                    author=str(record["commit"]["author"]["name"]),
                    message=str(record["commit"]["message"]),
                )
                for record in commit_records
            ),
        )
