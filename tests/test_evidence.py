from pathlib import Path

from adc.evidence import evidence_bytes, read_evidence, write_evidence
from adc.schema import Evidence, EvidenceBody, EvidenceMeta


def sample_evidence() -> Evidence:
    return Evidence(
        body=EvidenceBody(
            task_id="B02",
            commit_sha="a" * 40,
            changed_files=["z.py", "a.py"],
            commands=[],
            ci_tests={"tests/test_check.py::test_expected": "passed"},
            passed=True,
        ),
        meta=EvidenceMeta(generated_at="2026-09-04T12:00:00+02:00", adc_version="0.1.0"),
    )


def test_evidence_is_byte_identical(tmp_path: Path) -> None:
    evidence = sample_evidence()
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    write_evidence(first, evidence)
    write_evidence(second, evidence)

    assert first.read_bytes() == second.read_bytes() == evidence_bytes(evidence)


def test_evidence_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    evidence = sample_evidence()

    write_evidence(path, evidence)

    assert read_evidence(path) == evidence
