# Eval suite — concepts

The "why" behind `evals/`. For the "how" (adding an eval, debugging a
failure, regenerating a baseline), see [`scenarios.md`](scenarios.md).
For the original design and the roadmap of follow-ups, see
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
| Does the right skill load for a prompt (and the wrong one stay out)? | trigger eval |
| Does the agent produce a deployable, working artifact? | result eval |
| Do cross-references route the agent through the right skills? | result eval (diagnostic skill-load scorer) |

Lint runs on every PR touching `skills/`. Evals are opt-in per PR via
label (see [`ci-and-results.md`](ci-and-results.md)) and report as a
non-blocking check.

## Two kinds of eval

| Kind | Question | Authored as | Where |
|---|---|---|---|
| **Trigger** | Does the right skill load? | YAML data | `evals/skills/<skill>/triggers.yaml` |
| **Result** | Does the agent reach the right result? | Python `task.py` | `evals/skills/<skill>/task.py` (per-skill) or `evals/scenarios/<id>/task.py` (cross-skill) |

Triggers are uniform, so they're pure data: each skill dir has a thin
`triggers.py` shim (`inspect eval skills/<skill>/triggers.py`) that binds
the shared routing task in `core/triggers.py` to that skill, scored by
`skill_loaded` / `skill_not_loaded` (both gating). A trigger
is a single structured-output call: the model gets the skill catalog
(the same `<available_skills>` block the `skill` tool discloses) plus
the prompt and returns the skills it would load — no agent, no tools, no
sandbox. It runs a single arm — you can't load an absent skill — so it
has no baseline.

Result evals are bespoke — each is an Inspect `task.py` that picks its
scorers (judge and/or deterministic) and supports `arm=with_skill |
without_skill`, and runs in a Docker sandbox. "Scenario" now means
specifically a cross-skill result eval.

## Two-phase sandbox model

Every result eval runs in two Docker phases. Phase 1 is what the
**agent** does; Phase 2 is what **we** check.

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
│  Container: per-eval choice (see Scorer menu below)        │
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

## Scorer menu

A result eval's scorers are declared in its `task.py`. The judge
catches free-form correctness; deterministic scorers catch structural
and behavioural failure modes more cheaply. Compose any combination —
or stack several.

Built today (`evals/src/scorers/`):

| Scorer | Used for | Gating |
|---|---|---|
| **Judge LLM** (Inspect's `model_graded_qa`, per-sample rubric in `Sample.target`) | Free-form answer correctness | yes |
| **`feel_evaluates_to`** (runs the agent's FEEL on the cluster) | FEEL expression result | yes |
| **`bpmn_lint_clean`** (`c8ctl bpmn lint`) | Structural check on every `.bpmn` artifact | yes |
| **`process_deployed_on_cluster`** (c8ctl assertion) | Artifact reached the cluster | yes |
| **`cpt_scorer`** (Spring CPT, `mvn test` over an `*IT.java`; shares orchestration's network namespace) | Behaviour of a deployed process | yes |
| **`assert_skill_loaded(..., gating=False)`** | Diagnostic: did the agent load the skill | no |

Pick the **cheapest scorer that catches the failure mode you care
about**. Deterministic (FEEL, lint, deploy, CPT) before
non-deterministic (judge LLM). A composite is fine — rocket-launch
stacks deploy + lint + CPT, each catching a different failure mode.
`assert_skill_loaded(gating=False)` is shown, not gated; the
with/without-skill delta on the gating scorers is the routing signal.

Likely additions as new eval types land: a form-schema lint for
`.form` artifacts, and an HTTP-journal check (e.g. WireMock) for
connector evals. Not built yet — add them when an eval needs them.

## `with_skill` / `without_skill` semantics

A result eval supports two arms via the `arm` task parameter. The
default `with_skill` arm exposes every skill. The `without_skill` arm
**disables** the load-bearing skill(s) named in
`metadata.baseline.exclude` — the agent cannot read or invoke them.
All *other* skills (transitive cross-refs from skills not in `exclude`)
remain available. The question is "what does *this* skill add", not
"what does the model do raw".

A multi-skill scenario like AI-agent triage (`ai-agents`, `bpmn`,
`connectors`, `feel`) excluding only `ai-agents` measures the AI-Agent
skill's specific contribution. The `without_skill` arm is a comparison,
not a quality bar — its gate step is skipped in CI.

Triggers run a single arm only: you can't measure "does the right skill
load" with the skill removed.

## Harness model

**Result-eval agent loop**: Inspect's `react()` with `bash_session` +
`text_editor` + `skill(all_skill_dirs())` tools. Model selected via
Inspect's `--model` flag (e.g. `--model anthropic/claude-sonnet-4-6`).

No CLI-style harness bridge today: there's no upstream Copilot CLI
bridge for Inspect AI, so `sandbox_agent_bridge()` isn't a path yet.
`react()` is the v1 agent loop — the `skill()` tool surfaces all 13
skills to the model, and cross-skill routing falls out of which skills
the model loads (transcript signal).

**Trigger routing**: not an agent loop — one structured-output call. The
model gets the `<available_skills>` catalog (built the same way the
`skill()` tool discloses it) plus the prompt, and returns the skill
names it would load. No tools, no sandbox; the meta-router
`camunda-development` is omitted from every catalog but its own.

**Local credentials**: provide whatever the chosen `MODEL` needs. The
local default `anthropic/claude-sonnet-4-6` reads `ANTHROPIC_API_KEY`;
point `MODEL` at another provider (e.g. `anthropic/bedrock/<profile>`)
and supply that provider's creds instead. Read from the environment —
don't write them to disk.

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

## Baseline & cost gate

`baseline.json` lives in each eval's directory and records each
sample's observed token count per arm:

```json
{
  "model": "anthropic/bedrock/global.anthropic.claude-sonnet-4-6",
  "with_skill": { "samples": { "gateway-condition": { "tokens": 4200 } } }
}
```

No bands, no duration, no stored pass-rate. The gate
(`evals-pass-fail`) runs two per-sample stages:

1. **Outcome** — every gating scorer ≥ threshold (default 1.0).
   Diagnostic scorers are shown, not gated.
2. **Cost** — only if a baseline entry exists *and* outcome passed:
   observed tokens ≤ `baseline.<arm>.samples.<id>.tokens × 1.5` (an
   upper ceiling only). A sample with no baseline entry is reported,
   not gated — so adding a sample never breaks existing ones.

Triggers have no baseline (outcome only). `summarize.py` surfaces a
token-budget excursion in the PR comment.

## What the eval suite is **not**

- Not a replacement for `waza check` — it runs alongside.
- Not a description-optimization loop. Skill descriptions are rewritten
  by hand; automating that is a possible future follow-up.
- Not a tool for blind A/B between skill versions (a possible
  follow-up, not built).
- Not a place to land speculative evals. Each eval should catch a
  failure mode someone has actually observed or has a clear hypothesis
  about.
