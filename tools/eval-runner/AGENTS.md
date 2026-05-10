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
Tier 1 — trigger eval         Tier 2 — quality eval               Tier 2 — verifiers
─────────────────────         ──────────────────────              ──────────────────
trigger_eval.py               quality_eval.py + sdk_runner.py     verifiers/<type>.py
  │                             │                                   │
  └─ subprocess →               ├─ run_arm()                        └─ post-grading,
     run_eval.py                │     claude_agent_sdk.query()         shells out to
     (THEIR code,               │     ⇒ with_skill arm                 e.g. c8 feel
     SHA-pinned)                │     ⇒ without_skill arm              evaluate or
                                │     captures ToolUseBlocks           c8 bpmn lint
                                │     runs in isolated_workdir         --quiet
                                │     under /tmp
                                │
                                └─ run_grader()
                                      claude_agent_sdk.query()
                                      tools=["Read","Write"] only
                                      system = grader.md (THEIR
                                      text, SHA-pinned, read
                                      at runtime); the grader
                                      itself writes grading.json
```

Three external dependencies, kept on different update cadences:

| Dependency | Where pinned | Update cadence |
|---|---|---|
| `anthropics/skills` clone (`run_eval.py` + `grader.md`) | `tools/eval-runner/.skill-creator-sha` | Manual, deliberate, own PR |
| `claude-agent-sdk` (PyPI) | `tools/eval-runner/pyproject.toml` | When new tool-use semantics ship |

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

`quality_eval.py` orchestrates cases × arms × trials and dispatches each
unit of work to `sdk_runner.run_arm()`. Per-arm setup:

| Concern | Mechanism |
|---|---|
| Skill availability | `ClaudeAgentOptions.skills=[…]` — the SDK's native filter. For `with_skill`, the list is every skill discovered under the project setting source; for `without_skill`, the target is removed from that list. Sibling skills remain available, matching plugin-install reality (where all skills are present and the agent decides which to load). |
| Skill discovery | `isolated_workdir()` symlinks `<tmp>/.claude/skills/<name>` -> `<repo>/skills/<name>` for every name in `skills=[…]`. Claude Code's project setting source walks up from cwd looking for `.claude/skills/`; the symlinks bridge our `skills/<name>/` source-of-truth into that canonical location without changing the on-disk layout. |
| Sandbox boundary | `cwd` is set to a fresh `/tmp/eval-trial-*` dir per trial, NOT the repo root. Reason: with `permission_mode="bypassPermissions"` (required for non-interactive runs) the agent can ignore `add_dirs` and write absolute paths anywhere. Confining cwd to /tmp bounds the blast radius. After the run, `<tmp>/outputs/*` is copied back into the trial's persistent dir. The repo's `examples/` is symlinked into `<tmp>/examples` so prompts that reference relative paths there resolve correctly. |
| Output capture | Each trial pre-creates `<tmp>/outputs/` so the agent doesn't have to mkdir. Prompts instruct the agent to write to `outputs/<filename>` (e.g. `outputs/answer.feel`, `outputs/process.bpmn`). The runner copies that directory back into the persistent trial dir before the temp dir is cleaned. |
| Skill-load detection | Iterate `AssistantMessage.content` blocks; collect `ToolUseBlock`s. A `Skill` tool call (`block.name == "Skill"`, `block.input.skill = "<name>"`) is the primary signal; a `Read` of any `SKILL.md` path is the fallback. Both are captured in `summary.json` under `trials[].skill_loads.{via_skill_tool, via_read}` so we can monitor whether the fallback ever fires. |
| Model pinning | `ClaudeAgentOptions.model="claude-opus-4-7"` for the harness arm; the grader uses `claude-sonnet-4-6` via a separate `query()` call (see "Grader" below). |
| Sandbox env | `env={"IS_SANDBOX": "1"}` — Claude Code refuses `--dangerously-skip-permissions` when running as root unless this is set. CI typically runs as root inside containers. |
| Cost cap | `ClaudeAgentOptions.max_budget_usd` per query; defaults `--arm-max-usd=1.0`, `--grader-max-usd=0.5`. Plus a `--max-usd` runner-level guard for the whole invocation. |

## Grader — also runs through claude-agent-sdk

Earlier drafts of this file claimed grading went through plain
`anthropic.messages.create()`. That was misleading: the grader prompt
(`agents/grader.md`) is designed as a tool-using agent — it Reads the
trial transcript and outputs dir and Writes `grading.json` itself. A
single non-tool completion call can't satisfy that contract.

`sdk_runner.run_grader()` runs through `claude_agent_sdk.query()` with a
restricted tool set:

  - `tools=["Read", "Write"]`, `allowed_tools=["Read", "Write"]` — no
    Bash, no Skill, nothing else. Defense in depth.
  - `setting_sources=[]` — isolation mode; the grader sees only its own
    system prompt, not project CLAUDE.md or settings.
  - `system_prompt = <grader.md text read at runtime from the SHA-pinned
    clone>` — a `make setup-skill-creator` rerun is picked up without
    restarting the harness.
  - User message: a small JSON payload with `expectations[]`,
    `transcript_path`, `outputs_dir`. The grader follows its own
    instructions to inspect those files and emit `grading.json`.

After the grader returns, the runner re-reads `grading.json` and parses
its `summary.pass_rate` to decide whether the trial passed. The schema
matches what `report.py` already renders.

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
