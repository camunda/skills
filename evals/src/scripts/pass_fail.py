"""Per-sample pass/fail gate for an Inspect eval log.

Two stages, both keyed by sample id (so adding a sample never shifts an
existing comparison):

1. **Outcome** — every gating scorer on a sample must score ≥ ``--threshold``
   (default 1.0). The "works / doesn't work anymore" signal. Diagnostic
   scorers (``metadata.gating == False``) are shown but don't gate. A sample
   that ran but never scored (errored / aborted), or a run with no scored
   samples at all, fails too — the gate sees only scored samples, so an
   all-errored run must not pass by omission (mirrors the all-green guard in
   ``regenerate_baseline``).
2. **Cost** — only when an ``outcomes_baseline.json`` exists for the eval AND
   the sample passed outcome: observed **input + output** tokens must be ≤
   ``baseline.<arm>.samples.<id>`` (input + output) ``× 1.5`` (upper ceiling
   only). The "still works but costs ~2× now" signal. We gate input+output, not
   the all-in total: the total is ~90% cache-read — the cheapest, most volatile
   category — so a total-token ceiling polices cache churn while letting real
   output growth through. Cache-read/-write are recorded (in the baseline and
   the summary) for diagnosis, not gated. A sample with no baseline entry is
   reported, not gated. The whole cost stage is skipped (with a warning) when
   the run's model differs from the baseline's — ceilings are model-specific.

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
    REDUCED_FIELDS,
    baseline_dir,
    eval_name,
    gating_by_scorer,
    model_id,
    reduced_metrics,
    reduced_scores,
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


def _io(d: dict) -> float | None:
    """input + output (the gated quantity) from a flat metrics dict — a
    ``reduced_metrics`` row, whose token categories sit at the top level. None
    when either component is missing."""
    i, o = d.get("input"), d.get("output")
    if isinstance(i, (int, float)) and isinstance(o, (int, float)):
        return float(i) + float(o)
    return None


def _baseline_io(entry: dict) -> float | None:
    """input + output from a committed baseline entry, whose token categories are
    nested under ``tokens`` (``{input, cache_write, cache_read, output}``). None
    when the entry predates the nested schema or is partial."""
    if not isinstance(entry, dict):
        return None
    tokens = entry.get("tokens")
    return _io(tokens) if isinstance(tokens, dict) else None


def _outcome_rows(log, threshold: float) -> tuple[list[dict], bool]:
    """Per-sample scorer breakdown + overall outcome-pass bit.

    One row per distinct sample id, reading epoch-reduced scores
    (``reduced_scores``) and cost/effort signals (``reduced_metrics``) — so a
    multi-epoch run yields one verdict per sample, not one per id×epoch. With a
    ``mean`` reducer and the default threshold 1.0, a sample must pass *every*
    epoch to be green; a flaky 2/3 reduces to 0.67 and fails.
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
                # input/output gate the cost ceiling; cache_*/tokens/turns/
                # tool_calls/duration_s are diagnostic (see REDUCED_FIELDS).
                **{f: m.get(f, 0.0) for f in REDUCED_FIELDS},
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


def _model_mismatch(log, baseline: dict) -> str | None:
    """A reason string when the run's model differs from the baseline's, else None.

    Token ceilings are model-specific, so gating a run against a baseline
    recorded on a different model is invalid — it false-fails on a pricier model
    and false-passes on a cheaper one. When both models are known and differ, the
    caller skips the cost gate. ``"unknown"`` on either side (an older baseline,
    a log without a model) is treated as no-info, not a mismatch — gate as before.
    """
    run = model_id(log)
    base = baseline.get("model")
    if run and base and "unknown" not in (run, base) and run != base:
        return f"run model {run!r} != baseline model {base!r} — cost gate skipped"
    return None


def _cost_checks(
    rows: list[dict], baseline: dict, arm: str | None
) -> tuple[list[dict], bool]:
    """Per-sample input+output ceiling for samples that passed outcome."""
    arm_block = baseline.get(arm or "with_skill") or {}
    sample_baselines = arm_block.get("samples") or {}
    checks: list[dict] = []
    all_passed = True
    for row in rows:
        if not row["pass"]:
            continue
        entry = sample_baselines.get(row["sample_id"])
        base_io = _baseline_io(entry)
        if base_io is None:
            checks.append(
                {
                    "sample_id": row["sample_id"],
                    "pass": True,
                    "note": "no baseline (regenerate)",
                }
            )
            continue
        obs_io = _io(row) or 0.0
        ceiling = base_io * CEILING_MULTIPLIER
        ok = obs_io <= ceiling
        all_passed = all_passed and ok
        checks.append(
            {
                "sample_id": row["sample_id"],
                "pass": ok,
                "io": round(obs_io),
                "baseline": round(base_io),
                "ceiling": round(ceiling),
                # total tokens carried for the summary's headline; not gated.
                "tokens": round(row.get("tokens", 0.0)),
            }
        )
    return checks, all_passed


def _render(rows, cost_checks, name, arm, threshold) -> str:
    lines = [
        f"eval: {name or '(unknown)'}  arm: {arm or '(n/a)'}  threshold: {threshold}",
        "",
    ]
    for r in rows:
        scs = " ".join(
            f"{n}={v:.2f}{'*' if n in r['diagnostic'] else ''}"
            for n, v in sorted(r["scorers"].items())
        )
        lines.append(f"  [{'PASS' if r['pass'] else 'FAIL'}] {r['sample_id']}: {scs}")
    passed = sum(1 for r in rows if r["pass"])
    lines.append(
        f"\noutcome: {passed}/{len(rows)} sample(s) passed every gating scorer "
        f"(≥ {threshold})"
    )
    if any(r["diagnostic"] for r in rows):
        lines.append("(* = diagnostic scorer, shown but not gating)")
    if cost_checks:
        lines.append("\ncost gate — input+output (baseline × 1.5):")
        for c in cost_checks:
            if "note" in c:
                lines.append(f"  [warn] {c['sample_id']}: {c['note']}")
            else:
                lines.append(
                    f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['sample_id']}: "
                    f"io {c['io']} / ceiling {c['ceiling']} (baseline {c['baseline']})"
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

    # A sample that ran but never scored (errored / aborted), or a run with no
    # scored samples at all, is a failure — not a pass by omission. The outcome
    # gate above only sees scored samples, so catch the gap here against the ids
    # that actually ran. ``s.id`` repeats across epochs; the set dedupes it, so
    # this is epoch-safe (same comparison regenerate_baseline uses).
    scored_ids = {r["sample_id"] for r in rows}
    ran_ids = {str(s.id) for s in (getattr(log, "samples", None) or [])}
    unscored = sorted(ran_ids - scored_ids)
    run_complete = bool(rows) and not unscored

    cost_checks: list[dict] = []
    cost_passed = True
    cost_skipped: str | None = None
    if not args.no_baseline:
        baseline = _load_baseline(name)
        if baseline is not None:
            cost_skipped = _model_mismatch(log, baseline)
            if cost_skipped is None:
                cost_checks, cost_passed = _cost_checks(rows, baseline, arm)

    overall = outcome_passed and cost_passed and run_complete
    if args.json:
        print(
            json.dumps(
                {
                    "eval": name,
                    "arm": arm,
                    "threshold": args.threshold,
                    "samples": rows,
                    "unscored": unscored,
                    "cost_checks": cost_checks,
                    "cost_gate_skipped": cost_skipped,
                    "pass": overall,
                },
                indent=2,
                default=float,
            )
        )
    else:
        print(_render(rows, cost_checks, name, arm, args.threshold))
        if not rows:
            print("\n[FAIL] no samples scored")
        elif unscored:
            print(
                f"\n[FAIL] {len(unscored)} sample(s) ran but never scored "
                f"(errored/aborted): {', '.join(unscored)}"
            )
        if cost_skipped:
            print(f"\n[warn] {cost_skipped}")
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
