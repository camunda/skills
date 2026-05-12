"""Layer-2 verifier: lint the agent's BPMN output via `c8 bpmn lint`.

Reads the agent's emitted BPMN from ``outputs/process.bpmn`` (or whatever
``answer_file`` overrides to) and shells out to::

    c8 bpmn lint <file> --quiet

Both quiet and non-quiet modes exit non-zero on parse failures or lint
violations; ``--quiet`` is used to suppress the ``✓ No issues found.``
success line so the verifier output is clean when there's nothing to
report.

Verifier entry shape (in evals.json)::

    {
      "type": "bpmn-lint",
      "answer_file": "process.bpmn"     # optional, default "process.bpmn"
    }

There's no ``expected`` field — passing means the BPMN parses and lints
clean against the c8ctl-bundled `bpmnlint` ruleset. The check IS the rule.

Skip semantics mirror ``feel-evaluate``::

  - ``c8`` not on PATH                         -> skipped:no-cli
  - agent didn't produce an output file        -> skipped:no-output-file

There is no cluster dependency (lint runs entirely client-side), so no
``no-cluster`` skip path.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import Result

VERIFIER_TYPE = "bpmn-lint"


def _read_answer_path(outputs_dir: Path, name: str) -> Path | None:
    p = outputs_dir / name
    return p if p.is_file() and p.stat().st_size > 0 else None


def run(
    verifier: dict[str, Any],
    case: dict[str, Any],
    outputs_dir: Path,
    repo_root: Path,
) -> Result:
    if shutil.which("c8") is None:
        return Result(
            type=VERIFIER_TYPE, passed=False, skipped=True,
            skip_reason="no-cli",
            message="c8 CLI not on PATH; install @camunda8/cli to run this verifier",
        )

    answer_file_name = verifier.get("answer_file", "process.bpmn")
    answer_path = _read_answer_path(outputs_dir, answer_file_name)
    if answer_path is None:
        return Result(
            type=VERIFIER_TYPE, passed=False,
            skipped=True, skip_reason="no-output-file",
            message=f"agent did not produce {answer_file_name} under {outputs_dir}",
        )

    cmd = ["c8", "bpmn", "lint", str(answer_path), "--quiet"]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return Result(
            type=VERIFIER_TYPE, passed=False,
            message="c8 bpmn lint timed out (60s)",
            details={"answer_file": str(answer_path.relative_to(outputs_dir.parent.parent.parent.parent))
                     if outputs_dir.is_absolute() else str(answer_path)},
        )

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    if proc.returncode == 0:
        return Result(
            type=VERIFIER_TYPE,
            passed=True,
            message="bpmn lint clean",
            details={"answer_file": answer_file_name},
        )

    # Exit 1: parse failure or lint violations. Report a one-line summary
    # in `message` and the full report in `details.report` for the viewer.
    summary = _summarize_failure(stdout, stderr)
    return Result(
        type=VERIFIER_TYPE,
        passed=False,
        message=summary,
        details={
            "answer_file": answer_file_name,
            "report": (stdout or stderr)[:4000],
            "exit_code": proc.returncode,
        },
    )


def _summarize_failure(stdout: str, stderr: str) -> str:
    """One-line summary of what failed, drawn from the trailing report line."""
    text = stdout or stderr
    if not text:
        return "c8 bpmn lint failed with no output"
    # Parse-error path: stderr starts with "✗ Failed to bpmn lint: ..."
    if "Failed to bpmn lint" in text or "failed to parse" in text:
        return text.splitlines()[0][:300].lstrip("✗ ").strip()
    # Lint-violation path: trailing `✖ N problems (N errors, M warnings)`.
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("✖"):
            return line.lstrip("✖ ").strip()[:300]
    return text.splitlines()[-1][:300]
