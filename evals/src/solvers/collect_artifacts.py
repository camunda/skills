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

Two ways to wire it in:

- ``with_artifact_collection(agent)`` — wraps an Inspect agent
  (``react``, ``claude_code_agent``, any ``@agent`` function) so
  collection runs in a ``try/finally`` regardless of how the agent
  exits (clean submit, limit-hit, exception). Preferred — Inspect
  aborts the solver chain on a sample limit, so a plain downstream
  ``collect_artifacts()`` is skipped precisely when we most need
  visibility (the run that went sideways).

- ``collect_artifacts()`` — bare solver, chained after the agent.
  Only runs when the agent exits cleanly without hitting a limit.

    # Preferred — wrap the agent
    solver=[boot_cluster(), with_artifact_collection(react(...))]

    # Bare — only runs on clean exits
    solver=[boot_cluster(), react(...), collect_artifacts()]
"""

from __future__ import annotations

from inspect_ai.agent import Agent, as_solver
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


@solver
def with_artifact_collection(
    agent: Agent, root: str = "/workspace"
) -> Solver:
    """Wrap an Inspect agent so artifact collection runs whatever happens.

    Inspect aborts the solver chain when a sample limit (token,
    message, time) is hit during a solver. A downstream
    ``collect_artifacts()`` is then skipped — which is the worst time
    to lose visibility, because limit-hit runs are exactly the runs
    you want to inspect.

    This converts the agent to a Solver (via ``as_solver``) and runs
    it inside ``try/finally`` so the artifact snapshot fires
    regardless of how it exits: clean submit, sample-limit, or raised
    exception. The exception (if any) propagates after cleanup, so
    Inspect's downstream scoring + log bookkeeping still see the
    failure.

    Agent-agnostic by design — works with ``react(...)``,
    ``inspect_swe.claude_code_agent(...)``, or any ``@agent``
    function.
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
