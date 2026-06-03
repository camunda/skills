"""Per-sample pass/fail gate for an Inspect eval log.

Two stages, both keyed by sample id (so adding a sample never shifts an
existing comparison):

1. **Outcome** — every gating scorer on a sample must score ≥ ``--threshold``
   (default 1.0). The "works / doesn't work anymore" signal. Diagnostic
   scorers (``metadata.gating == False``) are shown but don't gate.
2. **Cost** — only when an ``outcomes_baseline.json`` exists for the eval AND the sample
   passed outcome: observed tokens must be ≤ ``baseline.<arm>.samples.<id>.tokens
   × 1.5`` (upper ceiling only). The "still works but costs ~2× now" signal.
   A sample with no baseline entry is reported, not gated.

Exit 0 on full pass, 1 otherwise. Wire as the CI gate after a run.

    evals-pass-fail [log] [--threshold 1.0] [--no-baseline] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

from core.metrics import (
    baseline_dir,
    gating_by_scorer,
    reduced_metrics,
    reduced_scores,
    eval_name,
    task_arg,
)
from core.paths import EVALS_ROOT

DEFAULT_LOG_DIR = EVALS_ROOT / "logs"
CEILING_MULTIPLIER = 1.5


def _resolve_log_path(arg: str | None) -> str:
    if arg:
        return str(Path(arg).resolve())
    logs = list_eval_logs(str(DEFAULT_LOG_DIR))
    if not logs:
        sys.stderr.write(f"no .eval logs found under {DEFAULT_LOG_DIR}\n")
        sys.exit(2)
    # EvalLogInfo.name is an fsspec URI read_eval_log accepts directly; do NOT
    # Path()-wrap it. Names are timestamp-prefixed, so lexically-greatest = newest.
    return max(logs, key=lambda li: li.name).name


def _outcome_rows(log, threshold: float) -> tuple[list[dict], bool]:
    """Per-sample scorer breakdown + overall outcome-pass bit.

    One row per distinct sample id, reading epoch-reduced scores
    (``reduced_scores``) and cost/effort signals (``reduced_metrics``) — so a multi-epoch run
    yields one verdict per sample, not one per id×epoch. With a ``mean`` reducer
    and the default threshold 1.0, a sample must pass *every* epoch to be green;
    a flaky 2/3 reduces to 0.67 and fails.
    """
    gating = gating_by_scorer(log)
    metrics = reduced_metrics(log)
    rows: list[dict] = []
    all_passed = True
    for sample_id, values in reduced_scores(log).items():
        diagnostic = {n for n in values if not gating.get(n, True)}
        gated = {n: v >= threshold for n, v in values.items() if n not in diagnostic}
        ok = all(gated.values()) if gated else False
        all_passed = all_passed and ok
        m = metrics.get(sample_id, {})
        rows.append(
            {
                "sample_id": sample_id,
                "scorers": values,
                "diagnostic": sorted(diagnostic),
                # tokens gates the cost ceiling; turns/tool_calls are diagnostic.
                "tokens": m.get("tokens", 0.0),
                "turns": m.get("turns", 0.0),
                "tool_calls": m.get("tool_calls", 0.0),
                "pass": ok,
            }
        )
    return rows, all_passed


def _load_baseline(name: str | None) -> dict | None:
    d = baseline_dir(name)
    if d is None:
        return None
    path = d / "outcomes_baseline.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _cost_checks(
    rows: list[dict], baseline: dict, arm: str | None
) -> tuple[list[dict], bool]:
    """Per-sample token ceiling for samples that passed outcome."""
    arm_block = baseline.get(arm or "with_skill") or {}
    sample_baselines = arm_block.get("samples") or {}
    checks: list[dict] = []
    all_passed = True
    for row in rows:
        if not row["pass"]:
            continue
        entry = sample_baselines.get(row["sample_id"])
        tokens = entry.get("tokens") if isinstance(entry, dict) else None
        if not isinstance(tokens, (int, float)):
            checks.append(
                {
                    "sample_id": row["sample_id"],
                    "pass": True,
                    "note": "no baseline (regenerate)",
                }
            )
            continue
        ceiling = tokens * CEILING_MULTIPLIER
        ok = row["tokens"] <= ceiling
        all_passed = all_passed and ok
        checks.append(
            {
                "sample_id": row["sample_id"],
                "pass": ok,
                "tokens": round(row["tokens"]),
                "baseline": tokens,
                "ceiling": round(ceiling),
            }
        )
    return checks, all_passed


def _render(rows, cost_checks, name, arm, threshold) -> str:
    lines = [
        f"eval: {name or '(unknown)'}  arm: {arm or '(n/a)'}  threshold: {threshold}",
        "",
    ]
    for r in rows:
        scs = " ".join(f"{n}={v:.2f}" for n, v in sorted(r["scorers"].items()))
        lines.append(f"  [{'PASS' if r['pass'] else 'FAIL'}] {r['sample_id']}: {scs}")
    passed = sum(1 for r in rows if r["pass"])
    lines.append(
        f"\noutcome: {passed}/{len(rows)} sample(s) passed every gating scorer (≥ {threshold})"
    )
    if cost_checks:
        lines.append("\ntoken budget (baseline × 1.5):")
        for c in cost_checks:
            if "note" in c:
                lines.append(f"  [warn] {c['sample_id']}: {c['note']}")
            else:
                lines.append(
                    f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['sample_id']}: "
                    f"{c['tokens']} / ceiling {c['ceiling']} (baseline {c['baseline']})"
                )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "log_path", nargs="?", help="path to a .eval log; default = latest"
    )
    parser.add_argument("--threshold", type=float, default=1.0)
    parser.add_argument("--no-baseline", action="store_true", help="outcome gate only")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    log = read_eval_log(_resolve_log_path(args.log_path))
    name = eval_name(log)
    arm = task_arg(log, "arm")
    rows, outcome_passed = _outcome_rows(log, args.threshold)

    cost_checks: list[dict] = []
    cost_passed = True
    if not args.no_baseline:
        baseline = _load_baseline(name)
        if baseline is not None:
            cost_checks, cost_passed = _cost_checks(rows, baseline, arm)

    overall = outcome_passed and cost_passed
    if args.json:
        print(
            json.dumps(
                {
                    "eval": name,
                    "arm": arm,
                    "threshold": args.threshold,
                    "samples": rows,
                    "cost_checks": cost_checks,
                    "pass": overall,
                },
                indent=2,
                default=float,
            )
        )
    else:
        print(_render(rows, cost_checks, name, arm, args.threshold))
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
