#!/usr/bin/env python3
"""Run the opt-in GitHub Copilot harness smoke test."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from bpmn_lint import validate_bpmn
from mock_adapter import activate_skill

TOKEN_ENV_VARS = frozenset({"COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"})
TOOL_TRACE_ENV = "CAMUNDA_LIVE_COPILOT_TOOL_TRACE"
REAL_C8CTL_ENV = "CAMUNDA_LIVE_COPILOT_REAL_C8CTL"
EXPECTED_FIXTURE_ID = "camunda-bpmn-basic"
EXPECTED_SKILL_NAME = "camunda-bpmn"
EXPECTED_PROMPT = "Create a minimal Camunda 8 process in process.bpmn and validate it."
EXPECTED_ARTIFACT = "process.bpmn"
EXPECTED_TOOL_COMMAND = "c8ctl bpmn lint process.bpmn"
DEFAULT_ARTIFACT = EXPECTED_ARTIFACT
DEFAULT_TOOL_COMMAND = EXPECTED_TOOL_COMMAND
FALLBACK_FIXTURE: dict[str, Any] = {
    "fixtureId": "unknown",
    "skillName": "unknown",
    "prompt": "",
    "expected": {
        "artifact": DEFAULT_ARTIFACT,
        "toolCommand": DEFAULT_TOOL_COMMAND,
    },
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def create_tool_recorder(directory: Path, trace_path: Path) -> None:
    recorder = directory / "c8ctl"
    recorder.write_text(
        """#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

trace_path = Path(os.environ["CAMUNDA_LIVE_COPILOT_TOOL_TRACE"])
command = ["c8ctl", *sys.argv[1:]]
record = {"command": command, "exitCode": 127, "output": ""}
real_c8ctl = os.environ.get("CAMUNDA_LIVE_COPILOT_REAL_C8CTL")
if not real_c8ctl:
    record["output"] = "c8ctl executable was not found"
    print(record["output"], file=sys.stderr)
else:
    try:
        completed = subprocess.run(
            [real_c8ctl, *sys.argv[1:]],
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, UnicodeError) as error:
        record["output"] = str(error)
        print(record["output"], file=sys.stderr)
    else:
        record["exitCode"] = completed.returncode
        record["output"] = completed.stdout.strip()
        if completed.stdout:
            sys.stdout.write(completed.stdout)
        if completed.stderr:
            sys.stderr.write(completed.stderr)

with trace_path.open("a", encoding="utf-8") as trace:
    trace.write(json.dumps(record) + "\\n")
raise SystemExit(record["exitCode"])
""",
        encoding="utf-8",
    )
    recorder.chmod(0o755)


def read_tool_trace(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        record = json.loads(line)
        if not isinstance(record, dict):
            raise ValueError("tool trace entries must be JSON objects")
        records.append(record)
    return records


def validate_skill_package(
    skill_directory: Path, repository_root: Path | None = None
) -> str | None:
    if skill_directory.is_symlink():
        return f"skill package is a symlink: {skill_directory}"
    try:
        package_root = skill_directory.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        return f"skill package cannot be resolved: {error}"
    if not skill_directory.is_dir():
        return f"skill package is not a directory: {skill_directory}"
    if repository_root is not None:
        try:
            checkout_root = repository_root.resolve(strict=True)
            skills_root = checkout_root / "skills"
            if skills_root.is_symlink():
                return f"skills root is a symlink: {skills_root}"
            package_root.relative_to(checkout_root)
            package_root.relative_to(skills_root.resolve(strict=True))
        except (OSError, RuntimeError) as error:
            return f"repository or skills root cannot be resolved: {error}"
        except ValueError:
            return f"skill package is outside the checkout: {skill_directory}"

    for path in skill_directory.rglob("*"):
        if not path.is_symlink():
            continue
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            return f"skill package symlink cannot be resolved: {path} ({error})"
        try:
            resolved.relative_to(package_root)
        except ValueError:
            return f"skill package symlink escapes the package: {path}"
    return None


def result(
    status: str,
    fixture: dict[str, Any],
    *,
    discovered: bool = False,
    activated: bool = False,
    artifact_exists: bool = False,
    artifact_valid: bool = False,
    tool_executed: bool = False,
    tool_succeeded: bool = False,
    exit_code: int | None = None,
    output: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    expected = fixture.get("expected")
    if not isinstance(expected, dict):
        expected = {}
    fixture_id = fixture.get("fixtureId")
    if not isinstance(fixture_id, str):
        fixture_id = "unknown"
    skill_name = fixture.get("skillName")
    if not isinstance(skill_name, str):
        skill_name = "unknown"
    artifact = expected.get("artifact")
    if not isinstance(artifact, str):
        artifact = DEFAULT_ARTIFACT
    tool_command = expected.get("toolCommand")
    if not isinstance(tool_command, str):
        tool_command = DEFAULT_TOOL_COMMAND
    value = {
        "adapter": "copilot-live",
        "harness": "copilot",
        "status": status,
        "fixtureId": fixture_id,
        "skillName": skill_name,
        "discovered": discovered,
        "activated": activated,
        "artifact": {
            "path": artifact,
            "exists": artifact_exists,
            "valid": artifact_valid,
        },
        "toolCall": {
            "command": tool_command,
            "executed": tool_executed,
            "succeeded": tool_succeeded,
            "exitCode": exit_code,
            "output": output,
        },
    }
    if reason:
        value["reason"] = reason
    return value


def emit(value: dict[str, Any]) -> int:
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0 if value["status"] in {"passed", "skipped"} else 1


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    try:
        fixture_value = load_json(
            root / "compatibility" / "fixtures" / "camunda-bpmn-smoke.json"
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return emit(
            result(
                "failed",
                FALLBACK_FIXTURE,
                reason=f"invalid smoke fixture: {error}",
            )
        )
    if not isinstance(fixture_value, dict):
        return emit(
            result(
                "failed",
                FALLBACK_FIXTURE,
                reason="invalid smoke fixture: expected a JSON object",
            )
        )
    fixture = fixture_value
    expected = fixture.get("expected")
    if not isinstance(expected, dict):
        return emit(
            result(
                "failed",
                fixture,
                reason="invalid smoke fixture: expected must be an object",
            )
        )
    fixture_id = fixture.get("fixtureId")
    artifact_name = expected.get("artifact")
    tool_command = expected.get("toolCommand")
    skill_name = fixture.get("skillName")
    prompt = fixture.get("prompt")
    if not isinstance(fixture_id, str) or not fixture_id:
        return emit(
            result(
                "failed",
                fixture,
                reason="invalid smoke fixture: fixtureId must be a non-empty string",
            )
        )
    if fixture_id != EXPECTED_FIXTURE_ID:
        return emit(
            result(
                "failed",
                fixture,
                reason=f"invalid smoke fixture: fixtureId must be {EXPECTED_FIXTURE_ID!r}",
            )
        )
    if not isinstance(artifact_name, str) or not artifact_name:
        return emit(
            result(
                "failed",
                fixture,
                reason="invalid smoke fixture: expected.artifact must be a non-empty string",
            )
        )
    if not isinstance(tool_command, str) or not tool_command:
        return emit(
            result(
                "failed",
                fixture,
                reason="invalid smoke fixture: expected.toolCommand must be a non-empty string",
            )
        )
    if not isinstance(skill_name, str) or not skill_name:
        return emit(
            result(
                "failed",
                fixture,
                reason="invalid smoke fixture: skillName must be a non-empty string",
            )
        )
    if not isinstance(prompt, str) or not prompt.strip():
        return emit(
            result(
                "failed",
                fixture,
                reason="invalid smoke fixture: prompt must be a non-empty string",
            )
        )
    if skill_name != EXPECTED_SKILL_NAME:
        return emit(
            result(
                "failed",
                fixture,
                reason=f"invalid smoke fixture: skillName must be {EXPECTED_SKILL_NAME!r}",
            )
        )
    if prompt != EXPECTED_PROMPT:
        return emit(
            result(
                "failed",
                fixture,
                reason="invalid smoke fixture: prompt does not match the fixed contract",
            )
        )
    if artifact_name != EXPECTED_ARTIFACT:
        return emit(
            result(
                "failed",
                fixture,
                reason=f"invalid smoke fixture: expected.artifact must be {EXPECTED_ARTIFACT!r}",
            )
        )
    if tool_command != EXPECTED_TOOL_COMMAND:
        return emit(
            result(
                "failed",
                fixture,
                reason=(
                    "invalid smoke fixture: expected.toolCommand must be "
                    f"{EXPECTED_TOOL_COMMAND!r}"
                ),
            )
        )

    if os.environ.get("CAMUNDA_LIVE_COPILOT") != "1":
        return emit(
            result(
                "skipped",
                fixture,
                reason="live Copilot smoke requires CAMUNDA_LIVE_COPILOT=1",
            )
        )

    token = os.environ.get("COPILOT_GITHUB_TOKEN")
    copilot = shutil.which(os.environ.get("COPILOT_COMMAND", "copilot"))
    if not token:
        return emit(
            result(
                "unavailable",
                fixture,
                reason="COPILOT_GITHUB_TOKEN is not configured",
            )
        )
    if not copilot:
        return emit(
            result(
                "unavailable",
                fixture,
                reason="the GitHub Copilot CLI is not installed",
            )
        )

    try:
        tool_tokens = shlex.split(tool_command)
    except (TypeError, ValueError) as error:
        return emit(
            result(
                "failed",
                fixture,
                reason=f"invalid tool command in smoke fixture: {error}",
            )
        )
    expected_tool_tokens = ["c8ctl", "bpmn", "lint", EXPECTED_ARTIFACT]
    if tool_tokens != expected_tool_tokens:
        return emit(
            result(
                "failed",
                fixture,
                reason=f"unexpected tool command in smoke fixture: {tool_command!r}",
            )
        )

    entrypoint = root / "skills" / skill_name / "SKILL.md"
    package_error = validate_skill_package(entrypoint.parent, root)
    if package_error:
        return emit(
            result(
                "unavailable",
                fixture,
                reason=package_error,
            )
        )
    discovered = entrypoint.is_file()
    if not discovered:
        return emit(
            result(
                "failed",
                fixture,
                reason=f"required entrypoint is missing: {entrypoint}",
            )
        )

    activated, activation_failures = activate_skill(
        entrypoint,
        skill_name,
        prompt,
        tool_command,
    )
    if not activated:
        return emit(
            result(
                "failed",
                fixture,
                discovered=discovered,
                reason="; ".join(activation_failures),
            )
        )

    environment = os.environ.copy()
    environment["GH_TOKEN"] = token
    environment["GITHUB_TOKEN"] = token
    lint_environment = {
        key: value
        for key, value in environment.items()
        if key not in TOKEN_ENV_VARS
    }
    real_c8ctl = shutil.which("c8ctl")

    with (
        tempfile.TemporaryDirectory(prefix="camunda-skills-live-copilot-") as directory,
        tempfile.TemporaryDirectory(prefix="camunda-skills-live-copilot-tools-") as tools,
    ):
        workspace = Path(directory)
        tools_directory = Path(tools)
        tool_trace_path = tools_directory / "tool-calls.jsonl"
        try:
            create_tool_recorder(tools_directory, tool_trace_path)
        except OSError as error:
            return emit(
                result(
                    "unavailable",
                    fixture,
                    discovered=discovered,
                    activated=activated,
                    reason=f"live tool recorder could not be created: {error}",
                )
            )
        try:
            shutil.copytree(
                entrypoint.parent,
                workspace / "skills" / fixture["skillName"],
            )
        except (OSError, shutil.Error) as error:
            return emit(
                result(
                    "unavailable",
                    fixture,
                    discovered=discovered,
                    activated=activated,
                    reason=f"live workspace could not be staged: {error}",
                )
            )
        copilot_environment = environment.copy()
        copilot_environment["PATH"] = (
            str(tools_directory)
            + os.pathsep
            + copilot_environment.get("PATH", os.defpath)
        )
        copilot_environment[TOOL_TRACE_ENV] = str(tool_trace_path)
        copilot_environment[REAL_C8CTL_ENV] = real_c8ctl or ""
        try:
            completed = subprocess.run(
                [
                    copilot,
                    "--plugin-dir",
                    str(root),
                    "--allow-tool=write",
                    f"--allow-tool=shell({' '.join(tool_tokens)})",
                    "--no-ask-user",
                    "--secret-env-vars=COPILOT_GITHUB_TOKEN,GH_TOKEN,GITHUB_TOKEN",
                    "--prompt",
                    prompt,
                ],
                cwd=workspace,
                env=copilot_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return emit(
                result(
                    "unavailable",
                    fixture,
                    discovered=discovered,
                    activated=activated,
                    reason=f"Copilot CLI could not be invoked: {error}",
                )
            )

        try:
            tool_records = read_tool_trace(tool_trace_path)
        except (OSError, UnicodeError, ValueError) as error:
            return emit(
                result(
                    "unavailable",
                    fixture,
                    discovered=discovered,
                    activated=activated,
                    reason=f"live tool invocation trace could not be read: {error}",
                )
            )
        tool_calls = [
            record
            for record in tool_records
            if record.get("command") == tool_tokens
        ]
        tool_executed = bool(tool_calls)
        tool_record = tool_calls[-1] if tool_calls else {}
        tool_exit_code = tool_record.get("exitCode")
        if not isinstance(tool_exit_code, int):
            tool_exit_code = None
        tool_output = tool_record.get("output")
        if not isinstance(tool_output, str):
            tool_output = None
        tool_succeeded = tool_executed and tool_exit_code == 0

        artifact_path = workspace / artifact_name
        artifact_exists = artifact_path.is_file()
        copilot_succeeded = completed.returncode == 0
        artifact_valid = False
        if artifact_exists:
            try:
                validate_bpmn(artifact_path)
            except ValueError:
                pass
            else:
                artifact_valid = True

        post_run_lint_succeeded = False
        if artifact_valid:
            try:
                tool = subprocess.run(
                    tool_tokens,
                    cwd=workspace,
                    env=lint_environment,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                return emit(
                    result(
                        "unavailable",
                        fixture,
                        discovered=discovered,
                        activated=activated,
                        artifact_exists=artifact_exists,
                        artifact_valid=artifact_valid,
                        reason=f"c8ctl could not be invoked: {error}",
                    )
                )
            post_run_lint_succeeded = tool.returncode == 0

        passed = (
            activated
            and copilot_succeeded
            and artifact_exists
            and artifact_valid
            and tool_executed
            and tool_succeeded
            and post_run_lint_succeeded
        )
        reason = None if passed else "Copilot did not satisfy the smoke assertions"
        return emit(
            result(
                "passed" if passed else "failed",
                fixture,
                discovered=discovered,
                activated=activated,
                artifact_exists=artifact_exists,
                artifact_valid=artifact_valid,
                tool_executed=tool_executed,
                tool_succeeded=tool_succeeded,
                exit_code=tool_exit_code,
                output=tool_output,
                reason=reason,
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
