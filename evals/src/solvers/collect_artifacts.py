"""Solver: snapshot the agent's workspace into the eval log.

Walks a directory in the sandbox (default ``/workspace``) and stores
the contents of every text-like file in ``state.store`` under
``artifacts``. The Inspect log viewer renders this as expandable JSON
so a reviewer can see exactly what the agent produced — BPMN, forms,
DMN, JSON, scripts, anything.

Filters: only files whose extension is in ``EXTENSIONS`` are captured
(the agent shouldn't be writing binaries, but the filter keeps random
``.class`` files or core dumps out of the log). Files larger than
``MAX_BYTES`` are recorded with a placeholder so the log doesn't bloat.

Wire after ``react()`` in a scenario's solver chain:

    solver=[boot_cluster(), react(...), collect_artifacts()]
"""

from __future__ import annotations

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox

# Text-like artifacts the skills produce. Add extensions here when a
# new scenario type introduces a new artifact format.
EXTENSIONS = (
    ".bpmn",
    ".dmn",
    ".form",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".java",
    ".kt",
    ".ts",
    ".js",
    ".py",
    ".md",
    ".txt",
    ".properties",
    ".feel",
)

# Per-file cap so a runaway file doesn't bloat the log. 256 KiB is
# generous for any hand-authored BPMN/DMN/form.
MAX_BYTES = 256 * 1024


@solver
def collect_artifacts(root: str = "/workspace") -> Solver:
    """Snapshot text-like artifacts under ``root`` into state.store["artifacts"]."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()

        # -printf would be tidier but isn't portable across find
        # variants — use null delimiters so spaces in paths are safe.
        # Exclude:
        #   - dotfile dirs
        #   - the skill() tool's planted skill contents under
        #     /workspace/skills/, which would otherwise drown the
        #     agent's own artifacts in the log
        find = await sb.exec(
            [
                "find",
                root,
                "-type", "f",
                "-not", "-path", "*/.*",
                "-not", "-path", f"{root.rstrip('/')}/skills/*",
                "-print0",
            ],
            timeout=30,
        )
        if find.returncode != 0:
            state.store.set(
                "artifacts",
                {"_error": f"find exit {find.returncode}: {find.stderr[-300:]}"},
            )
            return state

        paths = [p for p in find.stdout.split("\0") if p]
        artifacts: dict[str, str] = {}
        for path in paths:
            if not path.lower().endswith(EXTENSIONS):
                continue

            # Cheap size check first, then read.
            size_probe = await sb.exec(["wc", "-c", path], timeout=10)
            try:
                size = int((size_probe.stdout or "0").split()[0])
            except (ValueError, IndexError):
                size = -1

            if size > MAX_BYTES:
                artifacts[path] = f"<skipped: {size} bytes exceeds {MAX_BYTES}>"
                continue

            try:
                artifacts[path] = await sb.read_file(path, text=True)
            except Exception as exc:
                artifacts[path] = f"<read failed: {exc}>"

        state.store.set("artifacts", artifacts)
        return state

    return solve
