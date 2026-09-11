#!/usr/bin/env python3
"""Run the opt-in GitHub Copilot harness smoke test."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from bpmn_lint import validate_bpmn
from mock_adapter import activate_skill


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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
    value = {
        "adapter": "copilot-live",
        "harness": "copilot",
        "status": status,
        "fixtureId": fixture["fixtureId"],
        "skillName": fixture["skillName"],
        "discovered": discovered,
        "activated": activated,
        "artifact": {
            "path": fixture["expected"]["artifact"],
            "exists": artifact_exists,
            "valid": artifact_valid,
        },
        "toolCall": {
            "command": fixture["expected"]["toolCommand"],
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
    fixture = load_json(root / "compatibility" / "fixtures" / "camunda-bpmn-smoke.json")
    expected = fixture["expected"]

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

    entrypoint = root / "skills" / fixture["skillName"] / "SKILL.md"
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
        fixture["skillName"],
        fixture["prompt"],
        expected["toolCommand"],
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

    prompt = fixture["prompt"]
    environment = os.environ.copy()
    environment["GH_TOKEN"] = token
    environment["GITHUB_TOKEN"] = token

    with tempfile.TemporaryDirectory(prefix="camunda-skills-live-copilot-") as directory:
        workspace = Path(directory)
        shutil.copytree(
            entrypoint.parent,
            workspace / "skills" / fixture["skillName"],
        )
        try:
            completed = subprocess.run(
                [copilot, "--plugin-dir", str(root), "--prompt", prompt],
                cwd=workspace,
                env=environment,
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
                    reason=f"Copilot CLI could not be invoked: {error}",
                )
            )

        artifact_path = workspace / expected["artifact"]
        artifact_exists = artifact_path.is_file()
        activated = completed.returncode == 0
        artifact_valid = False
        if artifact_exists:
            try:
                validate_bpmn(artifact_path)
            except ValueError:
                pass
            else:
                artifact_valid = True

        tool_executed = False
        tool_succeeded = False
        tool_exit_code: int | None = None
        tool_output: str | None = None
        if artifact_valid:
            try:
                tool = subprocess.run(
                    ["c8ctl", "bpmn", "lint", expected["artifact"]],
                    cwd=workspace,
                    env=environment,
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
            tool_executed = True
            tool_exit_code = tool.returncode
            tool_output = tool.stdout.strip()
            tool_succeeded = tool.returncode == 0

        passed = (
            activated
            and artifact_exists
            and artifact_valid
            and tool_executed
            and tool_succeeded
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
