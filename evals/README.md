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

## Layout

```
evals/
├── pyproject.toml          # uv-managed deps (inspect-ai)
├── uv.lock                 # checked in
├── .python-version         # pinned Python
├── sandboxes/              # base / with-c8ctl / verifier Dockerfiles + compose-*.yaml
└── src/
    ├── eval_harness/       # framework: solvers, scorers, metadata, registry
    │   ├── metadata.py
    │   ├── registry.py
    │   ├── paths.py
    │   └── scripts/
    └── scenarios/
        ├── c8ctl-bootstrap/
        └── rocket-launch/
```

## Docs

- **Why** → [`../docs/evals/concepts.md`](../docs/evals/concepts.md)
- **How (add/maintain/debug a scenario)** → [`../docs/evals/scenarios.md`](../docs/evals/scenarios.md)
- **For AI agents working on this repo** → [`../docs/evals/agent-instructions.md`](../docs/evals/agent-instructions.md)
- **CI & PR comment** → [`../docs/evals/ci-and-results.md`](../docs/evals/ci-and-results.md)
- **Multi-PR rollout plan** → [`../docs/plans/01-eval-suite.md`](../docs/plans/01-eval-suite.md)
