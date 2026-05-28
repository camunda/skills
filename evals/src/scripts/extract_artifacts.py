"""Extract agent artifacts from an eval log to local disk.

After ``make eval`` finishes, each sample's ``store.artifacts`` dict
holds the text files the agent produced (BPMN, forms, DMN, etc.) —
populated by the ``collect_artifacts()`` solver. This script writes
those out as real files so you can open them in Camunda Modeler.

Default behaviour: extract the most recent ``.eval`` log under
``logs/`` to ``logs/artifacts/<eval-stem>/<sample-id>/<path>``.

CLI:
    evals-extract-artifacts              # latest log, default output dir
    evals-extract-artifacts <log-file>   # specific log file
    evals-extract-artifacts --output DIR # custom output root
    evals-extract-artifacts --quiet      # suppress per-file output

The chosen output dir is printed to stdout last for shell-piping
(``open "$(evals-extract-artifacts --quiet)"``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

from inspect_ai.log import EvalLog, list_eval_logs, read_eval_log

from core.paths import EVALS_ROOT


DEFAULT_LOG_DIR = EVALS_ROOT / "logs"
DEFAULT_OUTPUT_ROOT = DEFAULT_LOG_DIR / "artifacts"

# Filename-character allowlist for sample IDs; anything else becomes "_".
_SAFE_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_."
)


def _log_info_path(info) -> Path:
    """``list_eval_logs`` returns EvalLogInfo objects whose ``name`` is a
    ``file://...`` URI. Extract a real local Path."""
    name = getattr(info, "name", None) or str(info)
    parsed = urlparse(name)
    return Path(parsed.path if parsed.scheme == "file" else name)


def _latest_log(log_dir: Path) -> Path | None:
    candidates = list_eval_logs(str(log_dir))
    if not candidates:
        return None
    paths = [_log_info_path(c) for c in candidates]
    # list_eval_logs sorts newest first, but be defensive.
    return sorted(paths, key=lambda p: p.stat().st_mtime)[-1]


def _safe(name: str) -> str:
    return "".join(c if c in _SAFE_CHARS else "_" for c in name)


def _relative_path(stored_path: str) -> Path:
    """Map an in-sandbox path like ``/workspace/sub/foo.bpmn`` to a
    repo-relative path ``sub/foo.bpmn``. Falls back to using the
    basename if the path isn't under ``/workspace``."""
    p = Path(stored_path)
    parts = p.parts
    if len(parts) > 2 and parts[1] == "workspace":
        return Path(*parts[2:])
    return Path(p.name)


def extract(log_path: Path, output_root: Path, quiet: bool = False) -> Path:
    log: EvalLog = read_eval_log(str(log_path))
    target_dir = output_root / log_path.stem
    target_dir.mkdir(parents=True, exist_ok=True)

    total_files = 0
    samples = getattr(log, "samples", None) or []
    for sample in samples:
        sample_id = _safe(str(getattr(sample, "id", "unknown")))
        store = getattr(sample, "store", None) or {}
        # Inspect's Store can be dict-like or attribute-style; both
        # support .get / __getitem__.
        artifacts = (
            store.get("artifacts") if hasattr(store, "get") else None
        ) or {}

        if not artifacts:
            continue

        sample_dir = target_dir / sample_id
        sample_dir.mkdir(parents=True, exist_ok=True)

        for stored_path, content in artifacts.items():
            rel = _relative_path(stored_path)
            out = sample_dir / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, str):
                out.write_text(content)
            else:
                # Placeholder values like "<skipped: ...>" come through
                # as strings; non-string is defensive.
                out.write_text(str(content))
            total_files += 1
            if not quiet:
                print(f"  {out.relative_to(EVALS_ROOT)}", file=sys.stderr)

    if not quiet:
        print(
            f"Extracted {total_files} file(s) to {target_dir.relative_to(EVALS_ROOT)}",
            file=sys.stderr,
        )
    return target_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "log",
        type=Path,
        nargs="?",
        help="Path to a .eval log file (default: most recent under logs/)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=f"Output root directory (default: {DEFAULT_OUTPUT_ROOT})",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=DEFAULT_LOG_DIR,
        help="When `log` is omitted, search this directory for the most recent log.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-file progress on stderr.",
    )
    args = parser.parse_args()

    log_path = args.log
    if log_path is None:
        log_path = _latest_log(args.log_dir)
        if log_path is None:
            sys.exit(f"no .eval logs found under {args.log_dir}")
    if not log_path.exists():
        sys.exit(f"log file not found: {log_path}")

    target = extract(log_path, args.output, quiet=args.quiet)
    # Final line on stdout for piping (e.g. `open "$(evals-extract-artifacts -q)"`).
    print(target)


if __name__ == "__main__":
    main()
