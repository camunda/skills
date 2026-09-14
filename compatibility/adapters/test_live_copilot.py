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


def test_reports_malformed_fixture_as_structured_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CAMUNDA_LIVE_COPILOT", "1")
    monkeypatch.setattr(
        live_copilot,
        "load_json",
        lambda *_args: {"fixtureId": "broken"},
    )

    assert live_copilot.main() == 1

    result = read_result(capsys.readouterr().out)
    assert result["status"] == "failed"
    assert "expected must be an object" in result["reason"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("fixtureId", "other-fixture", "fixtureId must be"),
        ("skillName", "other-skill", "skillName must be"),
        ("prompt", "run another prompt", "prompt does not match"),
        ("artifact", "other.bpmn", "expected.artifact must be"),
        ("toolCommand", "c8ctl bpmn lint other.bpmn", "expected.toolCommand must be"),
    ),
)
def test_rejects_fixture_values_outside_live_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    field: str,
    value: str,
    message: str,
) -> None:
    fixture: dict[str, object] = {
        "fixtureId": "camunda-bpmn-basic",
        "skillName": "camunda-bpmn",
        "prompt": "Create a minimal Camunda 8 process in process.bpmn and validate it.",
        "expected": {
            "artifact": "process.bpmn",
            "toolCommand": "c8ctl bpmn lint process.bpmn",
        },
    }
    if field in {"artifact", "toolCommand"}:
        expected = fixture["expected"]
        assert isinstance(expected, dict)
        expected[field] = value
    else:
        fixture[field] = value

    monkeypatch.setenv("CAMUNDA_LIVE_COPILOT", "1")
    monkeypatch.setattr(live_copilot, "load_json", lambda *_args: fixture)

    assert live_copilot.main() == 1

    result = read_result(capsys.readouterr().out)
    assert result["status"] == "failed"
    assert message in result["reason"]


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


def test_rejects_skill_package_outside_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    (repository / "skills").mkdir(parents=True)
    package = tmp_path / "outside"
    package.mkdir()

    error = live_copilot.validate_skill_package(package, repository)

    assert error is not None
    assert "outside the checkout" in error


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
            assert "--allow-tool=shell(c8ctl bpmn lint process.bpmn)" in command
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
                trace_path = env.get(live_copilot.TOOL_TRACE_ENV)
                assert trace_path is not None
                Path(trace_path).write_text(
                    json.dumps(
                        {
                            "command": [
                                "c8ctl",
                                "bpmn",
                                "lint",
                                "process.bpmn",
                            ],
                            "exitCode": tool_exit_code,
                            "output": "lint output",
                        }
                    )
                    + "\n",
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


def test_does_not_count_post_run_lint_as_copilot_tool_execution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CAMUNDA_LIVE_COPILOT", "1")
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "token")
    monkeypatch.setattr(live_copilot.shutil, "which", lambda _: "copilot")
    monkeypatch.setattr(live_copilot, "activate_skill", lambda *args: (True, []))

    def run(
        command: list[str],
        *,
        cwd: str | Path,
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "copilot":
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
            return subprocess.CompletedProcess(command, 0, "", "")
        assert command == ["c8ctl", "bpmn", "lint", "process.bpmn"]
        return subprocess.CompletedProcess(command, 0, "lint output", "")

    monkeypatch.setattr(live_copilot.subprocess, "run", run)

    assert live_copilot.main() == 1

    result = read_result(capsys.readouterr().out)
    assert result["status"] == "failed"
    tool_call = result["toolCall"]
    assert isinstance(tool_call, dict)
    assert tool_call["executed"] is False
    assert tool_call["succeeded"] is False
