"""Per-sample pass/fail + baseline-aware gate for an Inspect eval log.

Two layers of checking. Both are evaluated; the script exits 0 only
when every layer passes.

**Per-sample scorer pass.** For each sample, every scorer must score
≥ ``--threshold`` (default 1.0). Letter-grade scorers (``model_graded_qa``
emits ``C`` / ``P`` / ``I``) are converted via the standard
1.0 / 0.5 / 0.0 mapping before comparison.

**Baseline gate (when ``--baseline-aware`` is set, or auto when the
scenario's ``baseline.json`` is discoverable).** Compares the run
against the matching arm's baseline:

- ``pass_rate``: must be ≥ ``baseline.{arm}.pass_rate - tolerance``
- ``tokens_total``: must land in ``baseline.{arm}.tokens`` band
- ``duration_total_s``: must land in ``baseline.{arm}.duration_s`` band

Bands already have width baked in (±15% tokens, ±30% duration), so
no additional tolerance is added on top. pass_rate gets an explicit
``--pass-rate-tolerance`` (default 0.10) because the underlying
metric is bounded [0, 1] and a flat percentage band would be
asymmetric near the endpoints.

CLI:
    evals-pass-fail                            # latest log
    evals-pass-fail <log-file>                 # specific log
    evals-pass-fail --threshold 0.5            # custom per-scorer pass
    evals-pass-fail --json                     # machine-readable output
    evals-pass-fail --no-baseline              # skip baseline gate (per-sample only)
    evals-pass-fail --pass-rate-tolerance 0.2  # looser pass_rate floor

Exit code is 0 on full pass, 1 otherwise — wire as final CI gate
after ``make eval``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from inspect_ai.log import list_eval_logs, read_eval_log

from core.metrics import (
    is_gating,
    pass_rate,
    sample_duration_s,
    sample_tokens,
    scenario_id,
    score_to_float,
    task_arg,
)
from core.paths import EVALS_ROOT, SCENARIOS_DIR

DEFAULT_LOG_DIR = EVALS_ROOT / "logs"


def _resolve_log_path(arg: str | None) -> str:
    if arg:
        return str(Path(arg).resolve())
    logs = list_eval_logs(str(DEFAULT_LOG_DIR))
    if not logs:
        sys.stderr.write(f"no .eval logs found under {DEFAULT_LOG_DIR}\n")
        sys.exit(2)
    # EvalLogInfo.name is an fsspec URI (e.g. file:///…/foo.eval) that
    # read_eval_log accepts directly — do NOT Path()-wrap it, or a
    # "file:/…" name gets treated as relative and joined onto the cwd
    # (CI hit `…/skills/skills/file:/…/foo.eval`). Log filenames are
    # timestamp-prefixed, so the lexically-greatest name is the newest.
    return max(logs, key=lambda li: li.name).name


def _summarize_log(log, threshold: float) -> tuple[list[dict], bool]:
    """Per-sample scorer breakdown + an overall pass bit.

    Diagnostic scorers (``score.metadata.gating == False``) are
    surfaced in the table but skipped when computing whether the
    sample passed its threshold — they're informational.
    """
    rows: list[dict] = []
    all_passed = True
    for sample in log.samples or []:
        scorer_values: dict[str, float] = {}
        diagnostic_scorers: set[str] = set()
        for scorer_name, score in (sample.scores or {}).items():
            if not is_gating(score):
                diagnostic_scorers.add(scorer_name)
            value = score.value if hasattr(score, "value") else score
            if isinstance(value, (int, float, str, bool)):
                # Inspect's Value→float: numbers pass through, C/P/I map
                # to 1.0/0.5/0.0 per the accuracy() convention.
                scorer_values[scorer_name] = score_to_float(value)
            else:
                scorer_values[scorer_name] = 0.0
        # Only gating scorers contribute to the per-sample pass bit.
        gating_passes = {
            name: v >= threshold
            for name, v in scorer_values.items()
            if name not in diagnostic_scorers
        }
        sample_pass = all(gating_passes.values()) if gating_passes else False
        if not sample_pass:
            all_passed = False
        rows.append(
            {
                "sample_id": str(sample.id),
                "scorers": scorer_values,
                "diagnostic": sorted(diagnostic_scorers),
                "pass": sample_pass,
            }
        )
    return rows, all_passed


def _load_baseline(scenario: str | None) -> dict[str, Any] | None:
    if not scenario:
        return None
    path = SCENARIOS_DIR / scenario / "baseline.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _band_check(value: float, band: Any) -> bool | None:
    """Whether ``value`` lands inside ``{low, high}``.

    Returns ``None`` when the band itself is malformed (treated as
    "no gate for this metric").
    """
    if not isinstance(band, dict):
        return None
    lo, hi = band.get("low"), band.get("high")
    if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))):
        return None
    return lo <= value <= hi


def _baseline_gate(
    log, baseline: dict[str, Any], arm: str, pass_rate_tolerance: float
) -> tuple[list[dict], bool]:
    """Compare the run against ``baseline[arm]``. Per-sample bands.

    Arm-level pass_rate floor is enforced; per-sample tokens and
    duration bands are checked for every sample whose id matches a
    baseline entry. Samples without a baseline entry (new additions)
    produce a warn-only row — the gate doesn't fail on them.
    """
    arm_baseline = baseline.get(arm)
    if not isinstance(arm_baseline, dict):
        return (
            [
                {
                    "check": f"baseline.{arm}",
                    "pass": False,
                    "detail": f"no baseline entry for arm={arm!r}",
                }
            ],
            False,
        )

    checks: list[dict] = []
    all_passed = True

    # Arm-level pass_rate floor (with tolerance — pass_rate is bounded [0,1]).
    run_pass_rate = pass_rate(log)
    floor = arm_baseline.get("pass_rate", 0.0) - pass_rate_tolerance
    pr_passed = run_pass_rate >= floor
    checks.append(
        {
            "check": "pass_rate",
            "pass": pr_passed,
            "observed": round(run_pass_rate, 4),
            "floor": round(floor, 4),
            "baseline": arm_baseline.get("pass_rate"),
        }
    )
    if not pr_passed:
        all_passed = False

    # Per-sample resource bands.
    sample_baselines = arm_baseline.get("samples") or {}
    for sample in getattr(log, "samples", None) or []:
        sample_id = str(sample.id)
        sample_baseline = sample_baselines.get(sample_id)
        if not isinstance(sample_baseline, dict):
            # New sample (no baseline entry yet): surface but don't
            # gate. Adding a sample shouldn't break the CI gate.
            checks.append(
                {
                    "check": f"samples.{sample_id}",
                    "pass": True,
                    "detail": "no baseline entry (new sample) — regen baseline",
                }
            )
            continue

        run_tokens = sample_tokens(sample)
        run_duration = sample_duration_s(sample)

        for metric, observed in (
            ("tokens", run_tokens),
            ("duration_s", run_duration),
        ):
            verdict = _band_check(observed, sample_baseline.get(metric))
            if verdict is None:
                continue
            band = sample_baseline[metric]
            checks.append(
                {
                    "check": f"{sample_id}.{metric}",
                    "pass": verdict,
                    "observed": round(observed, 2),
                    "band": {"low": band["low"], "high": band["high"]},
                }
            )
            if not verdict:
                all_passed = False

    return checks, all_passed


def _render_table(
    rows: list[dict],
    log_path: Path,
    threshold: float,
    baseline_checks: list[dict] | None,
    scenario: str | None,
    arm: str | None,
) -> str:
    if not rows:
        return f"no samples in {log_path}"
    scorer_names = sorted({s for row in rows for s in row["scorers"]})
    diagnostic_names = {name for row in rows for name in row.get("diagnostic", [])}
    # Suffix diagnostic columns so the gate/info distinction is visible
    # in the table header.
    header = ["sample", "pass"] + [
        f"{n} (d)" if n in diagnostic_names else n for n in scorer_names
    ]
    widths = [max(len(h), 8) for h in header]
    for row in rows:
        widths[0] = max(widths[0], len(row["sample_id"]))
        for i, name in enumerate(scorer_names):
            cell = f"{row['scorers'].get(name, '-'):.2f}" if name in row["scorers"] else "-"
            widths[2 + i] = max(widths[2 + i], len(cell))
    lines = [
        f"log: {log_path}",
        f"scenario: {scenario or '(unknown)'}, arm: {arm or '(unknown)'}",
        f"per-sample threshold: {threshold}",
        "",
        "  ".join(h.ljust(w) for h, w in zip(header, widths)),
        "  ".join("-" * w for w in widths),
    ]
    for row in rows:
        cells = [
            row["sample_id"].ljust(widths[0]),
            ("PASS" if row["pass"] else "FAIL").ljust(widths[1]),
        ]
        for i, name in enumerate(scorer_names):
            val = row["scorers"].get(name)
            cells.append(("-" if val is None else f"{val:.2f}").ljust(widths[2 + i]))
        lines.append("  ".join(cells))
    lines.append("")
    passed = sum(1 for r in rows if r["pass"])
    lines.append(f"per-sample: {passed}/{len(rows)} sample(s) passed every scorer (≥ {threshold})")

    if baseline_checks:
        lines.append("")
        lines.append("baseline gate:")
        for check in baseline_checks:
            mark = "PASS" if check.get("pass") else "FAIL"
            detail = ", ".join(
                f"{k}={v}" for k, v in check.items() if k not in {"check", "pass"}
            )
            lines.append(f"  [{mark}] {check['check']}: {detail}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log_path", nargs="?", help="Path to a .eval log; default = latest")
    parser.add_argument(
        "--threshold",
        type=float,
        default=1.0,
        help="Per-scorer pass threshold (default 1.0)",
    )
    parser.add_argument(
        "--no-baseline",
        action="store_true",
        help="Skip the baseline-aware gate (per-sample scorers only)",
    )
    parser.add_argument(
        "--pass-rate-tolerance",
        type=float,
        default=0.10,
        help="How far below baseline pass_rate is still acceptable (default 0.10)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    args = parser.parse_args()

    log_path = _resolve_log_path(args.log_path)
    log = read_eval_log(log_path)
    rows, samples_passed = _summarize_log(log, args.threshold)

    scenario = scenario_id(log)
    arm = task_arg(log, "arm")
    baseline_checks: list[dict] | None = None
    baseline_passed = True
    if not args.no_baseline:
        baseline = _load_baseline(scenario)
        if baseline is not None and arm is not None:
            baseline_checks, baseline_passed = _baseline_gate(
                log, baseline, arm, args.pass_rate_tolerance
            )

    overall_passed = samples_passed and baseline_passed

    if args.json:
        print(
            json.dumps(
                {
                    "log": str(log_path),
                    "scenario": scenario,
                    "arm": arm,
                    "threshold": args.threshold,
                    "samples": rows,
                    "baseline_checks": baseline_checks,
                    "pass": overall_passed,
                },
                indent=2,
            )
        )
    else:
        print(
            _render_table(rows, log_path, args.threshold, baseline_checks, scenario, arm)
        )

    sys.exit(0 if overall_passed else 1)


if __name__ == "__main__":
    main()
