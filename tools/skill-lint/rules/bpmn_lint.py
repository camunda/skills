"""Run `c8 bpmn lint` on every .bpmn file under examples/ and skills/<skill>/.

Skipped (warn) when `c8` is not on PATH so this rule is non-blocking when the
c8ctl CLI isn't installed locally. CI installs c8ctl so it always runs there.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import Finding


def _bpmn_files(skill_dir: Path, repo_root: Path) -> list[Path]:
    files = list(skill_dir.rglob("*.bpmn"))
    # Lint shared examples once, attributed to the BPMN skill.
    if skill_dir.name == "camunda-bpmn":
        files.extend((repo_root / "examples").rglob("*.bpmn"))
    return sorted(set(files))


def check(skill_dir: Path, repo_root: Path) -> list[Finding]:
    files = _bpmn_files(skill_dir, repo_root)
    if not files:
        return []
    if shutil.which("c8") is None:
        return [
            Finding(
                rule="bpmn_lint",
                skill=skill_dir.name,
                severity="skip",
                message="c8 CLI not on PATH; skipping BPMN lint",
                location=None,
            )
        ]
    findings: list[Finding] = []
    for bpmn in files:
        try:
            result = subprocess.run(
                ["c8", "bpmn", "lint", str(bpmn)],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            findings.append(
                Finding(
                    rule="bpmn_lint",
                    skill=skill_dir.name,
                    severity="error",
                    message="c8 bpmn lint timed out",
                    location=str(bpmn.relative_to(repo_root)),
                )
            )
            continue
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip().splitlines()
            summary = stderr[-1] if stderr else f"exit {result.returncode}"
            findings.append(
                Finding(
                    rule="bpmn_lint",
                    skill=skill_dir.name,
                    severity="error",
                    message=summary,
                    location=str(bpmn.relative_to(repo_root)),
                )
            )
    return findings
