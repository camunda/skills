# Eval suite — concepts

The "why" behind `evals/`. For the "how" (adding a scenario, debugging a
failure, regenerating a baseline), see [`scenarios.md`](scenarios.md).
For the original design and the roadmap of follow-up scenarios, see
[`../plans/01-eval-suite.md`](../plans/01-eval-suite.md) (its status box
notes where the landed suite diverged).

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

Lint runs on every PR touching `skills/` today. The eval workflow is
currently `workflow_dispatch`-only — it turns on as a PR gate once
credentials are provisioned and more than one scenario has been
validated end-to-end. Plan-era target: lint < 1 min / $0; evals
filtered to scenarios touching the changed skills, ~5–10 min, ~$1–4
per PR.

## Two-phase sandbox model

Every scenario runs in two Docker phases. Phase 1 is what the **agent**
does; Phase 2 is what **we** check.

```
┌────────────────────── Phase 1: Eval ───────────────────────┐
│  Container: with-c8ctl (or base for the bootstrap scenario)│
│  Services in compose: orchestration (camunda/camunda:8.9.x │
│  with H2), default (agent), optionally a connectors-bundle │
│  or WireMock sidecar per scenario                          │
│                                                            │
│  default shares orchestration's network namespace, so      │
│  localhost:8080 / :9600 just work from the agent's shell   │
│                                                            │
│  Agent receives prompt → uses tools (bash_session,         │
│  text_editor, skill via Inspect react()) → writes          │
│  artifacts to a shared /workspace volume                   │
│  (agent never sees Phase 2)                                │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼ /workspace mounted as /agent-workspace:ro
┌────────────────────── Phase 2: Verify ─────────────────────┐
│  Container: per-scenario choice (see Verifier menu below)  │
│  Network: egress denied; time/memory caps                  │
│                                                            │
│  CPT runs in remote-runtime (Spring CPT) against the same  │
│  orchestration cluster the agent worked against; the       │
│  verifier re-deploys the agent's BPMN from /agent-workspace│
│  and asserts behaviour. Other verifier shapes: c8ctl       │
│  exit-code, mvn compile + judge, transcript scorer,        │
│  WireMock journal, composite.                              │
└────────────────────────────────────────────────────────────┘
```

Why two phases: untrusted agent-generated code (most acutely, the
CPT-authoring scenario where the agent writes Java we then compile
+ code-review) must run in an isolated container with network denied
and resource caps, separate from the cluster the agent is interacting
with.

## Verifier menu

Verifier choice is per-scenario, declared in the task's metadata.
CPT is the workhorse for behavioural checks on a deployed BPMN, but
any scenario can compose a different verifier — or stack several.

Built today (`evals/src/scorers/`):

| Verifier | Used for | Scenario |
|---|---|---|
| **CPT remote-runtime** (`cpt_scorer` — Spring CPT, `mvn test` over an `*IT.java`; verifier shares orchestration's network namespace) | Behaviour of a deployed process | rocket-launch |
| **c8ctl + exit-code / JSON assertion** | Tool-shaped skills (does the artifact reach the cluster) | c8ctl-bootstrap |
| **`bpmn_lint_clean`** (`c8ctl bpmn lint` in the agent sandbox) | Cheap deterministic structural check on every `.bpmn` artifact | rocket-launch (any BPMN scenario) |
| **Inspect transcript scorer** (`assert_tool_called`, `assert_skill_loaded`) | "Did the agent route / fetch / cite as the skill instructs" | dev-routing |
| **Judge LLM** (Inspect's built-in `model_graded_qa`, per-sample rubric in `Sample.target`) | Free-form answer correctness | dev-routing |

Pick the **cheapest verifier that catches the failure mode you care
about**. Deterministic (CPT, lint, exit-code, transcript) before
non-deterministic (judge LLM). A composite is fine — rocket-launch
already stacks cluster + lint + CPT, each catching a different failure
mode at a different cost.

Likely additions as new scenario types land: a form-schema lint for
`.form` artifacts, and an HTTP-journal check (e.g. WireMock) for
connector scenarios. Not built yet — add them when a scenario needs
them.

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

A multi-skill scenario like AI-agent triage (`ai-agents`, `bpmn`, `connectors`,
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

**Agent loop**: Inspect's `react()` with `bash_session` + `text_editor`
+ `skill(all_skill_dirs())` tools. Model selected via Inspect's
`--model` flag (e.g. `--model anthropic/claude-sonnet-4-6`).

No CLI-style harness bridge today: there's no upstream Copilot CLI
bridge for Inspect AI, so `sandbox_agent_bridge()` isn't a path yet.
`react()` is the v1 agent loop — the `skill()` tool surfaces all 13
skills to the model, and cross-skill routing falls out of which
skills the model loads (transcript signal).

**Local credentials**: provide whatever the chosen `MODEL` needs. The
local default `anthropic/claude-sonnet-4-6` reads `ANTHROPIC_API_KEY`;
point `MODEL` at another provider (e.g. `bedrock/<profile>`) and supply
that provider's creds instead. Read from the environment — don't write
them to disk.

**CI credentials**: CI defaults to a Bedrock Claude profile and reads
AWS secrets; the model is switchable via the `EVAL_MODEL` repo
variable. See [`ci-and-results.md`](ci-and-results.md) for the exact
secret/variable names.

## Cross-skill verification (the load-bearing piece)

Inspect AI's transcript exposes every tool call and file read. A
reusable scorer in `evals/src/scorers/transcript.py` provides:

- `assert_tool_called("c8ctl", subcommand="deploy")` — CLI invoked
  (shipped)
- `assert_skill_loaded("camunda-bpmn")` — agent read
  `skills/camunda-bpmn/SKILL.md` or invoked the `skill` tool with that
  name (shipped)
- `assert_skill_chain(["camunda-bpmn", "camunda-dmn"])` — skills
  loaded in order (planned with scenario 09; see plan step I)

Once the chain scorer lands, multi-skill scenarios can assert
`assert_skill_chain(["camunda-ai-agents", "camunda-bpmn",
"camunda-connectors", "camunda-feel"])` → directly tests whether
cross-references in the skill bodies route the agent through the
suite. The prior single-skill eval attempt couldn't express this;
it's the new signal evals exist to catch.

## Cost & quota model

- **PR budget** (when CI is wired up): ~$1–4 per PR, scenarios filtered by path
- **Nightly budget**: ~$5–15
- **Local iteration**: whatever provider the engineer points the
  `MODEL` variable at; credentials come from the environment.
- **CI credentials**: provisioned as AWS secrets (see
  [`ci-and-results.md`](ci-and-results.md)).

If a scenario systematically blows its cost band, that's a regression
signal — `summarize.py` surfaces it in the PR comment once CI is on.

## What the eval suite is **not**

- Not a replacement for `waza check` — it runs alongside.
- Not a description-optimization loop. Skill descriptions are rewritten
  by hand; automating that is a possible future follow-up.
- Not a tool for blind A/B between skill versions (a possible
  follow-up, not built).
- Not a place to land speculative scenarios. Each scenario should
  catch a failure mode someone has actually observed or has a clear
  hypothesis about.
