# Eval suite — concepts

The "why" behind `evals/`. For the "how" (adding a scenario, debugging a
failure, regenerating a baseline), see [`scenarios.md`](scenarios.md).

This doc is a digest of [`docs/plans/01-eval-suite.md`](../plans/01-eval-suite.md);
the plan stays the source of truth while PRs are landing. Anything that
contradicts the plan is a doc bug — open a PR.

## Why evals when we already have `waza check`?

`waza check` proves a skill is **well-formed** — spec compliance, token
budget, link health, frontmatter quality. It cannot prove a skill
**works**: that the BPMN the agent emits actually deploys, that the FEEL
expression evaluates, that the CPT test passes, that the agent routes
correctly through cross-referenced skills when a task spans multiple
domains.

Two distinct signals, two distinct gates:

| Question | Gate |
|---|---|
| Is the skill text well-formed? | `waza check` (lint) |
| Does the agent produce a deployable, working artifact? | eval suite |
| Do cross-references route the agent through the right chain of skills? | eval suite (transcript scorer) |

Both run on every PR touching `skills/`. Lint is cheap and fast (< 1 min,
$0). Evals are filtered to scenarios touching the changed skills
(~5–10 min, ~$1–4 per PR).

## Two-phase sandbox model

Every scenario runs in two Docker phases. Phase 1 is what the **agent**
does; Phase 2 is what **we** check.

```
┌────────────────────── Phase 1: Eval ───────────────────────┐
│  Container: with-c8ctl (or base for scenario #0)           │
│  Services in compose: c8run (Zeebe), optionally WireMock   │
│                                                            │
│  Agent receives prompt → uses tools (Bash, edit, c8ctl) →  │
│  writes artifacts to mounted outputs/ volume               │
│  (agent never sees Phase 2)                                │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼ outputs/ (read-only mount)
┌────────────────────── Phase 2: Verify ─────────────────────┐
│  Container: per-scenario choice (see Verifier menu below)  │
│  Network: egress denied; time/memory caps                  │
│                                                            │
│  Runs CPT, c8ctl, mvn test, transcript scorer, judge LLM,  │
│  or composite. Returns pass/fail + score per sample.       │
└────────────────────────────────────────────────────────────┘
```

Why two phases: untrusted agent-generated code (most acutely, scenario
#7 where the agent writes Java we then `mvn test`) must run in an
isolated container with network denied and resource caps, separate
from the cluster the agent is interacting with.

## Verifier menu

Verifier choice is per-scenario, declared in the task's metadata.
CPT is the workhorse for behavioural checks on a deployed BPMN, but
any scenario can compose a different verifier — or stack several.

| Verifier | Used for | Example scenarios |
|---|---|---|
| **CPT** (`mvn test` over a `.test.json` we authored) | Behaviour of a deployed process | 1, 2, 3, 4, 5, 6 |
| **c8ctl + exit-code / JSON assertion** | Tool-shaped skills (does the artifact reach the cluster) | 0 |
| **`mvn test` over agent-written Java** | Agent's *code* is the deliverable | 7 |
| **Inspect transcript scorer** | "Did the agent route / fetch / cite as the skill instructs" | 8, 9 (+ chain checks on 2, 3, 5) |
| **Judge LLM** (Haiku, structured rubric) | Free-form text, routing rationale, prompt quality | 8, 9 |
| **WireMock journal** | "Did the agent's process hit the right HTTP endpoint" | 2 |

Pick the **cheapest verifier that catches the failure mode you care
about**. Deterministic (CPT, exit-code, transcript) before non-deterministic
(judge LLM). A composite is fine — scenario #3 stacks CPT + mocked
job-worker + transcript scorer.

## `with-skill` / `without-skill` semantics

Per-scenario decision, declared in the task's `metadata.baseline`.
Three modes:

```python
# Mode A: exclude the load-bearing skill only (single-skill scenarios)
metadata = {..., "baseline": {"mode": "without-skill", "exclude": ["camunda-bpmn"]}}

# Mode B: exclude the whole scenario's skill set ("does any of them help?")
metadata = {..., "baseline": {"mode": "without-skill", "exclude": "all"}}

# Mode C: no comparison run — tool-shaped scenarios where there's nothing
# to compare against (e.g., a transcript scorer asserting a specific MCP
# call fires)
metadata = {..., "baseline": {"mode": "none"}}
```

How `exclude` is enforced: the eval suite **disables** the named
skill(s) for the without-skill arm — the agent cannot read or invoke
them. All *other* skills the agent might pull in (transitive
cross-refs from skills not in `exclude`) remain available. The
question is "what does *this* skill add", not "what does the model
do raw".

A multi-skill scenario like #3 (`ai-agents`, `bpmn`, `connectors`,
`feel`) excluding only `ai-agents` measures the AI-Agent skill's
specific contribution; `exclude: "all"` measures the suite's
collective contribution.

## Tier model

| Trigger | Scope | Cost ceiling | Wall time |
|---|---|---|---|
| Every PR (existing) | `waza check` | $0 | < 1 min |
| PR with path filter on `skills/<x>/` or `evals:run` label | Scenarios where `metadata.skills` intersects the changed skill(s); with + without arms | ~$1–4 | ~5–10 min |
| Nightly on `main` | All scenarios (with + without arms) | ~$5–15 | ~15–20 min |
| Manual `make eval SCENARIO=<id>` | Anything | iteration-cost only | — |

PR filter via `dorny/paths-filter`: change to `skills/camunda-bpmn/`
triggers only scenarios where `metadata.skills` includes
`camunda-bpmn`.

Weekly cross-harness matrix and a few other follow-ups (assertion
hygiene cron, A/B comparison, etc.) are deferred — see the plan's
**Open follow-ups** section.

## Harness model

**Default agent**: Copilot CLI (`INSPECT_AGENT_BRIDGE=copilot-cli`)

- CI auth: the workflow's auto-injected `GITHUB_TOKEN` with
  `permissions: models: read` — no new repo/org secret to provision
- Local auth: `gh auth login` (one-time)
- Billing: Copilot quota (single line item; same quota as the judge)
- Underlying model: Claude Sonnet 4 (configurable)

**Swap to Claude Code** (`INSPECT_AGENT_BRIDGE=claude-code`)

- CI auth: `ANTHROPIC_API_KEY` repo secret
- Local auth: `claude login` or `ANTHROPIC_API_KEY` env var
- Billing: Anthropic API direct

Inspect AI's `sandbox_agent_bridge()` is the primitive — same scenario
files run against either harness with no other change. Both speak
SKILL.md identically since [Copilot CLI's Dec 2025 Agent Skills
support](https://github.blog/changelog/2025-12-18-github-copilot-now-supports-agent-skills/).

## Cross-skill verification (the load-bearing piece)

Inspect AI's transcript exposes every tool call and file read. A
reusable scorer in `evals/lib/inspect_transcript.py` provides:

- `assert_skill_loaded("camunda-bpmn")` — agent read `skills/camunda-bpmn/SKILL.md`
- `assert_tool_called("c8ctl", subcommand="deploy")` — CLI invoked
- `assert_skill_chain(["camunda-bpmn", "camunda-dmn"])` — skills loaded in order

Scenario #3 asserts `assert_skill_loaded(["camunda-ai-agents",
"camunda-bpmn", "camunda-connectors", "camunda-feel"])` → directly
tests whether cross-references in the skill bodies route the agent
through the suite. The prior single-skill eval attempt couldn't
express this; it's the new signal evals exist to catch.

## Cost & quota model

- **PR budget**: ~$1–4 per PR (scenarios filtered by path)
- **Nightly budget**: ~$5–15
- **Single token**: GitHub Models covers agent under test (Copilot
  CLI) + judge model. One quota line in CI.
- **Local iteration**: free Copilot quota for engineers with a Copilot
  subscription; ANTHROPIC_API_KEY if using Claude Code locally.

If a scenario systematically blows its cost band, that's a regression
signal — `summarize.py` surfaces it in the PR comment.

## What the eval suite is **not**

- Not a replacement for `waza check` — it runs alongside.
- Not a description-optimization loop. Manual rewrites at 13 skills.
  See `FOLLOWUP-EVAL-04` in the plan if this changes.
- Not a tool for blind A/B between skill versions. See
  `FOLLOWUP-EVAL-05`.
- Not a place to land speculative scenarios. Each scenario should
  catch a failure mode someone has actually observed or has a clear
  hypothesis about.
