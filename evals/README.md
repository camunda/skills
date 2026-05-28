# Camunda skills — eval suite

Verifies the skills under `../skills/` produce deployable, working
artifacts and that cross-skill orchestration routes correctly —
signals `waza check` can't catch. Runs locally and on CI.

## Quickstart

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/).

```bash
make eval SCENARIO=rocket-launch    # one scenario
make eval-all                          # all scenarios
make eval-baseline SCENARIO=<id>       # regenerate baseline.json
```

Logs land under `evals/logs/`. To inspect a trajectory:

```bash
uv run inspect view evals/logs/        # http://localhost:7575
```

The uv project lives at the repo root (`../pyproject.toml`,
`../uv.lock`, `../.python-version`), so `uv run …` works from anywhere
in the repo without a `cd`.

## Layout

```
evals/
├── sandboxes/              # base / with-c8ctl / verifier Dockerfiles + compose-*.yaml + orchestration application.yaml
├── scenarios/
│   ├── c8ctl-bootstrap/
│   ├── dev-routing/
│   └── rocket-launch/      # incl. cpt-verifier/ (Spring CPT, remote-runtime)
└── src/
    ├── core/              # paths, metadata schema, scenario registry, metrics
    ├── scorers/           # shared scorers: transcript, cluster, cpt, lint
    ├── solvers/           # shared solvers: boot_cluster, collect_artifacts
    └── scripts/           # CLI entry points: evals-list, evals-summarize, evals-extract-artifacts, evals-regen-baseline, evals-pass-fail
```

## Docs

- **Why** → [`../docs/evals/concepts.md`](../docs/evals/concepts.md)
- **How (add/maintain/debug a scenario)** → [`../docs/evals/scenarios.md`](../docs/evals/scenarios.md)
- **For AI agents working on this repo** → [`../docs/evals/agent-instructions.md`](../docs/evals/agent-instructions.md)
- **CI & PR comment** → [`../docs/evals/ci-and-results.md`](../docs/evals/ci-and-results.md)
- **Original design + roadmap (with divergences noted)** → [`../docs/plans/01-eval-suite.md`](../docs/plans/01-eval-suite.md)
