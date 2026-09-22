#!/usr/bin/env python3
"""Emit the compatibility triple for the current bundle: skills <-> c8ctl <-> Camunda.

The bundle version is a tested triple, not just a tag: a `camunda-skills`
release is validated against a minimum c8ctl and a minimum Camunda version.
Those floors are derived from the per-skill `requires{}` envelopes so they can
never drift from what the skills actually declare. Used by the release workflow
to append a Compatibility section to each GitHub Release's notes, and runnable
locally (`python3 compatibility/compat_matrix.py`).

Stdlib-only so it runs without the project virtualenv.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Tools surfaced in the headline triple, in display order. `requires{}` may
# carry more (node/java/maven/docker/dmnlint); those stay per-skill metadata.
TRIPLE = (("camunda", "Camunda"), ("c8ctl", "c8ctl"))
RANGE = re.compile(r"^(?:>=|>|<=|<|~|\^|=)?(\d+(?:\.\d+){0,2})$")


def floor(version_range: str) -> tuple[int, ...] | None:
    match = RANGE.fullmatch(version_range.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def render(root: Path) -> str:
    bundle = json.loads((root / "plugin.json").read_text(encoding="utf-8"))["version"]
    sidecars = sorted((root / "skills").glob("*/portability.json"))

    # Minimum floor each tool is required at across every skill in the bundle.
    floors: dict[str, tuple[int, ...]] = {}
    for sidecar in sidecars:
        requires = json.loads(sidecar.read_text(encoding="utf-8")).get("requires", {})
        for tool, value in requires.items():
            parsed = floor(value) if isinstance(value, str) else None
            if parsed is None:
                continue
            if tool not in floors or parsed < floors[tool]:
                floors[tool] = parsed

    lines = [
        "### Compatibility",
        "",
        f"`camunda-skills@{bundle}` is validated as a tested triple against these"
        " minimum versions:",
        "",
        "| Component | Minimum version |",
        "| --- | --- |",
        f"| Skills bundle | {bundle} |",
    ]
    for key, label in TRIPLE:
        if key in floors:
            lines.append(f"| {label} | {'.'.join(map(str, floors[key]))} |")
    lines += [
        "",
        "Per-skill dependency envelopes (including any language/tooling floors)"
        " are declared in each skill's `portability.json` under `requires`.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parent.parent
    )
    args = parser.parse_args(argv)
    sys.stdout.write(render(args.root.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
