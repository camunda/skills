# Judge and semantic-similarity configuration

Judge assertions (LLM-as-Judge) and semantic-similarity assertions call an external model API at test runtime. Configure the provider in `src/test/resources/application.yml` (or `application.properties`). No cluster connection is needed — the embedded engine drives the process; the model call is a side-channel from the test JVM.

Two independent features, configured separately:

- **LLM-as-Judge** *(8.9+)* — a chat model scores a variable against a natural-language expectation. Nested under `camunda.process-test.judge`.
- **Semantic similarity** *(8.10+)* — an embedding model compares a variable to an expected string by cosine similarity. Nested under `camunda.process-test.similarity`.

Source of truth: [docs.camunda.io/docs/next/apis-tools/testing/configuration](https://docs.camunda.io/docs/next/apis-tools/testing/configuration/). Verify keys there before changing this file — do not transcribe from memory.

## Prerequisites

Both features use the optional [LangChain4j](https://docs.langchain4j.dev/) integration module, which ships preconfigured support for OpenAI, Anthropic, Amazon Bedrock, Azure OpenAI, and OpenAI-compatible APIs. LangChain4j requires **Java 17+**.

- **Camunda Spring Boot Starter**: includes the LangChain4j providers transitively — no extra dependency.
- **Java client**: add the `io.camunda:camunda-process-test-langchain4j` dependency (`<scope>test</scope>`).

You can supply your own integration instead via a custom `ChatModelAdapter` / `EmbeddingModelAdapter` (SPI or Spring bean), in which case the LangChain4j dependency is not required.

## LLM-as-Judge configuration *(8.9+)*

All judge properties nest under `camunda.process-test.judge`. (Java properties files use the `judge.` prefix with camelCase, e.g. `judge.chat-model.api-key` → `judge.chatModel.apiKey`.)

```yaml
camunda:
  process-test:
    judge:
      threshold: 0.5            # default 0.5 — score (0.0–1.0) at or above which the assertion passes
      custom-prompt: "..."      # optional — replaces only the default evaluation criteria
      chat-model:
        provider: openai        # openai | anthropic | amazon-bedrock | azure-openai | openai-compatible | <custom SPI name>
        model: gpt-4o
        api-key: ${OPENAI_API_KEY}
        timeout: PT30S          # optional, ISO-8601 duration
        temperature: 0.5        # optional, 0.0–2.0
```

| Key | Required | Default | Notes |
|-----------------------|----------|---------|-------|
| `judge.threshold`     | No       | `0.5`   | Confidence threshold (0.0–1.0). The default treats a partially satisfying response as a pass; raise it for stricter agreement. |
| `judge.custom-prompt` | No       | —       | Replaces only the evaluation criteria preamble. The expectation injection, scoring rubric, and JSON output format stay system-controlled. |
| `chat-model.provider` | Yes      | —       | One of the listed providers, or a custom SPI provider name. |
| `chat-model.model`    | Yes      | —       | Chat-completion model id. |
| `chat-model.api-key`  | Yes*     | —       | Resolved from the environment — never hard-code. *Optional for `azure-openai` (falls back to `DefaultAzureCredential`), `amazon-bedrock` (IAM / default chain), and local `openai-compatible`. |
| `chat-model.timeout`  | No       | —       | ISO-8601 duration, e.g. `PT30S`. |
| `chat-model.temperature` | No    | —       | 0.0–2.0. Lower → more deterministic verdicts. |

### Anthropic

```yaml
camunda:
  process-test:
    judge:
      chat-model:
        provider: anthropic
        model: claude-sonnet-4-20250514
        api-key: ${ANTHROPIC_API_KEY}
```

### Azure OpenAI

```yaml
camunda:
  process-test:
    judge:
      chat-model:
        provider: azure-openai
        model: my-gpt4o-deployment                  # Azure deployment name
        endpoint: https://my-resource.openai.azure.com/
        api-key: ${AZURE_OPENAI_API_KEY}            # optional; falls back to DefaultAzureCredential
```

Amazon Bedrock (`region` + `credentials.access-key`/`secret-key` or the AWS default chain) and OpenAI-compatible / Ollama (`base-url`, e.g. `http://localhost:11434/v1`) are also supported — see the configuration docs for their property tables.

### Per-assertion override

Override the global judge config for one assertion chain with `withJudgeConfig`:

```java
assertThat(processInstance)
    .withJudgeConfig(config -> config.withThreshold(0.9))
    .hasVariableSatisfiesJudge("result", "Contains a valid JSON response with status OK.");
```

## Semantic-similarity configuration *(8.10+)*

Semantic similarity uses a separate **embedding model** to encode both the actual and expected strings before computing cosine similarity. All properties nest under `camunda.process-test.similarity`.

```yaml
camunda:
  process-test:
    similarity:
      threshold: 0.5                      # default 0.5 — cosine-similarity floor (0.0–1.0)
      default-preprocessors-enabled: true # default true — lowercase, Unicode NFC, whitespace normalization before embedding
      embedding-model:
        provider: openai                  # openai | amazon-bedrock | azure-openai | openai-compatible | <custom SPI name>
        model: text-embedding-3-small
        api-key: ${OPENAI_API_KEY}
        dimensions: 1536                  # optional — for models supporting custom dimensions
        timeout: PT30S                    # optional, ISO-8601 duration
```

| Key | Required | Default | Notes |
|-------------------------------------------|----------|---------|-------|
| `similarity.threshold`                    | No       | `0.5`   | Cosine-similarity floor. Per-assertion overrides apply. |
| `similarity.default-preprocessors-enabled`| No       | `true`  | Applies default text preprocessors before embedding. |
| `embedding-model.provider`                | Yes      | —       | `openai`, `amazon-bedrock`, `azure-openai`, `openai-compatible`, or a custom SPI name. **No `anthropic`** — Anthropic exposes no embeddings endpoint. |
| `embedding-model.model`                   | Yes      | —       | An embeddings model (not a chat model). |
| `embedding-model.api-key`                 | Yes*     | —       | Same fallback rules as the judge `chat-model.api-key`. |
| `embedding-model.dimensions`              | No       | —       | Output dimensions for models that support it. |
| `embedding-model.timeout`                 | No       | —       | ISO-8601 duration. |

Override per assertion with `withSemanticSimilarityConfig`:

```java
assertThat(processInstance)
    .withSemanticSimilarityConfig(config -> config.withThreshold(0.9))
    .hasVariableSimilarTo("greeting", "Hello, how can I help you today?");
```

A `0.5` default tolerates wording and detail variance between runs; raise toward `0.9` only when expected and actual text should be near-identical.

## Environment variables

Store API keys in environment variables, never in checked-in YAML. Inject them in CI via secrets:

```yaml
# GitHub Actions example
env:
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

For local development, a `.env` file (git-ignored) or a shell export keeps the key out of the repository.

## Cost and latency considerations

Each assertion makes one or two external round-trips (one chat call for LLM-as-Judge; one embedding call per string for semantic similarity). In a large suite:

- Prefer semantic similarity for factual/structured outputs — cheaper and faster than a chat-completion judge call.
- Prefer LLM-as-Judge for nuanced expectations that need reasoning (tone, completeness, multi-step logic).
- Group agentic scenarios into a dedicated Maven profile (e.g. `-P agentic-tests`) so they can be skipped in fast local runs and run in full CI.

## Cross-references

- [authoring.md § Agentic evaluation assertions](authoring.md#agentic-evaluation-assertions-810) — `ASSERT_VARIABLE` JSON instructions *(8.10+)*
- [test-context.md § Judge and similarity assertions](test-context.md#judge-and-similarity-assertions) — the Java assertion API
- **camunda-ai-agents** — AI Agent Sub-process connector shape, ad-hoc sub-process tooling, `fromAi()` parameter bindings
