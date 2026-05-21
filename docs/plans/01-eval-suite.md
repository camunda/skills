# Qualitative evaluation suite for camunda/skills

> **Status:** plan + docs/evals/ quartet + harness foundation + scenarios
> 00, 01 + CI workflows landed via the first PR
> (https://github.com/camunda/skills/pull/29). Scenarios 02–09 follow per
> the [Execution checklist](#execution-checklist-updated-as-prs-land).

## Context

The repo has grown to 13 cross-referencing skills (BPMN, FEEL, DMN, connectors,
AI agents, CPT, …) covering Camunda 8.8+ development. Today's quality gate is
`waza check` (lint, token budget, spec compliance) — that proves skills are
**well-formed**, not that they **work**. Two real signals are missing:

1. **Hard-fact correctness.** Does the artifact the agent produces (BPMN, FEEL,
   DMN, CPT test) actually lint, deploy, evaluate, and run as intended?
2. **Cross-skill orchestration.** Do the skill cross-references actually route an
   agent through the suite when a task spans multiple skills (BPMN + DMN +
   connector + AI agent)? The prior eval attempt tested skills in isolation
   and got ~0 delta; the cross-link concern was never measured.

The friction surfaced in `SKILL_IMPROVEMENTS.md` was overwhelmingly multi-skill
(AI agent + ad-hoc + connector; DMN COLLECT + BPMN; CPT for ad-hoc subprocess).
The Camunda use-case showcase (Rocket Launch, Invoice Approval, AI Agent Triage,
Order Processing, Payment Flow Incident) is multi-step e2e: deploy → start →
complete task → assert state.

Goal: a baseline eval suite that runs locally and on CI, gates PRs with a fast
subset, and provides regression detection nightly. Built on existing tooling
(no custom Python framework — the prior 5,200-line attempt was unmaintainable);
verifiers carried by Camunda Process Test (CPT), which we already ship.

## Goals & non-goals

**Goals**
- Verify skills produce **deployable, working artifacts** — not just lint-clean text
- Verify **cross-skill scenarios** end-to-end through a running Camunda runtime
- Test **untrusted agent-generated code** safely (e.g., CPT tests authored by the agent)
- Single eval framework, sandboxed per scenario, reproducible local + CI
- Per-scenario baseline; PR comment summary; trajectory web UI for debugging
- Track tokens + cost per scenario as regression signal (not pass/fail)
- Bootstrap from a clean container — exercises `camunda-c8ctl` installation skill itself

**Non-goals (v1)**
- Description-optimization train/validation loop (manual rewrites at 13 skills)
- Automated skill-rewrite loop from eval signals
- Full cross-harness matrix on every PR (nightly only)
- Real LLM calls inside AI-agent scenarios on PR (mocked; opt-in for nightly)

## Stack decision

| Layer | Choice | Why |
|---|---|---|
| Lint gate | **waza** (unchanged) | Orthogonal to evals; covers spec compliance, token budget, link health |
| Eval framework | **Inspect AI** | Multi-step solver chain, native Docker-compose sandbox, harness-agnostic agent bridge, per-task token/time limits, mature trajectory viewer (`inspect view`) |
| Agent under test | **Copilot CLI default**, swappable via `INSPECT_AGENT_BRIDGE` env var to Claude Code / Codex CLI | Zero extra credential setup in CI (auto-injected `GITHUB_TOKEN` with `models: read`); same Copilot quota as the judge; all bridges speak SKILL.md identically since Dec 2025; Inspect's `sandbox_agent_bridge()` is harness-agnostic |
| Judge model | **GitHub Models** (Claude Sonnet 4 via OpenAI-compatible endpoint) with Anthropic / Bedrock fallback | Single token covers local + CI; quota fits PR-gate + nightly |
| Runtime in sandbox | **c8run** for Phase 1 (agent's tool calls); **CPT embedded testcontainers Zeebe** for Phase 2 verifier | Embedded CPT is the same Zeebe binary; faster, isolated. c8run reserved for scenarios that specifically need it. |
| LLM mocking inside scenarios | **CPT `mockJobWorker.withHandler`** as default; WireMock-as-HTTPS-proxy as `FOLLOWUP-EVAL-01` | Job-worker-level mock is most realistic from BPMN's view (connector runtime mocked too); HTTPS proxy avoids the agent under test smelling a custom-endpoint config |
| Untrusted code execution | Docker sandbox + network egress denied + per-task time/mem limits. (Maven dep-tree bake-in / `mvn -o` offline mode deferred to `FOLLOWUP-EVAL-07`.) | Handles the CPT-authoring scenario (agent writes Java we then `mvn test`). Network denial + resource caps cover v1; offline-mode hardening is defense-in-depth |

**Frameworks considered and rejected**: Skillgrade (no compose sandbox, no
multi-step solver, no cost tracking — strictly weaker for our shape), Harbor
(no GitHub Actions story, single-Dockerfile model doesn't fit our compose
needs), Promptfoo (single-turn prompt-shaped, multi-step trajectories are not
its primitive — would lead with it only if we wanted PR-comment UX as the
deciding factor, which Inspect can replicate in ~50 lines), custom Python
framework (prior 5,200-line attempt was unmaintainable; explicitly out).

## Sandbox model

Two-phase execution per scenario, both in Docker, separate containers:

**Phase 1 — Eval**
- Container: `with-c8ctl` (or `base` for the c8ctl-bootstrap scenario) — agent-side environment
- Services in compose: the agent container itself (`default`); the
  agent boots c8run inside that container via `c8ctl cluster start`
  (c8run is a CLI-managed subprocess, not a Docker image). Optionally
  WireMock as a sidecar for scenarios that need it.
- Agent receives prompt, uses tools (Bash, file edit, c8ctl), writes artifacts
  to a mounted `outputs/` volume
- Agent never observes Phase 2

**Phase 2 — Verify**

Verifier is **per-scenario**. CPT is the workhorse for behavioural checks
on a deployed BPMN, but any scenario can compose a different verifier
(or stack several) depending on what the skill is supposed to produce:

| Verifier | Used for | Example scenarios |
|---|---|---|
| **CPT** (`mvn test` over a `.test.json` we authored) | Behaviour of a deployed process | 1, 2, 3, 4, 5, 6 |
| **c8ctl + exit-code / JSON assertion** | Tool-shaped skills (does the artifact reach the cluster at all) | 0 |
| **`mvn test` over agent-written Java** | Scenarios where the agent's *code* is the deliverable | 7 |
| **Inspect transcript scorer** (`assert_tool_called`, `assert_skill_loaded`, `assert_skill_chain`) | "Did the agent route / fetch / cite as the skill instructs" | 8, 9 (+ chain checks on 2, 3, 5) |
| **Judge LLM** (Haiku, structured rubric) | Free-form text answers, routing rationale, prompt quality | 8, 9 (combined with transcript scorer) |
| **WireMock journal** | "Did the agent's process actually hit the right HTTP endpoint" | 2 |

The container does the heavy lifting (`outputs/` read-only mount, network
egress denied for `verifier`, time + memory caps via compose deploy
resources + Inspect `time_limit`). What runs *inside* the verifier
container is the scenario's choice, declared in its task file.

v1 uses online Maven with a `.m2` cache volume for simplicity;
dep-tree bake-in + `mvn -o` is `FOLLOWUP-EVAL-07`.

**Two base images, declared in `evals/sandboxes/`:**
- `base.Dockerfile`: ubuntu + node + jdk-21 + mvn + jq — no c8ctl. Used only
  for the c8ctl-bootstrap scenario (00).
- `with-c8ctl.Dockerfile`: base + `npm i -g @camunda8/cli` + `c8ctl element-template sync`.
  Used by scenarios 1–9.

## Layout

```
evals/
├── README.md                      # quickstart, links to docs/evals/
├── pyproject.toml                 # uv-managed; inspect-ai pinned
├── uv.lock                        # checked in
├── .python-version                # pinned (e.g., 3.12)
├── sandboxes/
│   ├── base.Dockerfile
│   ├── with-c8ctl.Dockerfile
│   ├── verifier.Dockerfile
│   └── compose.yaml               # parameterizable; references one image
├── lib/                           # shared Inspect solvers
│   ├── boot_cluster.py
│   ├── deploy_bpmn.py
│   ├── run_cpt.py                 # mvn test + Surefire XML parse → score
│   ├── inspect_transcript.py      # helpers for "did agent read SKILL.md X?"
│   └── registry.py                # imports task.py files, exposes metadata JSON for CI
├── judges/                        # shared rubric prompts (markdown)
│   ├── routing_correctness.md
│   └── version_awareness.md
├── scripts/
│   ├── summarize.py               # .eval logs → PR comment markdown
│   ├── analyze_assertions.py      # always-pass/always-fail detection
│   └── regen_baseline.py          # rewrites per-scenario baseline.json
└── scenarios/
    ├── 00-c8ctl-bootstrap/
    │   ├── task.py                # @task(metadata={...}) declares skills/image/tier/baseline/verifier
    │   ├── baseline.json
    │   └── fixtures/
    ├── 01-rocket-launch/
    │   ├── task.py
    │   ├── baseline.json
    │   ├── cpt-verifier/          # mvn project; pom.xml + RocketLaunchIT.java
    │   └── fixtures/
    └── … (02–09)
```

**Python tooling: `uv` everywhere.** No pip, no venv-by-hand, no `requirements.txt`.
- Initial: `uv init evals && uv add inspect-ai`
- Run: `uv run inspect eval evals/scenarios/01-rocket-launch/task.py`
- CI: `astral-sh/setup-uv@v4` action → `uv sync --frozen` → `uv run …`
- Single source of truth: `pyproject.toml` + checked-in `uv.lock`
- Locked Python via `.python-version`

**Scenario metadata via Inspect's native `@task(metadata={...})`** — no custom
YAML sidecar. Inspect AI already supports per-task metadata as the canonical
home for non-Python configuration; we use it as our contract. A small helper
in `evals/lib/registry.py` imports all `task.py` files and exposes a flat
JSON view for CI consumers (PR comment, nightly summary, `analyze_assertions.py`).

Conventional metadata fields (validated by `lib/registry.py` against a
schema, not by Inspect itself):
- `skills: list[str]` — which skills this scenario exercises
- `image: "base" | "with-c8ctl" | "with-c8ctl+verifier"`
- `epochs: int` — default 1; 3 for trigger/judge-scored scenarios
- `tier: "pr" | "nightly" | "release"`
- `verifier: "cpt" | "exit-code" | "transcript" | "judge" | "composite"`
- `baseline: { mode: ..., exclude: [...] }` — see next section

## `with-skill` / `without-skill` semantics

Per-scenario decision, declared in the task's `metadata.baseline`. Three modes:

```python
# Mode A: exclude the load-bearing skill only (default for single-skill scenarios)
metadata = {
    ...,
    "baseline": {"mode": "without-skill", "exclude": ["camunda-bpmn"]},
}

# Mode B: exclude the whole scenario's skill set ("does any of them help?")
metadata = {
    ...,
    "baseline": {"mode": "without-skill", "exclude": "all"},  # = every skill in metadata.skills
}

# Mode C: no comparison run — tool-shaped scenarios where there's nothing to
# compare against (e.g., a transcript scorer that asserts a specific MCP call fires)
metadata = {
    ...,
    "baseline": {"mode": "none"},
}
```

How `exclude` is enforced: the eval suite **disables** the named skill(s) for
the without-skill arm — agent under test cannot read or invoke them. All
*other* skills the agent might pull in (transitive cross-refs from skills not
in `exclude`) remain available, because the question is "what does *this* skill
add", not "what does the model do raw". A multi-skill scenario like the
AI-agent triage one (`ai-agents`, `bpmn`, `connectors`, `feel`)
excluding only `ai-agents` measures
the AI-Agent skill's specific contribution; `exclude: all` measures the suite's
collective contribution.

**Defaults for the 10 initial scenarios:**
- Scenarios 1, 6, 7, 8, 9: exclude the single load-bearing skill (e.g., `[camunda-bpmn]`)
- Scenarios 0, 2, 3, 4, 5: `exclude: all` — we want to know whether the
  cross-skill story holds; "which one skill is doing the work" is a follow-up
  question once the suite-as-a-whole gates green

## Scenarios (initial 10)

| # | Scenario | Skills | Verifier | Image | Tier | Epochs | Baseline (exclude) |
|---|---|---|---|---|---|---|---|
| 0 | c8ctl bootstrap from clean container | camunda-c8ctl | `c8ctl get topology --json` exit 0 + topology JSON shape check | base | pr | 1 | `[camunda-c8ctl]` |
| 1 | Rocket Launch (BPMN deploy + run) | bpmn, process-mgmt | CPT embedded | with-c8ctl | pr | 1 | `[camunda-bpmn]` |
| 2 | Invoice Approval (BPMN + form + HTTP connector) | bpmn, forms, connectors, process-mgmt | CPT + WireMock journal | with-c8ctl | pr | 1 | `all` |
| 3 | AI Agent Customer Support Triage | ai-agents, bpmn, connectors, feel | CPT + `mockJobWorker.withHandler` + skill-chain transcript scorer | with-c8ctl | pr | 1 | `all` |
| 4 | Order Processing w/ AI Agent | ai-agents, bpmn, process-mgmt | CPT + mocked agent job | with-c8ctl | pr | 1 | `all` |
| 5 | Payment Flow Incident Investigation | process-mgmt, bpmn | CPT provokes incident; agent resolves via c8ctl | with-c8ctl | pr | 1 | `all` |
| 6 | DMN COLLECT regression (catches the `month()` and `typeRef` traps) | dmn, feel | CPT `assertThatDecision` | with-c8ctl | pr | 1 | `[camunda-dmn]` |
| 7 | CPT authoring (agent writes the test) | process-test | `mvn test` exit 0 on agent's test against fixed BPMN; sandboxed verifier (offline-Maven hardening in `FOLLOWUP-EVAL-07`) | with-c8ctl + verifier | pr | 1 | `[camunda-process-test]` |
| 8 | camunda-docs invocation (trigger via transcript) | docs | Transcript scorer: WebFetch/MCP on `docs.camunda.io` fired + judge on answer correctness | with-c8ctl | pr | 3 | `[camunda-docs]` |
| 9 | camunda-development routing | development | Transcript scorer: correct downstream skill referenced + judge on routing rationale | with-c8ctl | pr | 3 | `[camunda-development]` |

**Edge-case samples per scenario.** Each scenario's `task.py` declares a list
of `Sample`s — initially one happy path + one edge case, but the design is
**N edge cases per scenario** with no upper bound. Inspect AI's native
sample-list shape supports this directly; the `id` field distinguishes them
in the trajectory viewer and PR comment. Suggested edge-case categories per
scenario (add as they surface from real failures, don't pre-fabricate):
ambiguous prompt, malformed input, version-floor edge (8.8 vs 8.9 features),
adversarial user (asks for an anti-pattern), large-input. The first
PR ships 1 happy + 1 edge case per scenario; later PRs add more as
bugs surface.

## Tiering

| Trigger | Scope | Cost ceiling | Wall time |
|---|---|---|---|
| Every PR (existing) | `waza check` | $0 | < 1 min |
| PR with path filter on `skills/<x>/` or `evals:run` label | Scenarios where `metadata.skills` intersects the changed skill(s); with + without skill arms | ~$1–4 | ~5–10 min |
| Nightly on `main` | All 10 scenarios (with + without skill arms) | ~$5–15 | ~15–20 min |
| Weekly cross-harness matrix *(FOLLOWUP-EVAL-02)* | Scenarios 1–6 × {Copilot CLI, Claude Code, Codex CLI, Gemini CLI} | ~$15–30 | ~30 min |
| Manual `make eval SCENARIO=<id>` / `make eval-all` | Anything | iteration-cost only | — |

PR filter via `dorny/paths-filter`: change to `skills/camunda-bpmn/` triggers
only scenarios where `metadata.skills` includes `camunda-bpmn`.

## Harness flexibility & credentials

**Default agent**: Copilot CLI (`INSPECT_AGENT_BRIDGE=copilot-cli`)

- CI auth: the workflow's auto-injected `GITHUB_TOKEN` with `permissions:
  models: read` — no new repo/org secret to provision
- Local auth: `gh auth login` (one-time, most engineers already have it)
- Billing: Copilot quota (single line item; same quota as the judge model)
- Underlying model: Claude Sonnet 4 (configurable via Copilot CLI flag)

**Swap to Claude Code** (`INSPECT_AGENT_BRIDGE=claude-code`)
- CI auth: `ANTHROPIC_API_KEY` repo secret (added to workflow as needed)
- Local auth: `claude login` or `ANTHROPIC_API_KEY` env var
- Billing: Anthropic API direct
- Used for: engineer preference locally; weekly cross-harness matrix
  (`FOLLOWUP-EVAL-02`); fallback if Copilot CLI ships a regression

Inspect AI's `sandbox_agent_bridge()` is the primitive — same scenario files
run against either harness with no other change. Both speak SKILL.md
identically since Copilot CLI's [Dec 2025 Agent Skills support](https://github.blog/changelog/2025-12-18-github-copilot-now-supports-agent-skills/).

## Determinism & epochs

- **No temperature pin** — eval reflects real-user variance
- Per-scenario `epochs` in task metadata; default `1` for hard-fact scenarios
  (CPT pass/fail is deterministic; flake = real signal we want)
- Trigger / judge scenarios: `epochs=3`, pass-rate threshold 2/3 in `baseline.json`
- If a hard-fact scenario shows flake in practice, bump its `epochs` and add
  a threshold — local iteration uses `--epochs 1` regardless to keep dev cycle fast

## Baseline

- Per-scenario `evals/scenarios/<id>/baseline.json` checked in
- Shape:
  ```json
  {
    "pass_rate": 1.0,
    "with_skill": { "pass_rate": 1.0, "tokens": [3500, 6500], "duration_s": [8, 25] },
    "without_skill": { "pass_rate": 0.0 },
    "cost_band_usd": [0.05, 0.30]
  }
  ```
- `make eval-baseline SCENARIO=<id>` regenerates; engineer reviews diff and commits
- CI compares run to baseline; PR comment surfaces regressions
- No state between runs — every run reproducible from `baseline.json` + scenario files

## Web UI & PR comments

- **`uv run inspect view <log-dir>`** for local trajectory inspection (built-in,
  port 7575). Engineers download `.eval` artifacts and inspect locally
- **CI uploads `.eval` logs** as workflow artifacts
- **PR comment** via ~50-line `evals/scripts/summarize.py` + `peter-evans/create-or-update-comment@v4`:
  - Per-scenario pass/fail
  - Delta vs `baseline.json` (regression highlights)
  - Cost summary
  - Link to `.eval` artifact
- `edit-mode: replace` — single rolling comment, not stacked

## Cross-skill verification (the load-bearing piece)

Inspect AI's transcript exposes every tool call and file read. A reusable
scorer in `evals/lib/inspect_transcript.py` provides:

- `assert_skill_loaded("camunda-bpmn")` — asserts agent read `skills/camunda-bpmn/SKILL.md`
- `assert_tool_called("c8ctl", subcommand="deploy")` — asserts CLI invocation
- `assert_skill_chain(["camunda-bpmn", "camunda-dmn"])` — asserts skills loaded in order

The AI-agent-triage scenario asserts `assert_skill_loaded(["camunda-ai-agents", "camunda-bpmn", "camunda-connectors", "camunda-feel"])`
→ directly tests whether cross-references in the skill bodies route the agent
through the suite. This is the test that the prior single-skill eval attempt
couldn't express.

## What we keep vs. drop from agentskills.io guidance

**Keep**
- Realistic prompts (file paths, casual language, personal context)
- N edge-case samples per scenario (start at 1, grow as failures surface)
- With-skill vs without-skill baseline with explicit `exclude` list per scenario
- Programmatic verifiers preferred; LLM-judge for rubrics
- Token + duration tracking per run
- Periodic assertion hygiene (`analyze_assertions.py` — see `FOLLOWUP-EVAL-03`)
- Trajectory inspection ("read traces, not just outputs")

**Drop or defer**
- `evals/evals.json` schema as a data file — Inspect AI native is source of
  truth (one source, no double-writing); thin export adapter optional later
- Anthropic skill-creator workspace layout (`<skill>-workspace/iteration-N/`) —
  we use top-level `evals/`; iteration history in CI artifacts, not git
- 5-iteration description-optimization loop — `FOLLOWUP-EVAL-04`, optional
- Train/validation split for trigger scenarios — single ~12-query set is fine;
  reversible if we later need split
- "Write assertions only after first run" as a mandate — most of our scenarios
  have well-defined success (CPT assertion); treat as tip, not rule
- Blind A/B comparison between skill versions — `FOLLOWUP-EVAL-05`

## In-repo planning & documentation

No GitHub epics — overkill at this scale. The plan and supporting docs live
in the repo and travel with the code. Doc layout under `docs/`:

```
docs/
├── plans/
│   └── 01-eval-suite.md           # this plan (cross-PR coordination point)
└── evals/
    ├── concepts.md                # WHY: shape, sandbox model, harness choice, baseline semantics
    ├── scenarios.md               # HOW: maintain existing scenarios, add new ones
    ├── agent-instructions.md      # for AI agents: when/how to extend evals
    └── ci-and-results.md          # tier matrix, PR comment shape, debugging .eval logs
evals/
└── README.md                      # 1-pager quickstart linking into docs/evals/
```

`docs/plans/` over `docs/rfcs/` / `docs/adr/` because this is a multi-PR
execution plan, not a one-shot decision or a proposal-for-debate. Numbered
(`01-…`) so future plans append in order. Once the suite stabilizes, completed
plans can move to `docs/plans/archive/` — record, not roadmap.

**Documentation files ship in the foundation PR** alongside this plan. AGENTS.md gets a
link added to `docs/evals/agent-instructions.md` so the operational guide is
discoverable from the canonical entry point (and via the AGENTS.md ⇄ CLAUDE.md
symlink, Claude Code finds it too).

## PR sequence

Each PR is a self-contained deliverable that leaves the repo in a working
state. CI gate progressively expands as scenarios land.

| Step | Title | Contents |
|---|---|---|
| A | `docs(plans): eval suite plan` | **This doc.** Shipped on its own first so subsequent PRs have something to point at. |
| B | `docs(evals): concepts + scenarios + agent-instructions + ci-and-results` + AGENTS.md link | The `docs/evals/` quartet (can ship before any code lands; reviewers can engage with the design separately from the harness wiring). |
| C | `feat(evals): foundation + scenarios 00 + 01 + CI` | `evals/{README,pyproject.toml,uv.lock,.python-version}`, `evals/sandboxes/{base,with-c8ctl}.Dockerfile` + `compose.yaml`, `evals/lib/*` (incl. `registry.py`), `evals/scripts/summarize.py`, scenarios `00-c8ctl-bootstrap` + `01-rocket-launch`, `Makefile` targets, both workflows gated on these two scenarios. |
| D | `feat(evals): scenario 02-invoice-approval` | scenario + WireMock service + baseline; add to CI matrix |
| E | `feat(evals): scenarios 03 + 04 (AI agent)` | both AI-agent scenarios share `mockJobWorker.withHandler` plumbing — ship together |
| F | `feat(evals): scenario 05-payment-flow-incident` | provoke + resolve pattern, demonstrates c8ctl as agent tool |
| G | `feat(evals): scenario 06-dmn-collect-regression` | DMN COLLECT + `month()` + `typeRef` traps |
| H | `feat(evals): scenario 07-cpt-authoring + verifier sandbox` | sandboxed Java exec; agent's CPT test under `mvn test` |
| I | `feat(evals): transcript chain scorer + scenarios 08 + 09` | extend `inspect_transcript.py` with chain assertions; ship the two trigger-shaped scenarios |
| J | `feat(evals): cross-skill chain assertions on scenarios 02, 03, 05` | apply chain scorer where the cross-skill story is load-bearing |
| K | `ci(evals): PR-comment polish + nightly tuning` | rolling comment refinements, nightly schedule tuning, artifact retention policy |

Steps D–K are mostly independent — can land in any order — except H (which
needs `verifier.Dockerfile` not in C) and J (needs the chain scorer from I).
Path-filter on `evals/scenarios/<id>/` means each PR's CI only runs what it
added until merged to `main`.

Follow-ups (`FOLLOWUP-EVAL-01` through `FOLLOWUP-EVAL-07`, listed below) are
opened opportunistically as separate PRs once steps A–K are landed.

## Maintaining this plan

This plan doc has a checklist below. Each PR that lands ticks the matching box
and updates the doc with anything that changed from the original design (e.g.,
"actually used `assert_mcp_called` not `assert_tool_called` because Inspect
surfaces MCP separately"). The plan stays a living document until all PRs
land, then graduates to a historical record (and the operational guidance
moves into `docs/evals/`).

## Execution checklist (updated as PRs land)

- [x] A — this plan
- [x] B — `docs/evals/{concepts,scenarios,agent-instructions,ci-and-results}.md` + AGENTS.md link
- [x] C — foundation + scenarios 00, 01 + CI
- [ ] D — scenario 02 (invoice approval)
- [ ] E — scenarios 03 + 04 (AI agent)
- [ ] F — scenario 05 (payment flow incident)
- [ ] G — scenario 06 (DMN COLLECT)
- [ ] H — scenario 07 (CPT authoring, verifier sandbox)
- [ ] I — chain scorer + scenarios 08, 09
- [ ] J — cross-skill chain assertions on 02, 03, 05
- [ ] K — CI/PR-comment polish

## Open follow-ups (deferred, separate PRs after step K)

Each follow-up is written for an agent picking it up cold: what problem it
solves, when to open it, and the rough shape of the work. Open as a PR when
the trigger fires — don't pre-fabricate.

### FOLLOWUP-EVAL-01 — WireMock-as-HTTPS-proxy for AI-agent scenarios
- **Problem**: v1 mocks the AI-agent invocation at the *job-worker* layer via
  CPT's `mockJobWorker.withHandler`. This is realistic from BPMN's view (the
  process can't tell), but the agent under test, when authoring scenarios,
  sees the workaround in the test fixtures — a leaky abstraction.
- **Trigger**: when an authoring scenario (07 or similar) fails because the
  agent emits a job-worker mock instead of trusting the connector runtime.
- **Shape**: stand up WireMock configured as an HTTPS forward-proxy with a
  trust anchor injected into the sandbox JDK; route the AI Agent connector's
  OpenAI/Anthropic calls through it. WireMock journal becomes a verifier
  (asserting "the BPMN actually called LLM"). Replaces the `mockJobWorker`
  path in scenarios 3, 4.
- **Reference**: WireMock HTTPS proxy mode docs.

### FOLLOWUP-EVAL-02 — Cross-harness weekly matrix
- **Problem**: scenarios run against Copilot CLI by default; Claude Code is a
  manual swap. Harness-specific regressions (Copilot CLI changes skill-loading
  behaviour, Codex CLI's tool plumbing differs) can ship undetected for weeks.
- **Trigger**: ship this once step K lands *and* the nightly is reliably green
  for ≥2 weeks — premature matrix expansion = noise.
- **Shape**: new workflow `.github/workflows/eval-cross-harness.yml` running
  weekly. Matrix over `INSPECT_AGENT_BRIDGE ∈ {copilot-cli, claude-code,
  codex-cli, gemini-cli}` × scenarios 1–6. Same `make eval-all` target. New
  PR-comment dimension showing per-harness pass-rate. Each harness needs its
  bridge installed in `with-c8ctl.Dockerfile` (additive).

### FOLLOWUP-EVAL-03 — Quarterly assertion-hygiene cron
- **Problem**: assertions rot. Always-pass scenarios stop catching anything;
  always-fail scenarios get ignored. Without periodic review the suite
  degrades into theatre.
- **Trigger**: ~3 months after step K lands, or sooner if `summarize.py`
  shows a scenario at 100% pass-rate for 50+ runs with no false positives.
- **Shape**: implement `evals/scripts/analyze_assertions.py` (sketched in the
  Layout section). Reads the last N nightly `.eval` logs, flags scenarios
  with pass-rate ∈ {0.0, 1.0} for the entire window. Run via a scheduled
  `eval-hygiene.yml` workflow that opens an issue summarizing findings.
  Engineer reviews per-scenario.

### FOLLOWUP-EVAL-04 — Description-optimization loop *(optional, agentskills.io)*
- **Problem**: a skill's frontmatter `description` field gates whether the
  agent loads the skill in the first place. Manual rewrites can miss
  regressions in trigger behaviour.
- **Trigger**: only open this if a skill's description ships a regression
  that manual rewrite + the existing trigger-shaped scenarios (08, 09) can't
  catch. Premature = unnecessary complexity.
- **Reference**: [agentskills.io guidance on description optimization](https://agentskills.io)
  recommends a train/validation split with a 5-iteration loop. This follow-up
  implements that loop against our trigger-shaped scenarios — query set split
  ~70/30, 5 iterations of rewrite → re-evaluate trigger rate → keep if both
  splits improve. Output is a candidate `description` for engineer review.

### FOLLOWUP-EVAL-05 — Blind A/B comparison between skill versions
- **Problem**: large rewrites of a skill (e.g., restructuring a SKILL.md +
  references) can both improve some scenarios and regress others. Cumulative
  pass/fail hides this.
- **Trigger**: opened ad-hoc when a PR's diff against `skills/<x>/` is
  "large" (heuristic: >30% of the skill's lines changed) AND nightly shows
  scenario mix changes (some + some -).
- **Shape**: workflow `eval-ab.yml` triggered manually with `--base <sha>
  --head <sha>`. Runs the affected scenarios against both checkouts under
  identical seed + epoch settings. PR comment shows pairwise win/loss/tie
  per scenario. No baseline involvement — A/B is its own signal.

### FOLLOWUP-EVAL-06 — Static-export Inspect view to GitHub Pages
- **Problem**: engineers debugging a failing eval need to download `.eval`
  artifacts and run `uv run inspect view` locally — friction.
- **Trigger**: opened once engineers actually complain about the download
  step. Don't pre-fabricate.
- **Shape**: extend the PR-comment workflow to also export Inspect view as
  static HTML (Inspect supports this) keyed by commit SHA, push to a
  `gh-pages` branch under `evals/<sha>/`. PR comment links to the live URL.
  Retention via `gh-pages` branch hygiene cron (keep last 30 days).

### FOLLOWUP-EVAL-07 — Maven dep-tree bake-in + `mvn -o` for verifier image
- **Problem**: v1's `verifier.Dockerfile` uses online Maven with a `.m2`
  cache volume + network egress denial as the security boundary. If Maven
  Central is reachable from the verifier (e.g., a misconfigured network
  policy), an agent-written CPT test could exfiltrate.
- **Trigger**: opened once scenario 07 lands (step H) and we have a stable
  list of CPT transitive deps to bake. Also opened proactively if a security
  review flags the v1 network-denial model as insufficient.
- **Shape**: pre-resolve the CPT POM's full dep tree at image build time
  (`mvn dependency:go-offline`), commit the resolved versions, rebuild
  `verifier.Dockerfile` with the `.m2` repo baked in. Switch the verifier
  invocation to `mvn -o test`. Network policy can then be `network_mode:
  none` rather than allowlist-based. Cost: image grows ~200MB; rebuild
  required when CPT version bumps.

(c8run remote-cluster variant was considered and dropped — we have no
concrete scenario today that needs a real connector runtime that embedded
testcontainers can't serve. Re-open as a numbered follow-up if a scenario
surfaces that demand.)
