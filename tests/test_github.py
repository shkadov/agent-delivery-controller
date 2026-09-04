from __future__ import annotations

import json
from subprocess import CompletedProcess

from pytest import MonkeyPatch

from adc.github import GitHubClient


def test_pull_request_reads_identity_shas_and_paginated_files(monkeypatch: MonkeyPatch) -> None:
    responses = [
        {
            "user": {"login": "agent-bot"},
            "base": {"sha": "a" * 40},
            "head": {"sha": "b" * 40},
        },
        [[{"filename": "z.py"}, {"filename": "a.py"}]],
    ]

    def fake_run(*args: object, **kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(responses.pop(0)), stderr=""
        )

    monkeypatch.setattr("adc.github.subprocess.run", fake_run)

    pull = GitHubClient("example/repo").pull_request(7)

    assert pull.actor == "agent-bot"
    assert pull.base_sha == "a" * 40
    assert pull.head_sha == "b" * 40
    assert pull.changed_files == ("a.py", "z.py")


def test_self_repository_comes_from_actions_environment(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/repository")

    assert GitHubClient("self").repository == "example/repository"
