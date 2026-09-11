#!/usr/bin/env python3
"""Run one credential-free deterministic harness smoke adapter."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from bpmn_lint import validate_bpmn

SKILL_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---(?:\s|$)", re.DOTALL)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def activate_skill(
    entrypoint: Path,
    skill_name: Any,
    prompt: Any,
    tool_command: Any,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if not entrypoint.is_file():
        return False, [f"missing skill entrypoint: {entrypoint}"]

    try:
        content = entrypoint.read_text(encoding="utf-8")
    except OSError as error:
        return False, [f"cannot read skill entrypoint: {error}"]

    frontmatter = SKILL_FRONTMATTER.match(content)
    if not frontmatter:
        failures.append(f"skill entrypoint has no YAML frontmatter: {entrypoint}")
    else:
        try:
            metadata = yaml.safe_load(frontmatter.group(1))
        except yaml.YAMLError as error:
            failures.append(f"skill entrypoint has invalid YAML frontmatter: {error}")
        else:
            if not isinstance(metadata, dict):
                failures.append("skill entrypoint frontmatter must be a YAML object")
            else:
                if metadata.get("name") != skill_name:
                    failures.append("skill entrypoint name does not match the fixture")
                description = metadata.get("description")
                if not isinstance(description, str) or not description.strip():
                    failures.append("skill entrypoint description must be non-empty")

    if not isinstance(prompt, str) or not prompt.strip():
        failures.append("activation prompt must be non-empty")
    if not isinstance(tool_command, str) or tool_command not in content:
        failures.append("skill entrypoint does not declare the required BPMN lint command")
    return not failures, failures


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

    artifact_name = assertions["artifact"]["path"]
    command = assertions["toolCall"]["command"]
    command_tokens = shlex.split(command)

    required_entrypoint = root / contract["discovery"]["requiredEntrypoint"]
    discovered = required_entrypoint.is_file()
    activated, activation_failures = activate_skill(
        required_entrypoint,
        fixture["skillName"],
        fixture["prompt"],
        command,
    )
    failures.extend(activation_failures)
    if not activated:
        failures.append("fixture did not activate camunda-bpmn")

    expected_tokens = ["c8ctl", "bpmn", "lint", artifact_name]
    if command_tokens != expected_tokens:
        failures.append(f"unexpected tool command: {command!r}")

    artifact_exists = False
    artifact_valid = False
    tool_executed = False
    tool_succeeded = False
    exit_code: int | None = None
    tool_error: str | None = None
    tool_output: str | None = None

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
                tool_output = completed.stdout.strip()
                tool_succeeded = (
                    completed.returncode == 0
                    and tool_output == f"{command}: passed"
                )
                if completed.returncode != 0:
                    failures.append(
                        f"{command} failed with exit code {completed.returncode}: "
                        f"{completed.stderr.strip()}"
                    )
                elif not tool_succeeded:
                    failures.append(
                        f"{command} did not report the expected success output: "
                        f"{tool_output!r}"
                    )
        else:
            tool_error = "tool command was not run because its prerequisites failed"

    if expected["artifactExists"] and not artifact_exists:
        failures.append("fixture requires the artifact to exist")
    if expected["artifactValid"] and not artifact_valid:
        failures.append("fixture requires a valid BPMN artifact")
    if expected["toolExecuted"] and not tool_executed:
        failures.append(f"tool command was not executed: {tool_error or 'unknown error'}")
    if expected["toolSucceeded"] and not tool_succeeded:
        failures.append("tool command did not succeed")

    result = {
        "adapter": args.harness,
        "harness": args.harness,
        "status": "passed" if not failures else "failed",
        "fixtureId": fixture["fixtureId"],
        "skillName": fixture["skillName"],
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
            "output": tool_output,
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
