"""Render a Markdown summary of an eval run for the PR comment.

Reads ``.eval`` logs from a directory, compares each against its
per-scenario ``baseline.json``, and emits one Markdown block to stdout.
Consumed by ``.github/workflows/eval.yml`` via
``peter-evans/create-or-update-comment@v4``.

The verdict is **non-gating** — the comment reports pass/fail and the
baseline deltas as a signal; it does not block the PR. Each scenario
gets a one-line verdict in the summary table plus a collapsible block
with the full per-sample / baseline breakdown (reused verbatim from
``evals-pass-fail`` so the comment and the CLI never drift).

Intentionally tiny — keep it under ~150 lines.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from inspect_ai.log import list_eval_logs, read_eval_log
except ImportError:  # pragma: no cover
    list_eval_logs = None  # type: ignore[assignment]
    read_eval_log = None  # type: ignore[assignment]

from core.metrics import pass_rate, scenario_id, task_arg
from core.paths import SCENARIOS_DIR as _DEFAULT_SCENARIOS_DIR
from scripts.pass_fail import (
    _baseline_gate,
    _load_baseline,
    _render_table,
    _summarize_log,
)

_PASS_RATE_TOLERANCE = 0.10
_THRESHOLD = 1.0


def render(log_dir: Path) -> str:
    if list_eval_logs is None:
        return "_inspect-ai not available; summary skipped._"

    log_paths = list_eval_logs(str(log_dir))
    if not log_paths:
        return "_No eval logs found._"

    head = [
        # Stable marker so the workflow's find-comment step updates this
        # comment in place instead of posting a new one each run.
        "<!-- camunda-skills-eval-comment -->",
        "### 🧪 Eval results",
        "",
        "_Non-blocking signal — reports outcome + baseline deltas; does "
        "not gate merge._",
        "",
        "| Scenario | Arm | Verdict | pass_rate | Baseline |",
        "|---|---|---|---|---|",
    ]
    details: list[str] = []

    for log_info in log_paths:
        log_name = getattr(log_info, "name", str(log_info))
        log = read_eval_log(log_name)
        scenario = scenario_id(log) or Path(log_name).stem
        arm = task_arg(log, "arm") or "—"

        rows, samples_passed = _summarize_log(log, _THRESHOLD)
        baseline = _load_baseline(scenario)
        checks: list[dict] | None = None
        baseline_passed = True
        if baseline is not None and arm != "—":
            checks, baseline_passed = _baseline_gate(
                log, baseline, arm, _PASS_RATE_TOLERANCE
            )

        verdict = "✅ pass" if (samples_passed and baseline_passed) else "⚠️ check"
        baseline_cell = _baseline_cell(checks)
        head.append(
            f"| {scenario} | {arm} | {verdict} | {pass_rate(log):.0%} "
            f"| {baseline_cell} |"
        )

        table = _render_table(
            rows, Path(log_name), _THRESHOLD, checks, scenario, arm
        )
        details.append(
            f"<details><summary>{scenario} ({arm})</summary>\n\n"
            f"```\n{table}\n```\n</details>"
        )

    return "\n".join(head + ["", *details])


def _baseline_cell(checks: list[dict] | None) -> str:
    """One-glance baseline status: counts in-band vs out-of-band bands."""
    if not checks:
        return "— (no baseline)"
    band_checks = [c for c in checks if "band" in c]
    failed = [c for c in band_checks if not c.get("pass")]
    pr = next((c for c in checks if c.get("check") == "pass_rate"), None)
    pr_mark = "" if pr is None or pr.get("pass") else " · pass_rate below floor"
    if not band_checks:
        return ("✅ within bands" if not pr_mark else f"🔴{pr_mark}")
    if failed:
        return f"🔴 {len(failed)}/{len(band_checks)} bands out{pr_mark}"
    return f"✅ {len(band_checks)} bands in{pr_mark}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", required=True, type=Path)
    parser.add_argument(
        "--scenarios-dir",
        default=_DEFAULT_SCENARIOS_DIR,
        type=Path,
        help="(unused; baselines resolve via core.paths) kept for compatibility",
    )
    args = parser.parse_args()
    sys.stdout.write(render(args.log_dir))


if __name__ == "__main__":
    main()
