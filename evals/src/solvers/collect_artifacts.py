"""Solver: snapshot the agent's text-like workspace files into the eval log.

``with_artifact_collection(agent)`` is preferred over a bare downstream
``collect_artifacts()``: Inspect aborts the solver chain on a sample
limit, so the bare collector is skipped exactly when visibility matters.
"""

from __future__ import annotations

from inspect_ai.agent import Agent, as_solver
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox

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

MAX_BYTES = 256 * 1024


@solver
def collect_artifacts(root: str = "/workspace") -> Solver:
    """Snapshot text-like artifacts under ``root`` into state.store["artifacts"]."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()

        # -print0 (not -printf) for find portability; spaces in paths safe.
        # Exclude dotfile dirs and the skill() tool's plants under
        # /workspace/skills/ (they'd drown the agent's own artifacts).
        find = await sb.exec(
            [
                "find",
                root,
                "-type",
                "f",
                "-not",
                "-path",
                "*/.*",
                "-not",
                "-path",
                f"{root.rstrip('/')}/skills/*",
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


@solver
def with_artifact_collection(agent: Agent, root: str = "/workspace") -> Solver:
    """Wrap an Inspect agent so artifact collection runs whatever happens.

    Runs the agent inside ``try/finally`` so the snapshot fires on clean
    submit, sample-limit, or exception (which propagates after cleanup).
    """
    agent_solver = as_solver(agent)
    cleanup = collect_artifacts(root=root)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        try:
            state = await agent_solver(state, generate)
        finally:
            state = await cleanup(state, generate)
        return state

    return solve
