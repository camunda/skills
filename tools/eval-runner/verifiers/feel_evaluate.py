"""Layer-2/3 verifier: evaluate FEEL output against the cluster engine.

Reads the agent's emitted FEEL expression from ``outputs/answer.feel`` and
shells out to ``c8 feel evaluate '<expr>' --vars '<json>'``. Compares the
result to the expected value from the verifier entry. Layer 2 (parse
correctness) is implicit in the exit code; Layer 3 (behavioral correctness)
is the value comparison.

Verifier entry shape (in evals.json):

    {
      "type": "feel-evaluate",
      "context": {"orderAmount": 1500},
      "expected": 1275,
      "answer_file": "answer.feel"        # optional, default "answer.feel"
    }

Engine policy: cluster by default. We never silently fall back to
``--engine local``; if the cluster is unreachable, the verifier skips
with ``skip_reason="no-cluster"``. ``c8`` not on PATH skips with
``skip_reason="no-cli"``. Skipped verifiers do NOT fail the case.

**Dev/integration escape hatch**: setting the env var
``EVAL_FEEL_ENGINE=local`` switches to the JS-based ``feelin`` engine that
ships with c8ctl. For pure FEEL semantics on supported expressions the
local engine is interchangeable with the cluster engine: valid
expressions return the same result, parse errors fail with exit 1 in
both, and unknown-variable lookups warn-then-return-null with exit 0 in
both. Real differences: cluster-only features (``--tenant``, transport
failure modes), and warning payload shape (local includes ``type`` +
``position``; cluster has only ``message``). Use the local engine for
offline integration tests where no cluster is reachable; the eval
summary records ``engine: "local"`` so the report makes the mode
visible to reviewers. Baselines are still expected to run against the
cluster engine to catch tenant- and infrastructure-level regressions.

Comparison semantics: ``c8 feel evaluate`` writes the result to stdout. We
trim it and compare against ``expected``:

  - bool/None: stripped stdout matches ``str(expected).lower()`` ("true",
    "false", "null") OR equals the JSON form.
  - number: parse stdout as int or float; compare numerically (with a small
    epsilon for floats).
  - string: exact match against trimmed stdout.
  - list/dict: parse stdout as JSON; compare the parsed value.

Failures from any of the above stages produce ``passed=False`` with a
descriptive message and the raw c8 stdout/stderr in ``details`` for forensic
inspection in the report.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import Result

VERIFIER_TYPE = "feel-evaluate"
_ENGINE_ENV = "EVAL_FEEL_ENGINE"

# Heuristic substrings that signal a connectivity issue rather than a real
# evaluation failure. Conservative: when in doubt we treat the verifier as
# failed so reviewers see the noise rather than miss a real regression.
_CLUSTER_UNREACHABLE_HINTS = (
    "could not connect",
    "no cluster",
    "ECONNREFUSED",
    "ENOTFOUND",
    "Failed to fetch",
    "Unable to reach",
    "No active profile",
    "no profile",
    "not authenticated",
)

_FLOAT_EPSILON = 1e-6


def _read_answer(outputs_dir: Path, name: str) -> str | None:
    """Read the agent's FEEL output file. Returns None if missing/empty."""
    p = outputs_dir / name
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8").strip()
    return text or None


def _is_unreachable(stderr: str) -> bool:
    s = stderr.lower()
    return any(h.lower() in s for h in _CLUSTER_UNREACHABLE_HINTS)


def _compare(actual_stdout: str, expected: Any) -> tuple[bool, str]:
    """Compare c8's trimmed stdout to ``expected``. Returns (passed, message)."""
    actual = actual_stdout.strip()

    # bool / None
    if isinstance(expected, bool):
        target_str = "true" if expected else "false"
        if actual.lower() == target_str:
            return True, "boolean match"
        try:
            if json.loads(actual) == expected:
                return True, "boolean match (json)"
        except json.JSONDecodeError:
            pass
        return False, f"expected {target_str!r}, got {actual!r}"

    if expected is None:
        if actual.lower() in ("null", "none", ""):
            return True, "null match"
        return False, f"expected null, got {actual!r}"

    # numeric
    if isinstance(expected, (int, float)):
        try:
            actual_num = json.loads(actual)
        except json.JSONDecodeError:
            try:
                actual_num = float(actual)
            except ValueError:
                return False, f"expected numeric {expected}, got non-numeric {actual!r}"
        if isinstance(actual_num, bool):
            return False, f"expected numeric {expected}, got boolean {actual_num!r}"
        if isinstance(actual_num, (int, float)):
            if isinstance(expected, int) and isinstance(actual_num, float) and not actual_num.is_integer():
                return False, f"expected int {expected}, got float {actual_num}"
            if math.isclose(float(actual_num), float(expected), rel_tol=_FLOAT_EPSILON, abs_tol=_FLOAT_EPSILON):
                return True, "numeric match"
            return False, f"expected {expected}, got {actual_num}"
        return False, f"expected numeric {expected}, got {actual_num!r}"

    # list / dict — parse stdout as JSON, compare structurally
    if isinstance(expected, (list, dict)):
        try:
            actual_obj = json.loads(actual)
        except json.JSONDecodeError as e:
            return False, f"expected {type(expected).__name__}, stdout not JSON: {e}"
        if actual_obj == expected:
            return True, "structural match"
        return False, f"expected {expected!r}, got {actual_obj!r}"

    # string — exact match against trimmed stdout, or against quoted-string form
    if isinstance(expected, str):
        if actual == expected:
            return True, "string match"
        # FEEL strings are emitted quoted: "value"
        if actual == f'"{expected}"':
            return True, "string match (quoted)"
        try:
            parsed = json.loads(actual)
            if parsed == expected:
                return True, "string match (json)"
        except json.JSONDecodeError:
            pass
        return False, f"expected {expected!r}, got {actual!r}"

    return False, f"unsupported expected type: {type(expected).__name__}"


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

    answer_file_name = verifier.get("answer_file", "answer.feel")
    expression = _read_answer(outputs_dir, answer_file_name)
    if expression is None:
        return Result(
            type=VERIFIER_TYPE, passed=False,
            skipped=True, skip_reason="no-output-file",
            message=f"agent did not produce {answer_file_name} under {outputs_dir}",
        )

    context = verifier.get("context", {})
    expected = verifier.get("expected")

    cmd = ["c8", "feel", "evaluate", expression]
    if context:
        cmd += ["--vars", json.dumps(context)]
    # Engine policy: cluster by default. The EVAL_FEEL_ENGINE=local escape
    # hatch is a dev/integration affordance only — see module docstring.
    engine_override = os.environ.get(_ENGINE_ENV, "").strip().lower()
    if engine_override == "local":
        cmd += ["--engine", "local"]
    elif engine_override and engine_override != "cluster":
        return Result(
            type=VERIFIER_TYPE, passed=False,
            message=f"unrecognized {_ENGINE_ENV}={engine_override!r}; "
                    f"valid values: cluster, local",
        )

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return Result(
            type=VERIFIER_TYPE, passed=False,
            message="c8 feel evaluate timed out (30s)",
            details={"expression": expression, "context": context},
        )

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    if proc.returncode != 0:
        if _is_unreachable(stderr):
            return Result(
                type=VERIFIER_TYPE, passed=False, skipped=True,
                skip_reason="no-cluster",
                message="cluster unreachable; engine policy forbids --engine local fallback",
                details={"expression": expression, "stderr": stderr.strip()[:500]},
            )
        return Result(
            type=VERIFIER_TYPE, passed=False,
            message=f"c8 feel evaluate failed (exit {proc.returncode}); expression did not parse or evaluate",
            details={
                "expression": expression,
                "context": context,
                "stderr": stderr.strip()[:500],
                "stdout": stdout.strip()[:500],
            },
        )

    passed, msg = _compare(stdout, expected)
    engine = engine_override or "cluster"
    return Result(
        type=VERIFIER_TYPE,
        passed=passed,
        message=msg,
        details={
            "expression": expression,
            "context": context,
            "expected": expected,
            "actual_stdout": stdout.strip(),
            "engine": engine,
        },
    )
