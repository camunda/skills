# Qualitative evaluation suite for camunda/skills

> **Status & divergences (as of PR #29 — https://github.com/camunda/skills/pull/29).**
> This plan shipped as step A of the rollout. The body below is the
> **original design**, kept as the roadmap for the remaining scenarios
> and deferred work. The landed implementation diverged from it in
> several places — **treat this box, not the body, as ground truth for
> current state.**
>
> **Landed**
> - Inspect AI harness on the `react()` loop (model via `--model`,
>   default `anthropic/claude-sonnet-4-6`).
> - Three scenarios: `c8ctl-bootstrap` (exit-code), `rocket-launch`
>   (cluster + BPMN lint + CPT), `dev-routing` (7-sample advisory
>   routing — `model_graded_qa` + `assert_skill_loaded` diagnostic).
> - Sandboxes: `base`, `with-c8ctl`, `verifier` (CPT, Maven pre-warmed
>   at image build), `advisory`.
> - Per-sample baselines: `{low, high}` token + duration bands plus an
>   arm-level `pass_rate`; `evals-pass-fail` is the CI gate.
> - Python project at the **repo root**; scenarios at
>   `evals/scenarios/<id>/` (not under `src/`).
>
> **Diverged from the design below**
> - **Agent loop:** `react()`, not a Copilot/Claude CLI bridge — no
>   such Inspect bridge exists yet. `claude_code()` was trialled but
>   truncates the skill manifest past ~3 skills, so meta-skill routing
>   is unreliable there; `react()` is the default for routing/advisory
>   scenarios.
> - **No `tier` field.** Selection is `metadata.skills ∩ changed-skills`
>   on PR; nightly runs every scenario. A tier split can return if the
>   scenario set grows enough to need it.
> - **No `metadata.epochs` field.** Use Inspect's own `--epochs` flag
>   ad hoc for flake checks.
> - **`baseline` simplified to `{ exclude }`** (no `mode`).
> - **No custom judge module.** `src/scorers/llm_judge.py` was dropped
>   in favour of Inspect's built-in `model_graded_qa` with a per-sample
>   rubric in `Sample.target`.
> - **No `cost_band_usd`.** Inspect doesn't expose cost on the log;
>   token + duration bands carry the resource signal instead.
>
> **Roadmap (not yet built)** — the body below still applies: remaining
> scenarios (DMN, payment-incident, forms, AI-agents e2e, docs-invocation,
> CPT-authoring), the connector runtime + WireMock for connector
> scenarios, CI credentials (flip workflows off `workflow_dispatch`),
> and the deferred follow-ups (cross-harness matrix, assertion-hygiene
> check, A/B, GitHub Pages export).

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
| Agent under test | **Inspect `react()` loop** with `bash_session` + `text_editor` + `skill(all_skill_dirs())` tools; model picked via Inspect's `--model` flag | No upstream Copilot CLI bridge for Inspect exists yet; `sandbox_agent_bridge()` was the plan-era assumption. `react()` is the path until a CLI-style bridge lands. Skill discovery falls out of `skill()` tool choice rather than direct file-system seeding, so cross-skill routing stays a transcript signal. |
| Judge model | **Claude Sonnet 4.6** (default `global.anthropic.claude-sonnet-4-6`, served via AWS) | GitHub Models free tier rejected during validation — per-request token caps (gpt-5: 4000, gpt-4.1: 16000) are too tight for our `react()` loop with `skill()` + 13 skills. Judging now uses Inspect's built-in `model_graded_qa` (no custom judge module). |
| Runtime in sandbox | **Camunda 8.9.x via docker compose** for Phase 1 (`camunda/camunda:8.9.5`, H2 backend, no Elasticsearch / Postgres); **CPT remote-runtime mode (Spring CPT)** against the same orchestration cluster for Phase 2 | c8run dropped — no aarch64 build; `camunda/camunda` is multi-arch. Remote-runtime CPT means the verifier and the agent operate against the *same* cluster (shared via `network_mode: service:orchestration`); the verifier re-deploys the agent's BPMN and asserts behaviour. Embedded testcontainers reserved for scenarios that genuinely need per-test isolation (none in v1). |
| LLM mocking inside scenarios | **CPT `mockJobWorker.withHandler`** against the remote cluster — plain `CamundaClient` job subscription, runtime-mode-agnostic per the [CPT docs](https://docs.camunda.io/docs/apis-tools/testing/utilities/#mock-job-workers). | The `camunda/camunda` image is the orchestration cluster only; the connector runtime ships as a separate `camunda/connectors-bundle` image. Our compose currently runs orchestration only — no competing subscriber, no race. When 02 / 03 / 04 need a connector runtime, we add the bundle as a compose service and control which connectors are active (env vars / image overlay). For scenarios where the connector itself should fire end-to-end (not just have its worker mocked), `FOLLOWUP-EVAL-01` covers WireMock-as-HTTPS-proxy as the higher-fidelity option. |
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
- Services in compose: an `orchestration` service running `camunda/camunda:8.9.5` (H2 backend, no Elasticsearch / Postgres) plus the agent's `default` container, which shares orchestration's network namespace via `network_mode: service:orchestration`. Compose's `depends_on: condition: service_healthy` gates the agent until the orchestration health-check passes. Optionally WireMock or other sidecars per scenario.
- Agent receives prompt, uses tools (`bash_session`, `text_editor`, `skill` via Inspect's `react()` loop; `c8ctl` on PATH), writes artifacts to the shared `/workspace` volume.
- Agent never observes Phase 2.

**Phase 2 — Verify**

Verifier is **per-scenario**. CPT is the workhorse for behavioural checks
on a deployed BPMN, but any scenario can compose a different verifier
(or stack several) depending on what the skill is supposed to produce:

| Verifier | Used for | Example scenarios |
|---|---|---|
| **CPT remote-runtime** (Spring CPT — `mvn test` over an `*IT.java` we authored; points at the orchestration cluster via shared network namespace) | Behaviour of a deployed process | 1, 2, 5, 6 |
| **c8ctl + exit-code / JSON assertion** | Tool-shaped skills (does the artifact reach the cluster at all) | 0 |
| **`bpmn_lint_clean`** (`c8ctl bpmn lint` invoked in the agent sandbox) | Cheap deterministic structural check on every `.bpmn` artifact the agent wrote | 1, 2, 5 (any BPMN scenario) |
| **`form_lint_clean`** (validate against vendored `@bpmn-io/form-json-schema`) | Cheap deterministic structural check on every `.form` artifact | 2 |
| **`mvn compile` + LLM-judge code-review over agent-written Java** | CPT-authoring scenario where actually running the test would risk Docker-in-Docker via testcontainers fallback paths; compile gates valid CPT-API usage, judge gates quality | 7 |
| **Inspect transcript scorer** (`assert_tool_called`, `assert_skill_loaded`, `assert_skill_chain`) | "Did the agent route / fetch / cite as the skill instructs" | 8, 9 (+ chain checks on 2, 5) |
| **Judge LLM** (Sonnet 4.6, single-score rubric — `src/scorers/llm_judge.py`) | Free-form answer correctness | 7, 8 |
| **WireMock journal** | "Did the agent's process actually hit the right HTTP endpoint" | 2 |

The verifier shares the orchestration cluster's network namespace, so
CPT in remote-runtime mode reaches `localhost:8080` (REST) and
`localhost:9600` (management) directly. The agent's `/workspace`
volume is mounted read-only at `/agent-workspace` inside the verifier
so BPMN / form / DMN files the agent wrote are pickup-able regardless
of filename — scenarios walk for `*.bpmn` / `*.form` / `*.dmn`. Network
egress + time + memory caps via compose `deploy.resources` + Inspect
`time_limit`. Maven local repo lives in a named `m2-cache` volume
shared across runs.

v1 uses online Maven with a `.m2` cache volume for simplicity;
dep-tree bake-in + `mvn -o` is `FOLLOWUP-EVAL-07`.

**Two base images, declared in `evals/sandboxes/`:**
- `base.Dockerfile`: Eclipse Temurin 25 + Node 24 + Maven + jq — no c8ctl.
  Used only for the c8ctl-bootstrap scenario (00).
- `with-c8ctl.Dockerfile`: base + `npm i -g @camunda8/cli` + `c8ctl element-template sync`.
  Used by scenarios 1–9.
- `verifier.Dockerfile`: same toolchain as base; used as the Phase 2
  container for CPT-shaped verifiers.

**Compose archetypes** in `evals/sandboxes/`:
- `compose-base.yaml` — `orchestration` + `default` (base image).
- `compose-with-c8ctl.yaml` — `orchestration` + `default` (with-c8ctl image).
- `compose-cpt-verifier.yaml` — `orchestration` + `default` (with-c8ctl)
  + `verifier` (mvn/Java toolchain) for scenarios that need Phase 2
  Java execution. Shared `workspace` named volume (`default` rw,
  `verifier` ro at `/agent-workspace`). Maven `m2-cache` as a separate
  named volume.

Each `task.py` declares its sandbox directly via
`sandbox=("docker", str(SANDBOXES_DIR / "compose-<archetype>.yaml"))`.
No resolver indirection; the compose file is the declaration. When a
scenario needs custom infra (e.g. WireMock with specific mappings) it
adds its own `compose.yaml` next to `task.py` and references that path
instead — `include:` from an archetype to inherit base config.

## Layout

```
evals/
├── README.md                      # quickstart, links to docs/evals/
├── pyproject.toml                 # uv-managed; inspect-ai pinned; [project.scripts] CLIs
├── uv.lock                        # checked in
├── .python-version                # pinned (e.g., 3.12)
├── sandboxes/
│   ├── base.Dockerfile
│   ├── with-c8ctl.Dockerfile
│   ├── verifier.Dockerfile
│   └── compose-{base,with-c8ctl,cpt-verifier}.yaml
├── judges/                        # shared rubric prompts (markdown)
│   ├── routing_correctness.md
│   └── version_awareness.md
└── src/
    ├── core/                      # paths, metadata schema, scenario registry
    │   ├── paths.py
    │   ├── metadata.py            # ScenarioMetadata Pydantic model
    │   └── registry.py            # walks scenarios/, exposes JSON for CI
    ├── scorers/                   # shared Inspect scorers
    │   ├── transcript.py          # tool-call / skill-load assertions
    │   ├── cluster.py             # c8ctl-driven live-cluster checks
    │   ├── cpt.py                 # mvn test + Surefire XML parse
    │   ├── lint.py                # c8ctl bpmn lint (bpmn_lint_clean)
    │   └── llm_judge.py           # single-score Sonnet rubric; currently
    │                              # unused, earmarked for scenarios 7, 8
    ├── solvers/                   # shared Inspect solvers
    │   ├── boot_cluster.py        # confirm orchestration topology
    │   ├── collect_artifacts.py   # snapshot agent's /workspace into state.store
    │   └── deploy_bpmn.py
    ├── scripts/                   # CLI entry points (evals-list, evals-summarize, …)
    │   ├── summarize.py           # .eval logs → PR comment markdown
    │   ├── extract_artifacts.py   # write artifacts to logs/artifacts/ for review
    │   ├── analyze_assertions.py  # always-pass/always-fail detection (future)
    │   └── regen_baseline.py      # rewrites per-scenario baseline.json
    └── scenarios/
        ├── c8ctl-bootstrap/
        │   ├── task.py            # @task + METADATA: ScenarioMetadata
        │   ├── baseline.json
        │   └── fixtures/
        └── rocket-launch/
            ├── task.py
            ├── baseline.json
            ├── cpt-verifier/      # Spring CPT project (remote-runtime mode)
            │   ├── pom.xml        # spring-boot-starter-parent + camunda-process-test-spring
            │   └── src/test/
            │       ├── java/.../RocketLaunchIT.java
            │       └── resources/application.yml
            └── fixtures/
```

**Python tooling: `uv` everywhere.** No pip, no venv-by-hand, no `requirements.txt`.
- Initial: `uv init evals && uv add inspect-ai`
- Run: `uv run inspect eval evals/src/scenarios/rocket-launch/task.py`
- CI: `astral-sh/setup-uv@v4` action → `uv sync --frozen` → `uv run …`
- Single source of truth: `pyproject.toml` + checked-in `uv.lock`
- Locked Python via `.python-version`

**Scenario metadata via Inspect's native `@task(metadata={...})`** — no custom
YAML sidecar. Inspect AI already supports per-task metadata as the canonical
home for non-Python configuration; we use it as our contract. A small helper
in `evals/src/core/registry.py` imports all `task.py` files and exposes a flat
JSON view for CI consumers (PR comment, nightly summary, `analyze_assertions.py`).

Metadata is a Pydantic model (`evals/src/core/metadata.ScenarioMetadata`),
not a plain dict — schema lives in code rather than narrative, and
`extra="forbid"` catches typos at task-load time. Fields:

- `skills: list[str]` — which skills this scenario exercises
- `epochs: int` — default 1; 3 for trigger/judge-scored scenarios
- `tier: "pr" | "nightly" | "release"`
- `verifier: "cpt" | "exit-code" | "transcript" | "judge" | "composite"`
- `baseline: { mode, exclude }` — see next section

The Phase 1 image isn't a metadata field — it's implicit in the
`compose-*.yaml` the scenario points its `Task(sandbox=...)` at.

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
| 1 | Rocket Launch (BPMN deploy + run) | bpmn, process-mgmt | Composite: transcript (`c8ctl deploy` was called) + cluster (`process_deployed_on_cluster`) + `bpmn_lint_clean` + CPT remote-runtime | with-c8ctl + verifier | pr | 1 | `[camunda-bpmn]` |
| 2 | Invoice Approval (BPMN + form + HTTP connector) | bpmn, forms, connectors, process-mgmt | CPT + WireMock journal | with-c8ctl | pr | 1 | `all` |
| 3 | AI Agent Customer Support Triage | ai-agents, bpmn, connectors, feel | **Deferred** — broader AI-agent scope (model selection, credentials, fixture conversations). Mocking itself is solved (`mockJobWorker.withHandler` for the AI-Agent job worker; `FOLLOWUP-EVAL-01` for the higher-fidelity "connector fires through a fake LLM endpoint" variant). | with-c8ctl | nightly | 1 | `all` |
| 4 | Order Processing w/ AI Agent | ai-agents, bpmn, process-mgmt | **Deferred** — same scoping question as 3 | with-c8ctl | nightly | 1 | `all` |
| 5 | Payment Flow Incident Investigation | process-mgmt, bpmn | Setup solver deploys broken BPMN + provokes incident; agent resolves via c8ctl; CPT (or c8ctl exit-code check) asserts the instance reaches completion | with-c8ctl | pr | 1 | `all` |
| 6 | DMN COLLECT regression (catches the `month()` and `typeRef` traps) | dmn, feel | CPT `assertThatDecision` against deployed DMN | with-c8ctl | pr | 1 | `[camunda-dmn]` |
| 7 | CPT authoring (agent writes the test) | process-test | `mvn compile` + LLM-judge code-review over agent's `*IT.java`. No test execution — running the agent's CPT inside the verifier would invite Docker-in-Docker via testcontainers fallback. | with-c8ctl + verifier | pr | 1 | `[camunda-process-test]` |
| 8 | camunda-docs invocation (trigger via transcript) | docs | Composite: transcript scorer asserts WebFetch / docs-MCP fired on `docs.camunda.io`; judge LLM scores the agent's final answer for correctness | with-c8ctl | pr | 3 | `[camunda-docs]` |
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
| PR with path filter on `skills/<x>/` or `evals:run` label *(currently `workflow_dispatch`-only — turns on once CI credentials land)* | Scenarios where `metadata.skills` intersects the changed skill(s); with + without skill arms | ~$1–4 | ~5–10 min |
| Nightly on `main` *(currently `workflow_dispatch`-only)* | All v1 scenarios (with + without skill arms) | ~$5–15 | ~15–20 min |
| Manual `make eval SCENARIO=<id>` / `make eval-all` | Anything | iteration-cost only | — |

PR filter via `dorny/paths-filter`: change to `skills/camunda-bpmn/` triggers
only scenarios where `metadata.skills` includes `camunda-bpmn`.

## Harness & credentials

**Agent loop**: Inspect's `react()` with `bash_session` + `text_editor`
+ `skill(all_skill_dirs())` tools. Model picked via the `MODEL`
variable (default `global.anthropic.claude-sonnet-4-6`, served via
AWS; override e.g. `MODEL=anthropic/claude-sonnet-4-6`).

No CLI-style harness bridge today. There's no upstream Copilot CLI
bridge for Inspect AI, so `sandbox_agent_bridge()` isn't a path yet —
`react()` is the v1 loop. The `skill()` tool surfaces all 13 skills to
the model; cross-skill routing is a transcript signal (which skills
the model reached for), not file-system seeding.

**Local credentials**: provided to Inspect via the chosen model
provider's standard env vars (`AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` / `AWS_DEFAULT_REGION` for the default model,
or another provider's key if you override `MODEL`). Read from the
environment, not checked into shells.

**CI credentials**: the workflows authenticate via AWS secrets (see
`docs/evals/ci-and-results.md`). Until they're provisioned the
workflows stay `workflow_dispatch` / label-gated.

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
- **PR comment** via ~50-line `evals/src/scripts/summarize.py` + `peter-evans/create-or-update-comment@v4`:
  - Per-scenario pass/fail
  - Delta vs `baseline.json` (regression highlights)
  - Cost summary
  - Link to `.eval` artifact
- `edit-mode: replace` — single rolling comment, not stacked

## Cross-skill verification (the load-bearing piece)

Inspect AI's transcript exposes every tool call and file read. A reusable
scorer in `evals/src/scorers/transcript.py` provides:

- `assert_tool_called("c8ctl", subcommand="deploy")` — asserts CLI invocation *(shipped)*
- `assert_skill_loaded("camunda-bpmn")` — asserts agent read `skills/camunda-bpmn/SKILL.md` or invoked the `skill` tool with that name *(shipped)*
- `assert_skill_chain(["camunda-bpmn", "camunda-dmn"])` — asserts skills loaded in order *(planned with scenario 09; step I in [PR sequence](#pr-sequence))*

Once the chain scorer lands, multi-skill scenarios can assert
`assert_skill_chain(["camunda-ai-agents", "camunda-bpmn",
"camunda-connectors", "camunda-feel"])` → directly tests whether
cross-references in the skill bodies route the agent through the
suite. This is the test that the prior single-skill eval attempt
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
| B | `docs(evals): concepts + scenarios + agent-instructions + ci-and-results` + AGENTS.md link | The `docs/evals/` quartet. |
| C | `feat(evals): foundation + scenarios 00 + 01 + CI` | Harness scaffolding, scenarios `00-c8ctl-bootstrap` + `01-rocket-launch`, compose-based orchestration, Spring CPT remote-runtime verifier, three sandbox images, Makefile targets, both workflows gated `workflow_dispatch`-only. |
| D | `feat(evals): scenario 05-payment-flow-incident` | Phase 1 setup solver provokes incident on a known-broken BPMN before handing off to the agent; verifier checks the instance reaches completion. No mocking; exercises `process-mgmt` + `c8ctl` resolution. |
| E | `feat(evals): scenario 06-dmn-collect-regression` | DMN COLLECT + `month()` + `typeRef` traps. CPT `assertThatDecision` against deployed DMN. |
| F | `feat(evals): scenario 07-cpt-authoring (code-review variant) + judge module reactivation` | Agent writes a CPT test against a fixture BPMN; verifier runs `mvn compile` (no test execution) + LLM-judge code-review. Reintroduces `src/scorers/llm_judge.py` for use here and in step G. |
| G | `feat(evals): scenario 08-docs-invocation + composite verifier` | Composite of transcript scorer (assert WebFetch / docs-MCP fired on `docs.camunda.io`) + judge LLM (free-form answer correctness). Smallest new scenario; piggybacks on the judge from F. |
| H | `feat(evals): scenario 02-invoice-approval + WireMock + form_lint_clean` | Adds `wiremock` compose service; HTTP connector hits it; WireMock journal scorer reads via REST. `form_lint_clean` validates agent's `*.form` files against the vendored `@bpmn-io/form-json-schema`. |
| I | `feat(evals): transcript chain scorer + scenario 09-development-routing` | Extend `scorers/transcript.py` with `assert_skill_chain([...])`; ship scenario 09 which depends on it. |
| J | `feat(evals): cross-skill chain assertions on scenarios 02 + 05` | Apply chain scorer where the cross-skill story is load-bearing. |
| — | (deferred) `feat(evals): scenarios 03 + 04 (AI agent)` | Pending mocking-shape decision (`FOLLOWUP-EVAL-01`). |
| — | (deferred) `ci(evals): PR-comment polish + credential provisioning` | Picked up when CI credentials are provisioned. |

Steps D–J are mostly independent — can land in any order — except G
(needs judge module from F) and J (needs the chain scorer from I).
Path-filter on `evals/scenarios/<id>/` means each PR's CI only runs
what it added until merged to `main`.

Follow-ups (`FOLLOWUP-EVAL-01` through `FOLLOWUP-EVAL-07`, listed below) are
opened opportunistically as separate PRs once the [Execution
checklist](#execution-checklist-updated-as-prs-land) is mostly green.

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
- [x] C — foundation + scenarios 00, 01 + CI (rocket-launch green locally with `react()` + `claude-sonnet-4-6`; c8ctl-bootstrap scaffolded but not yet end-to-end-validated against a model run; CI workflows `workflow_dispatch`-only)
- [ ] D — scenario 05 (payment flow incident)
- [ ] E — scenario 06 (DMN COLLECT regression)
- [ ] F — scenario 07 (CPT authoring, code-review variant) + judge module reactivation
- [ ] G — scenario 08 (docs invocation, composite transcript + judge)
- [ ] H — scenario 02 (invoice approval, with WireMock + `form_lint_clean`)
- [ ] I — chain scorer + scenario 09 (development routing)
- [ ] J — cross-skill chain assertions on scenarios 02, 05
- (deferred) scenarios 03 + 04 (AI agent) — pending mocking design
- (deferred) CI credential provisioning + PR-comment polish

## Open follow-ups (deferred, separate PRs after step K)

Each follow-up is written for an agent picking it up cold: what problem it
solves, when to open it, and the rough shape of the work. Open as a PR when
the trigger fires — don't pre-fabricate.

### FOLLOWUP-EVAL-01 — WireMock-as-HTTPS-proxy for connector scenarios
- **Problem**: v1 mocks connector invocations at the *job-worker* layer
  via `mockJobWorker.withHandler`. That bypasses the connector runtime
  entirely — realistic from BPMN's view (the process can't tell), but
  doesn't exercise the connector. Some scenarios will want the
  higher-fidelity "the BPMN actually called the LLM / hit the right
  HTTP endpoint" assertion that only fires when the connector itself
  runs.
- **Trigger**: opened when a scenario fails because the agent-authored
  BPMN depends on the connector actually firing (e.g. an inbound
  webhook journal assertion that mocking would bypass), or when the
  AI-agent scenarios (3, 4) graduate from job-worker mocks to "real
  connector against a fake LLM endpoint".
- **Shape**: add `camunda/connectors-bundle` as a per-scenario compose
  service; stand up WireMock as an HTTPS forward-proxy with a trust
  anchor injected into the connectors-bundle JVM; route the AI Agent
  connector's OpenAI/Anthropic calls through it. WireMock journal
  becomes the verifier ("the BPMN actually called the LLM"). For HTTP
  connector scenarios (e.g. invoice approval), WireMock can run as a
  plain HTTP service that the connector targets directly — no proxy
  needed unless the agent emits an HTTPS URL.
- **Reference**: WireMock HTTPS proxy mode docs; Camunda Self-Managed
  Connectors deployment docs.

### FOLLOWUP-EVAL-02 — Cross-harness weekly matrix
- **Problem**: scenarios run today against Inspect's `react()` loop only;
  CLI-style harnesses (Copilot CLI, Codex CLI, Gemini CLI) load and route
  skills differently. Harness-specific regressions can ship undetected.
- **Trigger**: ship this once (a) an Inspect AI bridge for at least one
  CLI harness lands upstream, (b) the nightly is reliably green for
  ≥2 weeks, and (c) credentials for the second harness are provisioned.
  Premature matrix expansion = noise.
- **Shape**: new workflow `.github/workflows/eval-cross-harness.yml`
  running weekly. Matrix over `{react(), copilot-cli, claude-code,
  codex-cli, gemini-cli}` × scenarios 1–6 (whichever subset has working
  bridges). Same `make eval-all` target. New PR-comment dimension
  showing per-harness pass-rate. Each CLI harness needs its bridge
  installed in `with-c8ctl.Dockerfile` (additive).

### FOLLOWUP-EVAL-03 — Quarterly assertion-hygiene cron
- **Problem**: assertions rot. Always-pass scenarios stop catching anything;
  always-fail scenarios get ignored. Without periodic review the suite
  degrades into theatre.
- **Trigger**: ~3 months after the execution checklist is mostly green
  on `main`, or sooner if `summarize.py` shows a scenario at 100%
  pass-rate for 50+ runs with no false positives.
- **Shape**: implement `evals/src/scripts/analyze_assertions.py` (sketched in the
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
- **Trigger**: opened once scenario 07 lands (step F in the [PR
  sequence](#pr-sequence)) and we have a stable list of CPT transitive
  deps to bake. Also opened proactively if a security review flags the
  v1 network-denial model as insufficient. Note: with scenario 07 now
  being `mvn compile` + judge (not `mvn test`), exfil surface is
  narrower than the plan-era version assumed — but the existing CPT
  verifier projects we run for behavioural scenarios (1, 2, 5, 6) still
  run untrusted-adjacent code under online Maven, so the hardening is
  still worth doing.
- **Shape**: pre-resolve the CPT POM's full dep tree at image build time
  (`mvn dependency:go-offline`), commit the resolved versions, rebuild
  `verifier.Dockerfile` with the `.m2` repo baked in. Switch verifier
  invocations to `mvn -o test`. Network policy can then be
  `network_mode: none` rather than allowlist-based. Cost: image grows
  ~200MB; rebuild required when CPT version bumps.

(c8run remote-cluster variant was considered and dropped — we have no
concrete scenario today that needs a real connector runtime that embedded
testcontainers can't serve. Re-open as a numbered follow-up if a scenario
surfaces that demand.)
