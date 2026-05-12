"""Forbid references/x.md -> references/y.md chains within the same skill.

Progressive disclosure means SKILL.md points to references; a reference
should not redirect the reader further into another reference. This catches
accidental chains that would force the agent to load multiple files.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import Finding

LINK_RE = re.compile(r"\]\(([^)]+)\)")


def check(skill_dir: Path, repo_root: Path) -> list[Finding]:
    refs_dir = skill_dir / "references"
    if not refs_dir.is_dir():
        return []
    findings: list[Finding] = []
    for ref in sorted(refs_dir.glob("*.md")):
        text = ref.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in LINK_RE.finditer(line):
                target = match.group(1).split("#", 1)[0].strip()
                if not target or target.startswith(("http://", "https://", "mailto:")):
                    continue
                # Resolve against the reference's directory.
                resolved = (ref.parent / target).resolve()
                try:
                    rel = resolved.relative_to(refs_dir.resolve())
                except ValueError:
                    continue
                if rel.suffix == ".md":
                    findings.append(
                        Finding(
                            rule="references_depth",
                            skill=skill_dir.name,
                            severity="error",
                            message=(
                                f"reference links to another reference "
                                f"({target}); avoid chains"
                            ),
                            location=f"{ref.relative_to(repo_root)}:{lineno}",
                        )
                    )
    return findings
