# Judge configuration *(8.9+)*

`ASSERT_EVALUATION` assertions (LLM-as-Judge and semantic similarity) require CPT to call an external model API at test runtime. Configure the judge and embedding provider in `src/test/resources/application.yml` (or `application.properties`). No cluster connection is needed — the embedded Zeebe engine drives the process; the judge call is a side-channel from the test JVM.

## Minimum required configuration

```yaml
camunda:
  process:
    test:
      evaluation:
        judge:
          provider: openai          # openai | anthropic | azure-openai
          model: gpt-4o-mini        # any chat-completion model on the provider
          api-key: ${OPENAI_API_KEY}
```

Without this block, any `ASSERT_EVALUATION` instruction or `assertThatEvaluation(...)` call throws `EvaluationJudgeNotConfiguredException` at runtime.

## LLM-as-Judge configuration

```yaml
camunda:
  process:
    test:
      evaluation:
        judge:
          provider: openai
          model: gpt-4o-mini
          api-key: ${OPENAI_API_KEY}
          temperature: 0.0          # default 0.0 — keep deterministic
          timeout-seconds: 30       # default 30
```

| Key | Default | Notes |
|-----|---------|-------|
| `provider` | — | Required. `openai`, `anthropic`, or `azure-openai`. |
| `model` | — | Required. Chat-completion model id. |
| `api-key` | — | Required. Resolved from the environment — never hard-code in source. |
| `temperature` | `0.0` | Lower → more deterministic verdicts. Raise only if you need variance. |
| `timeout-seconds` | `30` | Per-call timeout; increase for slow models or large outputs. |

### Azure OpenAI

```yaml
camunda:
  process:
    test:
      evaluation:
        judge:
          provider: azure-openai
          model: gpt-4o-mini                          # deployment name
          api-key: ${AZURE_OPENAI_API_KEY}
          endpoint: ${AZURE_OPENAI_ENDPOINT}          # e.g. https://my-resource.openai.azure.com
          api-version: "2024-02-01"
```

### Anthropic

```yaml
camunda:
  process:
    test:
      evaluation:
        judge:
          provider: anthropic
          model: claude-haiku-4-5-20251001
          api-key: ${ANTHROPIC_API_KEY}
```

## Semantic-similarity configuration

Semantic similarity uses a separate **embedding model** to encode both the expected and actual strings before computing cosine similarity. Configure it under `evaluation.semantic-similarity`:

```yaml
camunda:
  process:
    test:
      evaluation:
        semantic-similarity:
          provider: openai
          model: text-embedding-3-small
          api-key: ${OPENAI_API_KEY}
          threshold: 0.80           # project-level default; override per-assertion
```

| Key | Default | Notes |
|-----|---------|-------|
| `provider` | Inherits `judge.provider` if omitted | `openai` or `azure-openai`. Anthropic does not expose an embeddings endpoint. |
| `model` | — | Required when the section is present. Must be an embeddings model (not a chat model). |
| `api-key` | Inherits `judge.api-key` if same provider | Resolved from the environment. |
| `threshold` | `0.80` | Cosine similarity floor (0–1). Per-assertion `threshold` fields override this. |

A `threshold` of `0.80` tolerates light paraphrasing; `0.90+` requires close wording; below `0.70` rarely produces meaningful signal. Start at `0.80` and tighten based on observed failure/pass rates.

## Environment variables

Store API keys in environment variables, never in checked-in YAML. Inject them in CI via secrets:

```yaml
# GitHub Actions example
env:
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

For local development, a `.env` file (excluded from `.gitignore`) or shell profile export keeps the key out of the repository.

## Cost and latency considerations

Each `ASSERT_EVALUATION` call makes one or two external API round-trips (one for LLM-as-Judge, one embedding call per string for semantic similarity). In a large suite:

- Prefer `semantic-similarity` for factual/structured outputs — cheaper and faster than a chat-completion judge call.
- Prefer `llm` for nuanced criteria that require reasoning (tone, completeness, multi-step logic).
- Group agentic scenarios into a dedicated Maven test profile (`-P agentic-tests`) so they can be skipped in fast local runs and run in full CI.

## Cross-references

- [authoring.md § Agentic evaluation assertions](authoring.md#agentic-evaluation-assertions-89) — `ASSERT_EVALUATION` JSON instruction
- [test-context.md § Evaluation assertions](test-context.md#evaluation-assertions-89) — `assertThatEvaluation` Java API
- **camunda-ai-agents** — AI Agent Sub-process connector shape, ad-hoc sub-process tooling, `fromAi()` parameter bindings
