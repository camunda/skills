"""Expand eval targets into CI matrix run specs.

Reads the eval registry, optionally narrows by changed skills
(``--changed-skills``) and a target-path substring (``--target``, matched
against the target's path), then expands each outcome eval into a
``with_skill`` arm (plus ``without_skill`` with ``--compare``); triggers stay
single-arm. Emits the specs JSON array the workflow matrix consumes.

    evals-build-matrix [--changed-skills <skill> ...] [--target <substr>] [--compare]
"""

from __future__ import annotations

import argparse
import json

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-skills", nargs="*", default=None)
    parser.add_argument(
        "--target", default="", help="substring matched against the target path"
    )
    parser.add_argument(
        "--compare", action="store_true", help="also emit the without_skill arm"
    )
    args = parser.parse_args()

    targets = discover()
    if args.changed_skills is not None:
        targets = filter_by_changed_skills(targets, args.changed_skills)
    if args.target:
        targets = [t for t in targets if args.target in t.path]

    print(json.dumps(build_specs(targets, args.compare)))


if __name__ == "__main__":
    main()
