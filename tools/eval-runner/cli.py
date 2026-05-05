#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "click>=8.1",
#     "jsonschema>=4.21",
# ]
# ///
"""Eval-runner CLI: run / triggers / quality / compare / promote subcommands.

This is the foundation; subcommands have stub implementations that exercise
the iteration scaffolding and the path relativizer. Real model calls and
verifier dispatch land under Issues #6, #7, #8, #9.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent))

from baseline import Baseline, diff, load as load_baseline  # noqa: E402
import quality_eval  # noqa: E402
import report as report_mod  # noqa: E402
import trigger_eval  # noqa: E402
from paths import relativize_grading  # noqa: E402
from verifiers import discover as discover_verifiers  # noqa: E402


def _repo_root(start: Path) -> Path:
    cur = start
    for _ in range(8):
        if (cur / ".git").exists() or (cur / "skills").is_dir():
            return cur
        cur = cur.parent
    return start


def _next_iteration_dir(repo_root: Path, skill: str) -> Path:
    base = repo_root / "evals" / skill
    base.mkdir(parents=True, exist_ok=True)
    existing = [
        int(p.name.split("-", 1)[1])
        for p in base.iterdir()
        if p.is_dir() and p.name.startswith("iteration-") and p.name.split("-", 1)[1].isdigit()
    ]
    n = (max(existing) + 1) if existing else 1
    out = base / f"iteration-{n}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _git_head(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            text=True,
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _git_dirty(repo_root: Path) -> bool:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo_root), "status", "--porcelain"], text=True
        )
        return bool(out.strip())
    except Exception:  # noqa: BLE001
        return True


@click.group()
@click.option(
    "--repo-root",
    "repo_root_opt",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Override repo root (defaults to nearest ancestor with .git or skills/).",
)
@click.option(
    "--max-usd",
    type=float,
    default=None,
    help="Soft budget guard. Aborts before running if estimated cost exceeds this.",
)
@click.pass_context
def main(ctx: click.Context, repo_root_opt: Path | None, max_usd: float | None) -> None:
    ctx.ensure_object(dict)
    ctx.obj["repo_root"] = repo_root_opt or _repo_root(Path.cwd())
    ctx.obj["max_usd"] = max_usd


@main.command()
@click.option("--skill", required=True, help="Skill directory name, e.g. camunda-feel.")
@click.option("--runs", "trials", default=3, help="Trials per case.")
@click.option("--dry-run", is_flag=True, help="Scaffold without calling any model.")
@click.pass_context
def run(ctx: click.Context, skill: str, trials: int, dry_run: bool) -> None:
    """Run trigger + quality evals for SKILL and write iteration data."""
    repo_root: Path = ctx.obj["repo_root"]
    iteration_dir = _next_iteration_dir(repo_root, skill)
    if dry_run:
        trigger_eval.run_dry(repo_root, skill, iteration_dir, trials)
        quality_eval.run_dry(repo_root, skill, iteration_dir, trials)
        summary = {
            "skill": skill,
            "iteration": iteration_dir.name,
            "trials_per_case": trials,
            "status": "dry-run",
            "verifiers_registered": sorted(discover_verifiers().keys()),
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "git_head": _git_head(repo_root),
        }
        (iteration_dir / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        report_mod.render_iteration(iteration_dir, repo_root)
        report_mod.render_index(iteration_dir.parent)
        click.echo(f"[dry-run] scaffolded {iteration_dir.relative_to(repo_root)}")
        return
    raise click.ClickException(
        "live run not implemented yet (Issues #6/#7); use --dry-run for now."
    )


@main.command()
@click.option("--skill", required=True)
@click.option("--runs", "trials", default=3)
@click.option("--workers", default=5, help="Parallel workers passed to run_eval.py.")
@click.option("--timeout", default=30, help="Per-query timeout seconds (passed through).")
@click.option("--model", default=None, help="Harness model id; default is the user's configured default.")
@click.option("--dry-run", is_flag=True)
@click.pass_context
def triggers(
    ctx: click.Context,
    skill: str,
    trials: int,
    workers: int,
    timeout: int,
    model: str | None,
    dry_run: bool,
) -> None:
    """Run trigger eval (Tier 1) only."""
    repo_root: Path = ctx.obj["repo_root"]
    iteration_dir = _next_iteration_dir(repo_root, skill)
    if dry_run:
        trigger_eval.run_dry(repo_root, skill, iteration_dir, trials)
        click.echo(f"[dry-run] {iteration_dir.relative_to(repo_root)}/triggers/")
        return
    summary = trigger_eval.run_live(
        repo_root, skill, iteration_dir,
        runs=trials, workers=workers, timeout=timeout, model=model,
    )
    click.echo(
        f"triggers: F1={summary['f1']:.2f} "
        f"precision={summary['precision']:.2f} recall={summary['recall']:.2f} "
        f"({summary['positive_cases']} positive + {summary['negative_cases']} negative)"
    )


@main.command()
@click.option("--skill", required=True)
@click.option("--runs", "trials", default=3)
@click.option("--dry-run", is_flag=True)
@click.pass_context
def quality(ctx: click.Context, skill: str, trials: int, dry_run: bool) -> None:
    """Run quality eval (Tier 2) only."""
    repo_root: Path = ctx.obj["repo_root"]
    iteration_dir = _next_iteration_dir(repo_root, skill)
    if dry_run:
        quality_eval.run_dry(repo_root, skill, iteration_dir, trials)
        click.echo(f"[dry-run] {iteration_dir.relative_to(repo_root)}")
        return
    raise click.ClickException("live quality eval not implemented yet (Issue #7).")


@main.command()
@click.option("--skill", required=True)
@click.option(
    "--iteration",
    "iteration_arg",
    default=None,
    help="Iteration directory to compare. Defaults to the latest under evals/<skill>/.",
)
@click.pass_context
def compare(ctx: click.Context, skill: str, iteration_arg: str | None) -> None:
    """Diff a candidate iteration against the committed baseline."""
    repo_root: Path = ctx.obj["repo_root"]
    base = load_baseline(repo_root, skill)
    if base is None:
        click.echo(json.dumps({"skill": skill, "status": "bootstrap"}, indent=2))
        sys.exit(0)
    iteration_dir = _resolve_iteration(repo_root, skill, iteration_arg)
    candidate_path = iteration_dir / "summary.json"
    if not candidate_path.exists():
        raise click.ClickException(f"no summary.json under {iteration_dir}")
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    d = diff(base, candidate)
    out = {
        "skill": skill,
        "iteration": iteration_dir.name,
        "with_skill_pass_rate_drop_pp": round(d.with_skill_pass_rate_drop_pp, 2),
        "trigger_f1_drop_pp": round(d.trigger_f1_drop_pp, 2),
        "delta_quality_pp": round(d.delta_quality_pp, 2),
        "noise_floor_pp": round(d.noise_floor_pp, 2),
        "status": "regression" if d.regression else ("warn" if d.warning else "ok"),
    }
    click.echo(json.dumps(out, indent=2))
    sys.exit(2 if d.regression else 0)


@main.command()
@click.option("--skill", required=True)
@click.option("--iteration", "iteration_arg", default=None)
@click.option("--force", is_flag=True, help="Promote even with a dirty worktree.")
@click.pass_context
def promote(ctx: click.Context, skill: str, iteration_arg: str | None, force: bool) -> None:
    """Snapshot a chosen iteration's summary into skills/<skill>/evals/baseline.json."""
    repo_root: Path = ctx.obj["repo_root"]
    if _git_dirty(repo_root) and not force:
        raise click.ClickException(
            "worktree is dirty; commit or stash, or pass --force."
        )
    iteration_dir = _resolve_iteration(repo_root, skill, iteration_arg)
    summary_path = iteration_dir / "summary.json"
    if not summary_path.exists():
        raise click.ClickException(f"no summary.json under {iteration_dir}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    quality = summary.get("quality", {})
    triggers_obj = summary.get("triggers", {})
    if not quality or not triggers_obj:
        raise click.ClickException(
            f"{summary_path}: missing quality/triggers blocks (live runs not yet "
            f"implemented; promote will be functional after Issue #7)."
        )

    n_cases = int(quality["with_skill"]["n_cases"])
    n_trials = int(quality["with_skill"]["n_trials"])
    noise_floor_pp = round(100.0 / max(n_cases * n_trials, 1), 2)

    baseline_obj = {
        "schema_version": 1,
        "skill": skill,
        "established_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "established_by": _git_head(repo_root),
        "source_iteration": str(iteration_dir.relative_to(repo_root)),
        "model": summary.get("model", {}),
        "trials_per_case": n_trials,
        "triggers": triggers_obj,
        "quality": quality,
        "regression_thresholds": {
            "with_skill_pass_rate_drop_pp": 5.0,
            "trigger_f1_drop_pp": 5.0,
            "sustained_runs": 2,
            "noise_floor_pp": noise_floor_pp,
        },
    }
    baseline_obj = relativize_grading(str(iteration_dir), baseline_obj)
    out = repo_root / "skills" / skill / "evals" / "baseline.json"
    out.write_text(json.dumps(baseline_obj, indent=2) + "\n", encoding="utf-8")
    click.echo(f"wrote {out.relative_to(repo_root)}")


def _resolve_iteration(repo_root: Path, skill: str, arg: str | None) -> Path:
    base = repo_root / "evals" / skill
    if arg:
        candidate = (base / arg) if not os.path.isabs(arg) else Path(arg)
        if not candidate.is_dir():
            raise click.ClickException(f"iteration not found: {candidate}")
        return candidate
    if not base.is_dir():
        raise click.ClickException(f"no iterations under {base}")
    iterations = sorted(
        (p for p in base.iterdir() if p.is_dir() and p.name.startswith("iteration-")),
        key=lambda p: int(p.name.split("-", 1)[1]) if p.name.split("-", 1)[1].isdigit() else -1,
    )
    if not iterations:
        raise click.ClickException(f"no iterations under {base}")
    return iterations[-1]


if __name__ == "__main__":
    main()
