# Camunda skills — eval suite

Verifies the skills under `../skills/` actually **work** — the right skill loads
for a prompt, and the agent produces deployable, working artifacts (BPMN that
lints and deploys, FEEL that evaluates, a CPT test that passes). This is the
behavioural gate alongside `waza check` (lint); it's built on
[Inspect AI](https://inspect.aisi.org.uk/) and runs locally and on CI.

## Quickstart

Prerequisites: [uv](https://docs.astral.sh/uv/); Docker for outcome evals only.

```bash
make eval-triggers SKILL=camunda-feel              # routing: does the skill load?  (no Docker)
make eval-images                                   # one-time: build sandbox images
make eval-outcomes TARGET=skills/camunda-feel      # behaviour: does the agent get it right?
make eval-viewer                                   # trajectory viewer — http://localhost:7575
```

The default model is `anthropic/bedrock/global.anthropic.claude-sonnet-4-6` (AWS
creds in the environment); override with `MODEL=…` + that provider's creds. The
uv project lives at the repo root, so `uv run …` works from anywhere without a `cd`.

## Layout

```
evals/
├── docs/                  # concepts · runbook · ci (see below)
├── sandboxes/             # Dockerfiles + docker-bake.hcl + compose-*.yaml (base / with-c8ctl / cpt-verifier / advisory)
├── skills/<skill>/        # triggers.py (routing) and, where one exists, outcomes.py
├── scenarios/<id>/        # cross-skill outcome evals (e.g. rocket-launch, c8ctl-bootstrap)
└── src/
    ├── core/              # paths, metadata schema, registry, metrics, trigger builder
    ├── scorers/           # cluster, cpt, feel, lint, transcript
    ├── solvers/           # boot_cluster, collect_artifacts
    └── scripts/           # CLIs: evals-list, evals-summarize, evals-pass-fail, evals-regenerate-baseline, evals-extract-artifacts
```

## Docs

- **Concepts** (the model: two kinds, sandbox, arms, baseline) →
  [`docs/concepts.md`](docs/concepts.md)
- **Runbook** (run · interpret · add · maintain) → [`docs/runbook.md`](docs/runbook.md)
- **CI** (labels · PR comment · baselines · secrets) → [`docs/ci.md`](docs/ci.md)
