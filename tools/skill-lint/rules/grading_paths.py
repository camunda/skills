"""Defense in depth: refuse absolute machine paths committed under skills/<name>/evals/.

The eval-runner relativizes grading.json output, but we also guard at lint
time so a mistake in the runner can't silently leak machine-local paths into
the repo.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import Finding

ABS_PATTERNS = [
    re.compile(r"/home/[^\s\"']+"),
    re.compile(r"/Users/[^\s\"']+"),
    re.compile(r"[A-Za-z]:\\\\[^\s\"']+"),
]


def check(skill_dir: Path, repo_root: Path) -> list[Finding]:
    evals_dir = skill_dir / "evals"
    if not evals_dir.is_dir():
        return []
    findings: list[Finding] = []
    for path in sorted(evals_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in (".json", ".md", ".txt"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pat in ABS_PATTERNS:
                if pat.search(line):
                    findings.append(
                        Finding(
                            rule="grading_paths",
                            skill=skill_dir.name,
                            severity="error",
                            message="absolute machine path leaked into committed eval data",
                            location=f"{path.relative_to(repo_root)}:{lineno}",
                        )
                    )
                    break
    return findings
