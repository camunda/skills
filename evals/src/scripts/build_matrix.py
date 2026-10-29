"""Expand eval targets into CI matrix run specs.

Reads the eval registry, optionally narrows by changed skills
(``--changed-skills``) and a target-path substring (``--target``, matched
against the target's path), then expands each outcome eval into a
``with_skill`` arm (plus ``without_skill`` with ``--compare``); triggers stay
single-arm. Emits the specs JSON array the workflow matrix consumes.

``--models a,b,c`` switches to the model-comparison shape used by
``eval-models.yml``: outcome evals only, ``with_skill`` only, run through the
GitHub Copilot CLI agent (``-T agent=copilot_cli``), one entry per target ×
Copilot model id (each carrying a ``model`` field), with ``--epochs N`` folded
into the run flags.

    evals-build-matrix [--changed-skills <skill> ...] [--target <substr>] [--compare]
    evals-build-matrix --models <m1,m2,...> [--epochs N] [--target <substr>]
"""

from __future__ import annotations

import argparse
import json
import re

from core.registry import EvalTarget, discover, filter_by_changed_skills


def _spec_ref(target: EvalTarget) -> str:
    return target.path + (f"@{target.task}" if target.task else "")


def _base_targs(target: EvalTarget) -> str:
    return " ".join(f"-T {k}={v}" for k, v in (target.args or {}).items())


def build_specs(targets: list[EvalTarget], compare: bool) -> list[dict]:
    """One matrix entry per arm.

    Triggers are sandbox-free single-shot routing calls (samples run in
    parallel). Outcome evals run one sandbox per sample (= a Camunda cluster),
    so concurrency is capped from the target's ``max_sandboxes`` — passed as both
    ``--max-sandboxes`` AND ``--max-samples`` (Inspect's ``max_samples`` defaults
    to 1, so without the latter samples run serially however many sandboxes are
    allowed; cluster targets keep this at 1, judge-only targets parallelize).
    They run ``with_skill`` plus ``without_skill`` when ``compare``.
    """
    specs: list[dict] = []
    for t in targets:
        slug = t.id.replace(":", "-")
        spec = _spec_ref(t)
        base_targs = _base_targs(t)
        if t.kind == "trigger":
            specs.append(
                {
                    "slug": slug,
                    "label": t.id,
                    "spec": spec,
                    "targs": base_targs,
                    "arm": "",
                    "sandbox": False,
                    "limit": "--max-samples 10",
                    "display": "plain",
                }
            )
            continue
        for arm in ["with_skill"] + (["without_skill"] if compare else []):
            specs.append(
                {
                    "slug": f"{slug}-{arm}",
                    "label": f"{t.id} [{arm}]",
                    "spec": spec,
                    "targs": f"-T agent=react -T arm={arm} {base_targs}".strip(),
                    "arm": arm,
                    "sandbox": True,
                    "limit": f"--max-sandboxes {t.max_sandboxes} --max-samples {t.max_sandboxes}",
                    "display": "conversation",
                }
            )
    return specs


# Per-job concurrent Copilot sessions in model-comparison mode.
MODEL_MAX_SANDBOXES = 4


def _model_slug(model: str) -> str:
    """Artifact-name-safe form of a model id (``anthropic/claude-x`` → ``anthropic-claude-x``)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-")


def parse_models(raw: str) -> list[str]:
    """Split a comma/whitespace-separated model list, dropping blanks and dupes."""
    seen: list[str] = []
    for m in re.split(r"[,\s]+", raw or ""):
        if m and m not in seen:
            seen.append(m)
    return seen


def build_model_specs(
    targets: list[EvalTarget], models: list[str], epochs: int
) -> list[dict]:
    """One entry per outcome target × Copilot model, ``with_skill`` arm only.

    Triggers are skipped (routing isn't what the model comparison measures).
    ``model`` is a Copilot CLI model id (``copilot --model``), exported to the
    agent as ``COPILOT_MODEL`` — not an Inspect ``--model``.
    Concurrency mirrors ``build_specs`` but is capped at
    ``MODEL_MAX_SANDBOXES`` — each sandbox is a live Copilot session, and the
    workflow runs several jobs at once. ``--epochs`` rides in ``limit`` so the
    workflow's run step stays a straight substitution.
    """
    specs: list[dict] = []
    for t in targets:
        if t.kind == "trigger":
            continue
        slug = t.id.replace(":", "-")
        base_targs = _base_targs(t)
        n = min(t.max_sandboxes, MODEL_MAX_SANDBOXES)
        for model in models:
            specs.append(
                {
                    "slug": f"{slug}-{_model_slug(model)}",
                    "label": f"{t.id} [{model}]",
                    "spec": _spec_ref(t),
                    "targs": (
                        f"-T agent=copilot_cli -T arm=with_skill {base_targs}"
                    ).strip(),
                    "arm": "with_skill",
                    "model": model,
                    "sandbox": True,
                    "limit": (
                        f"--max-sandboxes {n} --max-samples {n} --epochs {epochs}"
                    ),
                    "display": "plain",
                }
            )
    return specs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-skills", nargs="*", default=None)
    parser.add_argument(
        "--target", default="", help="substring matched against the target path"
    )
    parser.add_argument(
        "--compare", action="store_true", help="also emit the without_skill arm"
    )
    parser.add_argument(
        "--models",
        default=None,
        help="comma-separated Copilot CLI model ids; emits the model-comparison matrix",
    )
    parser.add_argument(
        "--epochs", type=int, default=1, help="epochs per sample (with --models)"
    )
    args = parser.parse_args()

    targets = discover()
    if args.changed_skills is not None:
        targets = filter_by_changed_skills(targets, args.changed_skills)
    if args.target:
        targets = [t for t in targets if args.target in t.path]

    if args.models is not None:
        models = parse_models(args.models)
        if not models:
            parser.error("--models is empty")
        if args.epochs < 1:
            parser.error("--epochs must be >= 1")
        print(json.dumps(build_model_specs(targets, models, args.epochs)))
        return

    print(json.dumps(build_specs(targets, args.compare)))


if __name__ == "__main__":
    main()
