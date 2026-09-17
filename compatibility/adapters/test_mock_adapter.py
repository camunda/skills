from pathlib import Path

from mock_adapter import activate_skill


def test_activate_skill_reports_invalid_utf8_entrypoint(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_bytes(b"\xff")

    activated, failures = activate_skill(
        path,
        "fixture-skill",
        "Create process.bpmn",
        "c8ctl bpmn lint process.bpmn",
    )

    assert not activated
    assert len(failures) == 1
    assert "cannot read skill entrypoint" in failures[0]
