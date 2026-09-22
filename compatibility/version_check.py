#!/usr/bin/env python3
"""Assert every plugin manifest carries the same bundle version.

Under the hybrid versioning model the whole `camunda-skills` package ships as
one semantically versioned, pinnable bundle. That single version is duplicated
across four manifests that different harnesses read. `plugin.json` is the source
of truth; this guard fails if any other manifest drifts from it, so a manual
edit or a botched release bump can never publish mismatched versions.

Stdlib-only so it runs anywhere (`python3 compatibility/version_check.py`)
without the project virtualenv.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")

# (manifest path, list of key paths that must equal the source-of-truth version).
# A key path is a sequence of dict keys / list indices from the document root.
SOURCE_OF_TRUTH = ("plugin.json", ("version",))
MANIFESTS: tuple[tuple[str, tuple[tuple[Any, ...], ...]], ...] = (
    ("plugin.json", (("version",),)),
    (".claude-plugin/plugin.json", (("version",),)),
    (
        ".claude-plugin/marketplace.json",
        (("version",), ("plugins", 0, "version")),
    ),
    (
        ".github/plugin/marketplace.json",
        (("metadata", "version"), ("plugins", 0, "version")),
    ),
)


def resolve(document: Any, path: tuple[Any, ...]) -> Any:
    cursor = document
    for part in path:
        if isinstance(part, int):
            if not isinstance(cursor, list) or part >= len(cursor):
                return None
            cursor = cursor[part]
        else:
            if not isinstance(cursor, dict) or part not in cursor:
                return None
            cursor = cursor[part]
    return cursor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parent.parent
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    errors: list[str] = []

    source_file, source_path = SOURCE_OF_TRUTH
    source_doc = json.loads((root / source_file).read_text(encoding="utf-8"))
    canonical = resolve(source_doc, source_path)
    if not isinstance(canonical, str) or not SEMVER.fullmatch(canonical):
        print(
            f"{source_file}.{'.'.join(map(str, source_path))}: "
            f"expected a semantic version, got {canonical!r}",
            file=sys.stderr,
        )
        return 1

    for filename, key_paths in MANIFESTS:
        path = root / filename
        if not path.is_file():
            errors.append(f"{filename}: manifest does not exist")
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        for key_path in key_paths:
            dotted = ".".join(str(part) for part in key_path)
            value = resolve(document, key_path)
            if value is None:
                errors.append(f"{filename}.{dotted}: version field is missing")
            elif value != canonical:
                errors.append(
                    f"{filename}.{dotted}: {value!r} != source-of-truth "
                    f"plugin.json version {canonical!r}"
                )

    if errors:
        print("Version consistency check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"Version consistency check passed: all manifests at {canonical}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
