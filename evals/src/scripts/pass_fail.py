"""Summarize per-sample pass/fail across every scorer in an eval log.

Each scenario can carry multiple scorers (rocket-launch has four:
transcript + cluster + lint + cpt). Inspect's dashboard shows each
scorer's metric in its own column, but there's no native "did this
sample pass ALL scorers" gate — by design, ``status`` reflects
execution, not correctness.

This script post-processes a ``.eval`` log and emits, per sample,
whether every scorer scored ≥ 1.0. Useful for:

- Eyeballing baseline runs without trawling the viewer
- Wiring up CI red/green based on outcome (not just harness exit code)
- Catching the case where 3/4 scorers pass but the load-bearing one
  (e.g. ``cpt_scorer``) silently regressed

CLI:
    evals-pass-fail                       # latest log
    evals-pass-fail <log-file>            # specific log
    evals-pass-fail --threshold 0.5       # custom pass threshold
    evals-pass-fail --json                # machine-readable output

Exit code is 0 when every sample passes every scorer, 1 otherwise —
so this can be wired as a final CI gate after ``make eval``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

from core.paths import EVALS_ROOT

DEFAULT_LOG_DIR = EVALS_ROOT / "logs"


def _resolve_log_path(arg: str | None) -> Path:
    if arg:
        return Path(arg).resolve()
    logs = list_eval_logs(str(DEFAULT_LOG_DIR))
    if not logs:
        sys.stderr.write(f"no .eval logs found under {DEFAULT_LOG_DIR}\n")
        sys.exit(2)
    return Path(logs[0].name).resolve()


def _summarize_log(log_path: Path, threshold: float) -> tuple[list[dict], bool]:
    """Read the log and return per-sample summaries + an overall pass bit."""
    log = read_eval_log(str(log_path))
    rows: list[dict] = []
    all_passed = True
    for sample in log.samples or []:
        scorer_values: dict[str, float] = {}
        for scorer_name, score in (sample.scores or {}).items():
            value = score.value if hasattr(score, "value") else score
            if isinstance(value, (int, float)):
                scorer_values[scorer_name] = float(value)
            else:
                # Non-numeric (categorical) scores treated as 0.0 by
                # this gate — they need their own analysis path.
                scorer_values[scorer_name] = 0.0
        passes = {name: v >= threshold for name, v in scorer_values.items()}
        sample_pass = all(passes.values()) if passes else False
        if not sample_pass:
            all_passed = False
        rows.append(
            {
                "sample_id": str(sample.id),
                "scorers": scorer_values,
                "passes": passes,
                "pass": sample_pass,
            }
        )
    return rows, all_passed


def _render_table(rows: list[dict], log_path: Path, threshold: float) -> str:
    if not rows:
        return f"no samples in {log_path}"
    scorer_names = sorted({s for row in rows for s in row["scorers"]})
    header = ["sample", "pass"] + scorer_names
    widths = [max(len(h), 8) for h in header]
    for row in rows:
        widths[0] = max(widths[0], len(row["sample_id"]))
        for i, name in enumerate(scorer_names):
            cell = f"{row['scorers'].get(name, '-'):.2f}" if name in row["scorers"] else "-"
            widths[2 + i] = max(widths[2 + i], len(cell))
    lines = [
        f"log: {log_path}",
        f"threshold: {threshold}",
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
    lines.append(f"overall: {passed}/{len(rows)} sample(s) passed every scorer (≥ {threshold})")
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
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    args = parser.parse_args()

    log_path = _resolve_log_path(args.log_path)
    rows, all_passed = _summarize_log(log_path, args.threshold)

    if args.json:
        print(json.dumps({"log": str(log_path), "threshold": args.threshold, "samples": rows}, indent=2))
    else:
        print(_render_table(rows, log_path, args.threshold))

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
