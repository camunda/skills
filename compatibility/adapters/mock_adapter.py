#!/usr/bin/env python3
"""Run one credential-free deterministic harness smoke adapter."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from bpmn_lint import validate_bpmn


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", choices=("claude", "copilot"), required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    contract = load_json(root / "compatibility" / "harness-smoke-contract.json")
    fixture = load_json(root / "compatibility" / "fixtures" / "camunda-bpmn-smoke.json")
    assertions = contract["resultAssertions"]
    expected = fixture["expected"]
    failures: list[str] = []

    required_entrypoint = root / contract["discovery"]["requiredEntrypoint"]
    discovered = required_entrypoint.is_file()
    activated = discovered and fixture["skillName"] == "camunda-bpmn" and bool(fixture["prompt"])
    if not discovered:
        failures.append(f"missing skill entrypoint: {required_entrypoint}")
    if not activated:
        failures.append("fixture did not activate camunda-bpmn")

    artifact_name = assertions["artifact"]["path"]
    command = assertions["toolCall"]["command"]
    command_tokens = shlex.split(command)
    expected_tokens = ["c8ctl", "bpmn", "lint", artifact_name]
    if command_tokens != expected_tokens:
        failures.append(f"unexpected tool command: {command!r}")

    artifact_exists = False
    artifact_valid = False
    tool_executed = False
    tool_succeeded = False
    exit_code: int | None = None
    tool_error: str | None = None

    with tempfile.TemporaryDirectory(prefix="camunda-skills-smoke-") as directory:
        artifact_path = Path(directory) / artifact_name
        source_path = root / expected["artifactSource"]
        if not source_path.is_file():
            failures.append(f"missing smoke artifact source: {source_path}")
        else:
            shutil.copyfile(source_path, artifact_path)

        artifact_exists = artifact_path.is_file()
        if not artifact_exists:
            failures.append(f"adapter did not emit {artifact_name}")
        else:
            try:
                validate_bpmn(artifact_path)
            except ValueError as error:
                failures.append(f"invalid emitted artifact: {error}")
            else:
                artifact_valid = True

        if command_tokens == expected_tokens and artifact_exists:
            environment = os.environ.copy()
            adapter_directory = str(Path(__file__).resolve().parent)
            environment["PATH"] = adapter_directory + os.pathsep + environment.get("PATH", "")
            try:
                completed = subprocess.run(
                    command_tokens,
                    cwd=directory,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                tool_error = str(error)
            else:
                tool_executed = True
                exit_code = completed.returncode
                tool_succeeded = completed.returncode == 0
                if not tool_succeeded:
                    failures.append(
                        f"{command} failed with exit code {completed.returncode}: "
                        f"{completed.stderr.strip()}"
                    )
        else:
            tool_error = "tool command was not run because its prerequisites failed"

    result = {
        "adapter": args.harness,
        "fixtureId": fixture["fixtureId"],
        "discovered": discovered,
        "activated": activated,
        "artifact": {
            "path": artifact_name,
            "exists": artifact_exists,
            "valid": artifact_valid,
        },
        "toolCall": {
            "command": command,
            "executed": tool_executed,
            "succeeded": tool_succeeded,
            "exitCode": exit_code,
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))

    if expected["artifactExists"] and not artifact_exists:
        failures.append("fixture requires the artifact to exist")
    if expected["artifactValid"] and not artifact_valid:
        failures.append("fixture requires a valid BPMN artifact")
    if expected["toolExecuted"] and not tool_executed:
        failures.append(f"tool command was not executed: {tool_error or 'unknown error'}")
    if expected["toolSucceeded"] and not tool_succeeded:
        failures.append("tool command did not succeed")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
