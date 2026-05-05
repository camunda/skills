# Eval Runner — Maintenance Notes

For contributors changing the runner. The user-facing surface is the Makefile
targets (`make eval-triggers`, `make eval-quality`, `make compare`,
`make promote`); see the root `CLAUDE.md` and `CONTRIBUTING.md`.

## What the runner is

A Python harness that runs paired with_skill / without_skill evals on
Camunda skills, plus a trigger-rate eval over positive + negative probes.
Outputs an iteration directory under `evals/<skill>/iteration-N/` containing
`summary.json`, per-trial `outputs/`, `grading.json`, `timing.json`, and a
self-contained `report.html`.

## Architecture

Three layers, distinct on purpose:

```
Tier 1 — trigger eval        Tier 2 — quality eval         Tier 2 — verifiers
─────────────────────        ──────────────────────        ──────────────────
trigger_eval.py              quality_eval.py               verifiers/<type>.py
  │                            │                             │
  └─ subprocess →              ├─ claude_agent_sdk.query()   └─ shells out to e.g.
     run_eval.py               │     ⇒ with_skill arm           c8 feel evaluate
     (THEIR code,              │     ⇒ without_skill arm        (post-grading)
     SHA-pinned)               │     captures ToolUseBlocks
                               │
                               └─ anthropic.messages.create()
                                     system = grader.md (THEIR text,
                                     SHA-pinned, read at runtime)
                                     ⇒ writes grading.json
```

Three external dependencies, kept on different update cadences:

| Dependency | Where pinned | Update cadence |
|---|---|---|
| `anthropics/skills` clone (`run_eval.py` + `grader.md`) | `tools/eval-runner/.skill-creator-sha` | Manual, deliberate, own PR |
| `claude-agent-sdk` (PyPI) | `tools/eval-runner/pyproject.toml` | When new tool-use semantics ship |
| `anthropic` (PyPI) | `tools/eval-runner/pyproject.toml` | Standard dep bump |

## SHA pin: how to update upstream `anthropics/skills`

The `run_eval.py` CLI and `grader.md` system prompt are read from a
SHA-pinned shallow clone at `tools/external/anthropics-skills/`. The SHA
lives in `tools/eval-runner/.skill-creator-sha`. We do NOT vendor copies
of the upstream files — the clone is the single source of truth, gitignored
because the SHA pin already locks the version.

**To bump:**

1. Inspect what's changed upstream:
   ```sh
   git -C tools/external/anthropics-skills fetch origin
   git -C tools/external/anthropics-skills log --oneline \
     $(cat tools/eval-runner/.skill-creator-sha)..origin/main \
     -- skills/skill-creator/scripts/run_eval.py skills/skill-creator/agents/grader.md
   ```
2. Pick a target SHA (typically `origin/main`'s tip, but pin to a specific
   SHA — never a branch name). Eyeball the diffs of `run_eval.py` and
   `grader.md` between old and new — those are the only two files we
   actually consume. Other changes upstream are irrelevant to us.
3. Update the pin file:
   ```sh
   echo <new-sha> > tools/eval-runner/.skill-creator-sha
   ```
4. Re-create the clone at the new SHA and verify:
   ```sh
   make setup-skill-creator
   make verify-skill-creator
   ```
5. Smoke-test:
   ```sh
   make eval-triggers SKILL=camunda-feel
   ```
   Expect F1 to be roughly stable. Big swings (>5pp) usually mean a behavior
   change in `run_eval.py` worth understanding before merging.
6. Commit `.skill-creator-sha` as its own PR. The PR description should
   include the upstream `git log` output from step 1 so reviewers can see
   what's coming in.

**Future migration to git submodule**: ~5 file diff (add `.gitmodules`,
remove `.skill-creator-sha` + `setup-skill-creator` target, untrack the
external dir from `.gitignore`, update CI checkout to `submodules:
recursive`, swap one paragraph in this file). Harness code unchanged.

## Run-eval.py invocation contract

`tools/eval-runner/trigger_eval.py` shells out to:

```
python tools/external/anthropics-skills/skills/skill-creator/scripts/run_eval.py \
    --eval-set <converted-from-triggers.json> \
    --skill-path skills/<skill-name> \
    --runs-per-query <RUNS> \
    --num-workers <N> \
    --model <id>
```

Stdout: a single pretty-printed JSON object (NOT NDJSON):
```jsonc
{
  "skill_name": "...",
  "description": "...",
  "results": [
    {"query": "...", "should_trigger": true|false,
     "trigger_rate": 0.66, "triggers": 2, "runs": 3, "pass": true}
  ],
  "summary": {"total": N, "passed": N, "failed": N}
}
```

We project this into our `summary.json` shape (per-case hits/misses,
aggregate F1/precision/recall computed from `should_trigger`/`pass` pairs).

Side effects we tolerate:
- Writes a temp slash-command file to `<project_root>/.claude/commands/`
  during the run, deletes it in a `finally`. Our repo has `.claude/` so
  this is fine — but the harness should run from the repo root, not from
  a subdir, so `find_project_root()` finds the right one.
- Concurrency uses `ProcessPoolExecutor`; runs are non-deterministic in
  order but the aggregated F1 is stable.

If `run_eval.py`'s output shape changes upstream, update the projection
in `trigger_eval.py` and bump the comment header citing the new SHA.

## Quality eval — claude-agent-sdk specifics

`quality_eval.py` drives the with_skill / without_skill arms via
`claude_agent_sdk.query()`. Per-arm setup:

| Concern | Mechanism |
|---|---|
| Skill availability | `ClaudeAgentOptions.add_dirs=[<allowed skills root>]` — for `without_skill`, point at a temp dir that excludes the target skill but still includes its siblings (matches plugin-install reality where ALL skills are present, but we're asking what happens when the agent decides not to load this one). |
| Output capture | Each trial gets a fresh `outputs/` dir under `add_dirs`; the agent writes there via Bash/Write. We read it back after `query()` returns. |
| Skill-load detection | Iterate `AssistantMessage.content` blocks; collect `ToolUseBlock`s. A `Skill` tool call (`block.name == "Skill"`, `block.input.skill = "<name>"`) is the primary signal; a `Read` of any `SKILL.md` path is the fallback. Both are captured in `summary.json` under `loaded_skills.{via_skill_tool, via_read}` so we can monitor whether the fallback ever fires. |
| Model pinning | `ClaudeAgentOptions.model="claude-opus-4-7"` for the harness arm; the grader call uses Sonnet via the plain Anthropic SDK in a separate request. |
| Cost cap | `ClaudeAgentOptions` exposes `max_budget_usd` indirectly via `extra_args`; we also enforce a hard ceiling at the runner level (`--max-usd`). |

## Grader call — plain Anthropic SDK

Grading is a single non-tool-using completion call. We deliberately do NOT
use the agent SDK for this — there's no tool use, no async iteration, just
"system prompt + user input → JSON out". `quality_eval.py` reads
`agents/grader.md` from the SHA-pinned clone at runtime (not at import
time, so a `make setup-skill-creator` rerun is picked up without
restarting the harness) and passes it as the `system` parameter. The user
message is a small JSON payload referencing the trial's transcript and
outputs dir, exactly as the grader prompt expects.

The grader writes `grading.json` matching the schema in
`anthropics/skills/.../skills/skill-creator/references/schemas.md`. That
schema also matches what `report.py` already renders — no adapter needed.

## What this code is NOT

- **Not a skill-creator wrapper.** We reuse two of skill-creator's files
  (`run_eval.py`, `grader.md`) and reimplement the rest (with_skill /
  without_skill orchestration, paired aggregation, `summary.json` shape).
  The "Inner-loop tool: skill-creator" framing in earlier plan drafts was
  misleading — see `Inner-loop tool` row in the plan's decisions table.
- **Not a multi-model runner.** Anthropic-only. Cross-agent matrix is
  deferred (see plan's "Future / explicitly deferred" section).
- **Not a CPT-based BPMN behavioral verifier.** Tier-2 quality verifiers
  are layer-1 (parse) and layer-3 (output match) only. Behavioral testing
  of running BPMN processes is deferred to a later iteration.
