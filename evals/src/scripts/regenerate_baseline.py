"""Regenerate an eval's ``outcomes_baseline.json`` from its most recent run.

Records, per arm, the model and each sample's median token count across epochs
— the ceiling gate in ``pass_fail`` allows up to ``tokens × 1.5``. No bands, no
duration: outcome is gated per-sample by the scorers, not by a stored aggregate
that would drift as samples are added.

A baseline is an all-green snapshot or nothing: if any sample in the run
failed a gating scorer (or errored / never scored), regeneration refuses to
write and exits non-zero, naming the offenders. A partial baseline would leave
half the eval ungated, and a failed sample's token count is unrepresentative
anyway (a token-limit flail inflates it, an early error deflates it). Fix the
eval, get a clean run, then regenerate.

    evals-regenerate-baseline --target camunda-feel [--arm with_skill]

``--target`` is the eval dir path (``skills/<name>`` or ``scenarios/<name>``).
Review the diff before committing; regenerate one target at a time.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

from core.paths import EVALS_ROOT
from scripts.pass_fail import _outcome_rows

LOGS_DIR = EVALS_ROOT / "logs"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        required=True,
        help="eval dir path, e.g. skills/camunda-feel or scenarios/rocket-launch",
    )
    parser.add_argument("--arm", default="with_skill")
    parser.add_argument("--log-dir", default=LOGS_DIR, type=Path)
    args = parser.parse_args()

    target_dir = EVALS_ROOT / args.target.rstrip("/")
    if not (target_dir / "outcomes.py").exists():
        print(
            f"no outcomes.py at {args.target!r} "
            "(expected a skills/<name> or scenarios/<name> dir)",
            file=sys.stderr,
        )
        return 2

    task_name = target_dir.name.replace("-", "_")
    infos = list_eval_logs(str(args.log_dir))
    infos.sort(key=lambda i: i.mtime, reverse=True)
    chosen = None
    for info in infos:
        header = read_eval_log(info.name, header_only=True)
        if (
            header.eval.task == task_name
            and (header.eval.task_args or {}).get("arm", "with_skill") == args.arm
        ):
            chosen = info
            break
    if chosen is None:
        print(
            f"no {task_name} log for arm={args.arm} under {args.log_dir}",
            file=sys.stderr,
        )
        return 2

    log = read_eval_log(chosen.name)
    model = getattr(log.eval, "model", None) or "unknown"
    # A baseline is all-green or nothing: refuse to write if any sample failed a
    # gating scorer, or ran but never scored (errored). Either would leave a
    # partial baseline that silently ungates part of the eval. ``rows`` carries
    # only scored samples, so compare against the ids that actually ran.
    rows, _ = _outcome_rows(log, 1.0)
    scored_ids = {r["sample_id"] for r in rows}
    ran_ids = {str(s.id) for s in (getattr(log, "samples", None) or [])}
    failed = sorted(r["sample_id"] for r in rows if not r["pass"])
    unscored = sorted(ran_ids - scored_ids)
    if not rows or failed or unscored:
        problems = []
        if not rows:
            problems.append("no samples scored")
        if failed:
            problems.append(f"failed: {', '.join(failed)}")
        if unscored:
            problems.append(f"errored/unscored: {', '.join(unscored)}")
        print(
            f"refusing to regenerate {args.target} — a baseline must come from an "
            f"all-green run ({'; '.join(problems)}). Fix the eval, get a clean "
            "run, then regenerate.",
            file=sys.stderr,
        )
        return 1
    # Record the median per-id tokens/turns/tool_calls (rows carry the
    # epoch-reduced figures); tokens gate the cost ceiling, turns and tool_calls
    # are diagnostic (stored for the summary's delta, never gated). Sorted by id
    # so the committed JSON is stable regardless of log ordering.
    samples = {
        r["sample_id"]: {
            "tokens": round(r["tokens"]),
            "turns": round(r["turns"]),
            "tool_calls": round(r["tool_calls"]),
        }
        for r in sorted(rows, key=lambda r: r["sample_id"])
    }

    target = target_dir / "outcomes_baseline.json"
    existing = {}
    if target.exists():
        try:
            existing = json.loads(target.read_text())
        except json.JSONDecodeError:
            existing = {}

    baseline = {**existing, "model": model, args.arm: {"samples": samples}}
    target.write_text(json.dumps(baseline, indent=2) + "\n")
    print(
        f"wrote {target} (from {Path(chosen.name).name}, arm={args.arm}, model={model})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
