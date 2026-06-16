"""Scorer: assert the agent's Node.js worker is genuinely zero-dependency.

The ``worker-http-no-sdk.md`` sample is the unit under test: a worker that
uses only Node built-ins over the ``/v2/jobs/*`` REST API — no ``package.json``,
no ``node_modules``, no ``@camunda8`` SDK. This scorer checks that property
statically; the CPT verifier checks that the worker actually completes a job.

Excludes the ``skill()`` tool's plants under ``workspace/skills/``.
"""

from __future__ import annotations

import re

from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

# Node built-in modules a zero-dependency worker may import. A bare or
# ``node:``-prefixed specifier resolving to one of these needs no install.
_NODE_BUILTINS = {
    "http",
    "https",
    "http2",
    "url",
    "buffer",
    "crypto",
    "util",
    "stream",
    "events",
    "process",
    "timers",
    "timers/promises",
    "net",
    "tls",
    "zlib",
    "querystring",
    "assert",
    "fs",
    "path",
    "os",
}

# require('x') or require("x"), and ESM import ... from 'x'.
_REQUIRE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")
_IMPORT_FROM = re.compile(r"""import\s+(?:.+?\s+from\s+)?['"]([^'"]+)['"]""")


def _is_builtin(spec: str) -> bool:
    # Relative/absolute paths are first-party, not dependencies.
    if spec.startswith(".") or spec.startswith("/"):
        return True
    name = spec[len("node:") :] if spec.startswith("node:") else spec
    return name in _NODE_BUILTINS


@scorer(metrics=[mean(), stderr()])
def worker_is_zero_dependency(workspace: str = "/workspace") -> Scorer:
    """Score 1.0 when the worker uses only Node built-ins and pulls in no npm.

    Fails (0.0) if a ``package.json`` or ``node_modules`` directory is present
    under ``workspace``, or if any JS file (``.js``/``.mjs``/``.cjs``) imports
    a non-built-in module.
    """

    async def score(state: TaskState, target: Target) -> Score:
        sb = sandbox()
        ws = workspace.rstrip("/")
        skills_dir = f"{ws}/skills"

        # 1. No package.json / node_modules anywhere in the agent's workspace.
        # Prune the skill() plant tree (don't descend it) and search at any
        # depth — a deep node_modules must not slip past as a false pass.
        manifest = await sb.exec(
            [
                "find",
                ws,
                "-path",
                skills_dir,
                "-prune",
                "-o",
                "(",
                "-name",
                "package.json",
                "-o",
                "-name",
                "node_modules",
                ")",
                "-print",
            ],
            timeout=10,
        )
        offenders = [p for p in (manifest.stdout or "").splitlines() if p]
        if offenders:
            return Score(
                value=0.0,
                explanation=(
                    "not zero-dependency — found npm manifest/install: "
                    + ", ".join(offenders)
                ),
                metadata={"npm_artifacts": offenders},
            )

        # 2. Collect the agent's JS files (excluding skill plants). Match
        # .js/.mjs/.cjs at any depth; a worker may legitimately be an ES
        # module (.mjs) or be nested below the workspace root.
        find = await sb.exec(
            [
                "find",
                ws,
                "-path",
                skills_dir,
                "-prune",
                "-o",
                "(",
                "-name",
                "*.js",
                "-o",
                "-name",
                "*.mjs",
                "-o",
                "-name",
                "*.cjs",
                ")",
                "-print",
            ],
            timeout=10,
        )
        js_paths = [p for p in (find.stdout or "").splitlines() if p]
        if not js_paths:
            return Score(
                value=0.0,
                explanation=f"no JS worker (.js/.mjs/.cjs) found under {workspace}",
            )

        # 3. Every import must resolve to a Node built-in or a local path.
        bad: dict[str, list[str]] = {}
        for path in js_paths:
            try:
                src = await sb.read_file(path, text=True)
            except Exception as exc:  # noqa: BLE001 - surface as a soft skip
                bad[path] = [f"<read failed: {exc}>"]
                continue
            specs = _REQUIRE.findall(src) + _IMPORT_FROM.findall(src)
            non_builtin = sorted({s for s in specs if not _is_builtin(s)})
            if non_builtin:
                bad[path] = non_builtin

        if bad:
            first = next(iter(bad))
            return Score(
                value=0.0,
                explanation=(
                    f"worker imports non-built-in module(s); first offender "
                    f"{first}: {bad[first]}"
                ),
                metadata={"non_builtin_imports": bad},
            )

        return Score(
            value=1.0,
            explanation=(
                f"zero-dependency: {len(js_paths)} JS file(s) import only "
                "Node built-ins, no package.json/node_modules"
            ),
            metadata={"js_files": js_paths},
        )

    return score
