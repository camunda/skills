"""Regenerate an eval's ``baseline.json`` from its most recent run.

Records, per arm, the model and each sample's observed token count — the
ceiling gate in ``pass_fail`` allows up to ``tokens × 1.5``. No bands, no
duration, no pass_rate: outcome is gated per-sample by the scorers, not by a
stored aggregate that would drift as samples are added.

    evals-regen-baseline --target camunda-feel [--arm with_skill]

``--target`` is the directory name under ``skills/`` or ``scenarios/``.
Review the diff before committing; regenerate one target at a time.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

from core.metrics import baseline_dir, sample_tokens
from core.paths import EVALS_ROOT

LOGS_DIR = EVALS_ROOT / "logs"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target", required=True, help="dir name under skills/ or scenarios/"
    )
    parser.add_argument("--arm", default="with_skill")
    parser.add_argument("--log-dir", default=LOGS_DIR, type=Path)
    args = parser.parse_args()

    target_dir = baseline_dir(args.target)
    if target_dir is None:
        print(
            f"no task.py for target {args.target!r} under skills/ or scenarios/",
            file=sys.stderr,
        )
        return 2

    task_name = args.target.replace("-", "_")
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
    samples = {
        str(s.id): {"tokens": round(sample_tokens(s))}
        for s in (getattr(log, "samples", None) or [])
    }

    target = target_dir / "baseline.json"
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
