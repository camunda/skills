import json
import subprocess
from pathlib import Path

import pytest

import live_copilot


def read_result(output: str) -> dict[str, object]:
    return json.loads(output)


def test_skips_without_live_opt_in(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CAMUNDA_LIVE_COPILOT", raising=False)

    assert live_copilot.main() == 0

    result = read_result(capsys.readouterr().out)
    assert result["status"] == "skipped"


def test_reports_missing_token_as_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CAMUNDA_LIVE_COPILOT", "1")
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)

    assert live_copilot.main() == 1

    result = read_result(capsys.readouterr().out)
    assert result["status"] == "unavailable"


@pytest.mark.parametrize(
    "error",
    (
        OSError("copilot unavailable"),
        subprocess.TimeoutExpired("copilot", 180),
    ),
)
def test_reports_copilot_invocation_failure_after_activation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
) -> None:
    monkeypatch.setenv("CAMUNDA_LIVE_COPILOT", "1")
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "token")
    monkeypatch.setattr(live_copilot.shutil, "which", lambda _: "copilot")
    monkeypatch.setattr(live_copilot, "activate_skill", lambda *args: (True, []))

    def run(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(live_copilot.subprocess, "run", run)

    assert live_copilot.main() == 1

    result = read_result(capsys.readouterr().out)
    assert result["status"] == "unavailable"
    assert result["activated"] is True


def test_reports_workspace_staging_failure_after_activation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CAMUNDA_LIVE_COPILOT", "1")
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "token")
    monkeypatch.setattr(live_copilot.shutil, "which", lambda _: "copilot")
    monkeypatch.setattr(live_copilot, "activate_skill", lambda *args: (True, []))

    def copytree(*_args: object, **_kwargs: object) -> None:
        raise OSError("temporary directory is unavailable")

    monkeypatch.setattr(live_copilot.shutil, "copytree", copytree)

    assert live_copilot.main() == 1

    result = read_result(capsys.readouterr().out)
    assert result["status"] == "unavailable"
    assert result["activated"] is True


def test_rejects_symlink_escaping_skill_package(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (package / "SKILL.md").symlink_to(outside)

    error = live_copilot.validate_skill_package(package)

    assert error is not None
    assert "escapes the package" in error


@pytest.mark.parametrize(
    ("copilot_exit_code", "write_artifact", "tool_exit_code", "expected_status"),
    (
        (0, True, 0, "passed"),
        (1, True, 0, "failed"),
        (0, False, 0, "failed"),
        (0, True, 1, "failed"),
    ),
)
def test_maps_live_process_and_tool_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    copilot_exit_code: int,
    write_artifact: bool,
    tool_exit_code: int,
    expected_status: str,
) -> None:
    monkeypatch.setenv("CAMUNDA_LIVE_COPILOT", "1")
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "token")
    monkeypatch.setattr(live_copilot.shutil, "which", lambda _: "copilot")
    monkeypatch.setattr(live_copilot, "activate_skill", lambda *args: (True, []))

    def run(
        command: list[str],
        *,
        cwd: str | Path,
        env: dict[str, str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "copilot":
            assert env["COPILOT_GITHUB_TOKEN"] == "token"
            if write_artifact:
                source = (
                    Path(live_copilot.__file__).resolve().parents[2]
                    / "compatibility"
                    / "fixtures"
                    / "process.bpmn"
                )
                (Path(cwd) / "process.bpmn").write_text(
                    source.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            return subprocess.CompletedProcess(command, copilot_exit_code, "", "")
        assert command == ["c8ctl", "bpmn", "lint", "process.bpmn"]
        assert all(
            variable not in env
            for variable in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
        )
        return subprocess.CompletedProcess(command, tool_exit_code, "lint output", "")

    monkeypatch.setattr(live_copilot.subprocess, "run", run)

    assert live_copilot.main() == (0 if expected_status == "passed" else 1)

    result = read_result(capsys.readouterr().out)
    assert result["status"] == expected_status
    assert result["activated"] is True
    artifact = result["artifact"]
    assert isinstance(artifact, dict)
    assert artifact["exists"] is write_artifact
    tool_call = result["toolCall"]
    assert isinstance(tool_call, dict)
    assert tool_call["succeeded"] is (write_artifact and tool_exit_code == 0)
    assert tool_call["exitCode"] == (tool_exit_code if write_artifact else None)
