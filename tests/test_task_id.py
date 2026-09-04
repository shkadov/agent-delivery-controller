from pathlib import Path


def test_task_id_format_is_documented_as_shell_safe() -> None:
    workflow = Path(".github/workflows/adc-check.yml").read_text(encoding="utf-8")

    assert "grep -qE '^[A-Z][A-Z0-9_-]*$'" in workflow
    assert "TASK_ID: ${{ steps.task.outputs.id }}" in workflow
    assert 'adc check "$TASK_ID"' in workflow
