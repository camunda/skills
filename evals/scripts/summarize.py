"""Render a Markdown summary of an eval run for the PR comment.

Reads ``.eval`` logs from a directory plus per-scenario
``baseline.json`` files, then emits a single Markdown block to stdout.
Consumed by ``.github/workflows/eval.yml`` via
``peter-evans/create-or-update-comment@v4``.

This is intentionally tiny in v1. As the comment shape evolves
(per-harness rows, A/B columns, hygiene flags), this is the file to
extend — keep it under ~150 lines.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Soft fallback so the script remains importable in environments
# without inspect-ai installed (e.g., during static analysis).
try:
    from inspect_ai.log import EvalLog, list_eval_logs, read_eval_log
except ImportError:  # pragma: no cover
    EvalLog = None  # type: ignore[assignment]
    list_eval_logs = None  # type: ignore[assignment]
    read_eval_log = None  # type: ignore[assignment]


def _load_baseline(scenario_dir: Path) -> dict | None:
    baseline_path = scenario_dir / "baseline.json"
    if not baseline_path.exists():
        return None
    return json.loads(baseline_path.read_text())


def _band_status(value: float, band: list[float] | None) -> str:
    if band is None or len(band) != 2:
        return "—"
    lo, hi = band
    if value < lo:
        return f"🟢 {value:.0f} (< {lo:.0f}, faster/cheaper)"
    if value > hi:
        return f"🔴 {value:.0f} (> {hi:.0f}, regression)"
    return f"✅ {value:.0f}"


def render(log_dir: Path, scenarios_dir: Path) -> str:
    if list_eval_logs is None:
        return "_inspect-ai not available; summary skipped._"

    log_paths = list_eval_logs(str(log_dir))
    if not log_paths:
        return "_No eval logs found._"

    rows: list[str] = []
    rows.append("### 🧪 Eval results\n")
    rows.append("| Scenario | with-skill | without-skill | tokens | duration_s |")
    rows.append("|---|---|---|---|---|")

    total_cost = 0.0
    for log_path in log_paths:
        log: EvalLog = read_eval_log(log_path)
        task_id = log.eval.task or Path(log_path).stem
        # Scenario id is the directory name; task name should match.
        scenario_dir = scenarios_dir / task_id
        baseline = _load_baseline(scenario_dir) if scenario_dir.exists() else None
        pass_rate = _pass_rate(log)
        tokens = _total_tokens(log)
        duration = _duration_s(log)
        total_cost += _cost_usd(log)
        with_col = f"{'✅' if pass_rate == 1.0 else '❌'} {pass_rate:.0%}"
        without_col = "—"  # without-skill arm rendered separately when present
        token_band = (baseline or {}).get("with_skill", {}).get("tokens")
        dur_band = (baseline or {}).get("with_skill", {}).get("duration_s")
        rows.append(
            f"| {task_id} | {with_col} | {without_col} "
            f"| {_band_status(tokens, token_band)} | {_band_status(duration, dur_band)} |"
        )

    rows.append("")
    rows.append(f"**Cost**: ${total_cost:.2f}")
    return "\n".join(rows)


def _pass_rate(log) -> float:
    samples = getattr(log, "samples", None) or []
    if not samples:
        return 0.0
    scores = [_score_value(s) for s in samples]
    return sum(scores) / len(scores)


def _score_value(sample) -> float:
    score = getattr(sample, "score", None) or getattr(sample, "scores", None)
    if score is None:
        return 0.0
    if isinstance(score, dict):
        score = next(iter(score.values()), None)
    value = getattr(score, "value", None)
    if isinstance(value, (int, float)):
        return float(value)
    return 1.0 if value == "C" or value == "correct" else 0.0


def _total_tokens(log) -> float:
    stats = getattr(log, "stats", None)
    if stats is None:
        return 0.0
    usage = getattr(stats, "model_usage", None) or {}
    total = 0
    for entry in usage.values():
        total += getattr(entry, "total_tokens", 0) or 0
    return float(total)


def _duration_s(log) -> float:
    stats = getattr(log, "stats", None)
    if stats is None:
        return 0.0
    return float(getattr(stats, "duration", 0) or 0)


def _cost_usd(log) -> float:
    # Inspect AI surfaces cost when the provider reports it; otherwise 0.
    stats = getattr(log, "stats", None)
    if stats is None:
        return 0.0
    return float(getattr(stats, "cost", 0) or 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", required=True, type=Path)
    parser.add_argument(
        "--scenarios-dir",
        default=Path(__file__).resolve().parent.parent / "scenarios",
        type=Path,
    )
    args = parser.parse_args()
    sys.stdout.write(render(args.log_dir, args.scenarios_dir))


if __name__ == "__main__":
    main()
