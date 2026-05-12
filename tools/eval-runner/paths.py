"""Relativize machine-local paths in grading/summary JSON before persisting.

Background: skill-creator's grading.json contains absolute filesystem paths
that point inside the iteration workspace. Those leak machine identity (e.g.
``/home/<user>/...``) and break path-aware viewers when committed or shared.
This module rewrites any string that begins with the workspace root so the
path becomes relative to the workspace.

The transformation is in-place over a JSON-shaped Python object (dict/list/
scalar mix) and walks all strings recursively.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _normalize(p: str | os.PathLike[str]) -> str:
    """Normalize a path-like value for prefix comparison."""
    return os.path.normpath(str(p))


def relativize_grading(workspace_root: str | os.PathLike[str], obj: Any) -> Any:
    """Rewrite strings starting with ``workspace_root`` to be relative.

    Returns the transformed object. Non-string scalars and unrelated strings
    are returned unchanged. Dict/list containers are walked recursively.

    Examples:
        >>> relativize_grading("/work/it-7", {"path": "/work/it-7/grading.json"})
        {'path': 'grading.json'}
        >>> relativize_grading("/work/it-7", "C:\\\\unrelated")
        'C:\\\\unrelated'
    """
    root = _normalize(workspace_root)
    root_with_sep = root + os.sep
    # Also accept POSIX separator on Windows callers passing in mixed paths.
    alt_sep = root + "/"

    def _walk(node: Any) -> Any:
        if isinstance(node, str):
            return _rewrite(node)
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(v) for v in node]
        if isinstance(node, tuple):
            return tuple(_walk(v) for v in node)
        return node

    def _rewrite(s: str) -> str:
        norm = os.path.normpath(s) if (os.sep in s or "/" in s) else s
        if norm == root:
            return ""
        if norm.startswith(root_with_sep):
            return norm[len(root_with_sep):]
        if alt_sep != root_with_sep and norm.startswith(alt_sep):
            return norm[len(alt_sep):]
        return s

    return _walk(obj)


def is_machine_path(s: str) -> bool:
    """Quick heuristic to flag absolute machine paths in committed data."""
    if not isinstance(s, str):
        return False
    if s.startswith(("/home/", "/Users/")):
        return True
    if len(s) >= 3 and s[1:3] == ":\\" and s[0].isalpha():
        return True
    return False
