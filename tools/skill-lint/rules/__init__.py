"""Auto-discovered lint rules.

Each module in this package that exposes a top-level callable named ``check``
with the signature ``check(skill_dir: Path, repo_root: Path) -> list[Finding]``
is run as a rule.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True)
class Finding:
    rule: str
    skill: str
    severity: str  # "error" | "warn" | "skip"
    message: str
    location: str | None = None  # "path:line" or "path"

    def text_line(self) -> str:
        loc = self.location or self.skill
        return f"[{self.severity}] {self.rule}: {loc}: {self.message}"


RuleFn = Callable[[Path, Path], list[Finding]]


def discover_rules() -> list[tuple[str, RuleFn]]:
    """Return a list of (rule_name, callable) auto-discovered from this package."""
    rules: list[tuple[str, RuleFn]] = []
    package = importlib.import_module(__name__)
    for mod_info in pkgutil.iter_modules(package.__path__):
        if mod_info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{mod_info.name}")
        fn = getattr(mod, "check", None)
        if callable(fn):
            rules.append((mod_info.name, fn))
    rules.sort(key=lambda x: x[0])
    return rules


__all__ = ["Finding", "discover_rules", "RuleFn"]
