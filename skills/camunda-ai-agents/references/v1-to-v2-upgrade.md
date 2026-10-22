# Upgrading AI Agent Templates: v1 → v2

Move AI Agent elements from the legacy (v1) element templates to the v2 templates *(8.10+)*. v1 and v2 are **separate templates**, not versions of one template — the move is a template swap, not a version bump. Source of truth: [Upgrade AI Agent element templates](https://docs.camunda.io/docs/components/connectors/out-of-the-box-connectors/agentic-ai-aiagent-upgrade/). Whether to switch at all is decided in `SKILL.md` § "Template Generations: v1 and v2".

## Prerequisites

- c8ctl ≥ 4.6.0.
- `modeler:executionPlatformVersion` on the BPMN file is `8.10.0` or later. c8ctl does not change it — set it first.
- Manual route only: Desktop Modeler 5.51.0+ (earlier versions show v2 as **Not found**).

## Template ID pairs

| Element | v1 (`<v1-id>`) | v2 (`<v2-id>`) |
| :-- | :-- | :-- |
| Sub-process | `io.camunda.connectors.agenticai.aiagent.jobworker.v1` | `io.camunda.connectors.agenticai.ai-agent-subprocess.v2` |
| Task | `io.camunda.connectors.agenticai.aiagent.v1` | `io.camunda.connectors.agenticai.ai-agent-task.v2` |
| Sub-process (hybrid) | `io.camunda.connectors.agenticai.aiagent.jobworker.v1-hybrid` | `io.camunda.connectors.agenticai.ai-agent-subprocess.v2-hybrid` |
| Task (hybrid) | `io.camunda.connectors.agenticai.aiagent.v1-hybrid` | `io.camunda.connectors.agenticai.ai-agent-task.v2-hybrid` |

Pick the pair that matches the element's current `zeebe:modelerTemplate`. Hybrid stays hybrid.

## Upgrade with c8ctl

`update` selects elements by **v1 template ID**, one ID per command. A file with both Sub-process and Task elements needs one run per v1 ID.

| Command | Updates |
| :-- | :-- |
| `update <v1-id> process.bpmn --to <v2-id>` | Every element using `<v1-id>`, any version. Other templates untouched. |
| `update <v1-id> <element-id> process.bpmn --to <v2-id>` | One element. Fails if it does not use `<v1-id>`. |

1. Refresh the cache so c8ctl has the newest v2 template and its migration recipe:

   ```bash
   c8ctl element-template sync
   ```

2. Preview with `--json`. `--dry-run` writes nothing and exits 1 if an element would fail or the write would need `--allow-lossy`:

   ```bash
   c8ctl element-template update <v1-id> process.bpmn --to <v2-id> --dry-run --json
   ```

3. Read `results[]` per element. Decide on:
   - `recipe`: `source` is `embedded` when the target template carries a migration recipe, `none` when not; `refusal` says why a recipe was not used.
   - `requiresAuthorization`: `true` means the write needs `--allow-lossy`.
   - `report.dropped`: values that would be lost.
   - `report.notes`: recipe notes, each with a `level`. Act on warnings.
   - `summary`: `failed > 0` or `blocked > 0` means nothing would be written.

   The other report categories (`added`, `moved`, `changed`, `kept`) describe themselves per entry; see the [c8ctl docs](https://github.com/camunda/c8ctl/tree/main/default-plugins/element-template) for the full shape. Compare the result with the manual notes in [Provider mapping](#provider-mapping).
4. Write:

   ```bash
   c8ctl element-template update <v1-id> process.bpmn --to <v2-id> --in-place
   ```

   c8ctl writes once, and only if **every** selected element migrates. Dropped values block the write unless `--allow-lossy` is passed.
5. Repeat steps 2–4 for the other v1 ID, if the file has one.
6. Run `c8ctl bpmn lint process.bpmn`, then the post-upgrade steps below.

### Recipe present or not

The migration recipe ships inside the v2 template (`metadata.migratesFrom`). It is what moves provider fields across the redesign.

- `recipe.source` is `embedded` → recipe is active. This is the expected case.
- `recipe.source` is `none`, or the update fails with `destination "input:provider.type" violates choice constraint` → the cached v2 template has no recipe. Only same-key values carry over; provider-specific values such as the Anthropic **Endpoint** and **API key** appear in `report.dropped`. Secret values and their keys print as `[REDACTED]` — identify them by `label`. Run `c8ctl element-template sync` and update c8ctl, then dry-run again. If there is still no recipe, do not write with `--allow-lossy` as a shortcut: re-enter the provider config by hand from the mapping below, or supply a recipe via `--recipe <file>`.
- The recipe accepts only v1 template version 12 or later. For an older element, c8ctl first updates it to v1 version 12, then applies the recipe; the report shows this step. When the recipe cannot be used for an element (`recipe.refusal`; a stale cache is a common cause — `sync` and retry), the report gives the reason, only same-key values copy, and the write requires `--allow-lossy`.
- `--map <from>=<to>` moves one binding's value per element when no recipe covers it.

### `--allow-lossy` discipline

Pass it only after reading every dropped value in the report. Afterwards set each dropped value on the v2 element. Never ask the user for a secret value — use the user-confirmed `{{secrets.NAME}}` reference.

Set values with `edit`. It does not re-apply the template, so it never resets other values, including hidden ones:

```bash
c8ctl element-template edit -i <element-id> process.bpmn \
  --set 'provider.anthropic.backend.anthropic.apiKey={{secrets.NAME}}'
```

`edit` processes `--set` arguments in order, and a property whose condition depends on another is created once that selector is set. Put selectors first: to switch the Anthropic backend and fill its fields in one command, set `provider.anthropic.backend.type` first, then the backend's `authentication.type`, then its endpoint and API key. A dependent property set before its selector fails with "Set the property its condition depends on first". Avoid `apply --set` here: re-applying resets dropdowns and hidden properties to the template default.

Verify v2 property paths with `c8ctl element-template get-properties <v2-id>` — they nest under `backend.<type>` and differ from v1 (v1 `provider.anthropic.authentication.apiKey` → v2 `provider.anthropic.backend.anthropic.apiKey`).

### Stopgap: update within v1

Upgrading to v2 is the intended path; v1 is deprecated. If the upgrade must wait, v1 elements can still move to the newest v1 version. Run `c8ctl element-template sync` first, then omit `--to`. c8ctl moves each element to the newest v1 version compatible with the file's execution platform version. The element keeps the v1 job type; the report flags the template as deprecated and names the v2 target.

```bash
c8ctl element-template update <v1-id> process.bpmn --dry-run --json
```

Re-run with `--in-place` to write.

## Provider mapping

Provider and backend are now decoupled. Unlisted fields carry over under the same label. "Recipe" = what `update` does when the recipe is active; "Manual" = what remains.

### Anthropic (v1 Anthropic → v2 Anthropic)

Carry over: API key, Timeout, Model, Maximum tokens, Temperature, top P, top K. New with no v1 equivalent: **Effort**, **Thinking mode**, **Enable prompt caching**; OAuth 2.0 client credentials on the custom backend.

| v1 Endpoint | v2 backend |
| :-- | :-- |
| Microsoft Foundry (`*.azure.com`, `*.azure.us`, `*.azure.cn`) | **Microsoft Foundry (Azure)**, **API endpoint** (API key auth, v1 API key). Remove trailing `/anthropic/v1` or `/v1`; v2 adds `/anthropic` if missing and appends `/v1/messages`. |
| Any other | **Custom / compatible endpoint**, **API endpoint**. Remove trailing `/v1`; v2 appends `/v1/messages`. |

- Recipe: picks the backend from the endpoint, copies the endpoint **unchanged**, turns on prompt caching; Effort and Thinking mode stay at model default.
- Manual: strip the trailing path segment from the endpoint.

### AWS Bedrock

v1 Bedrock Converse was often used for Claude. Choose by model family:

- **Claude** → v2 **Anthropic** provider + **AWS Bedrock Mantle** backend (keeps reasoning and prompt caching).
- **Other families** (Nova, Llama, Mistral, …) → v2 **AWS Bedrock Converse**, the direct replacement.

Both targets: Authentication, Timeout, Model, Maximum tokens, Temperature, top P carry over; Region → **AWS region**; Endpoint → **Custom endpoint**. Converse gains **Enable prompt caching**.

Mantle specifics:

- **Custom endpoint** needs the full Mantle base URL **including `/anthropic`** (e.g. `https://your-vpce-host/anthropic`), a different shape than the Bedrock Runtime endpoint.
- **Model** uses Anthropic's model ID scheme, not the AWS Bedrock model ID. Check the [Claude models overview](https://docs.anthropic.com/en/docs/about-claude/models/all-models).
- Mantle needs a different IAM policy than Bedrock Runtime. Tell the user to update it before migrating, else the first model call fails with an authentication or permission error.

- Recipe: keeps **every** element on Bedrock Converse and turns on prompt caching.
- Manual: for Claude models, switch the provider to Anthropic + Mantle after the upgrade.

### Azure OpenAI (→ v2 OpenAI, backend Microsoft Foundry)

Carry over: API key auth, Timeout, Temperature, top P.

| v1 | v2 |
| :-- | :-- |
| Endpoint | API endpoint |
| Client credentials (Client ID, Client secret, Tenant ID, Authority host) | Entra ID: Client credentials (same fields) |
| Model deployment name | Model |
| Maximum tokens | Max output tokens (Responses API) or Max completion tokens (Chat Completions API) |

New: **Entra ID: Managed identity** (Hybrid/Self-Managed only), **Entra ID scope**, **Effort**. With multiple connector replicas, each replica acquires and caches its own Entra ID token.

- Recipe: sets **API** to **Chat Completions**; moves Maximum tokens → Max completion tokens.
- Manual: for the **Responses** API, change **API** and enter the value in **Max output tokens**.

### OpenAI (→ v2 OpenAI, backend OpenAI API)

Carry over: API key, Organization ID, Project ID, Timeout, Model, Temperature, top P. Maximum completion tokens → Max completion tokens (Chat Completions) or Max output tokens (Responses). v1 always used Chat Completions; v2 defaults **API** to **Responses**. New: **Effort**.

- Recipe: sets **API** to **Chat Completions**.
- Manual: for **Responses**, change **API** and enter the value in **Max output tokens**.

### OpenAI-compatible (→ v2 OpenAI, backend Custom / compatible endpoint)

Carry over: API endpoint, Headers, Query parameters, Timeout, Model, Temperature, top P. Maximum completion tokens → Max completion tokens / Max output tokens; Custom parameters → **Body properties**. v2 appends `/chat/completions` or `/responses` to **API endpoint** — check the resulting path. New: OAuth 2.0 client credentials.

The v1 **API key** field becomes an **Authentication** selector. An `Authorization` header in v1 **Headers** took precedence over the API key:

- `Bearer <token>` → **API key**, token without the `Bearer` prefix; remove the header from **Headers**.
- Other scheme (`Basic …`) → keep the header, select **None**.
- No such header → **API key** with the v1 value; **None** if neither header nor key was set.

- Recipe: sets **API** to **Chat Completions**; selects **API key** if the v1 API key has a value, else **None**. It does **not** read an `Authorization` header.
- Manual: apply the header rules above; for **Responses**, change **API**.

### Google Vertex AI (→ v2 Google Gemini, backend Enterprise Agent Platform (Vertex AI))

Carry over: Project ID, Region, Authentication, Model, Temperature, top P, top K. Maximum output tokens → **Maximum tokens**. New: **Thinking budget** / **Thinking level**, and a **Google Gemini API** backend that needs no Google Cloud project.

v1 **Endpoint** has no Modeler equivalent (no custom backend for Gemini).

- Recipe: moves a custom Endpoint into a hidden v2 field. The connector uses it at runtime; Modeler neither shows nor edits it.

## Post-upgrade steps

Both routes (c8ctl and manual):

1. **Task variant only** — set the two additions the v2 Task template expects on the tools ad-hoc sub-process (`io.camunda.agenticai.toolContainer` and `completedAt: now()` in the Output element). Neither the template nor c8ctl sets them; see `ai-agent-task.md`, "Configure the multi-instance ad-hoc subprocess".
2. **Job type overrides** — if job types are overridden by env vars (hybrid), the v1 variables do not apply to v2 job workers. Set the v2 variables and point the template at the same custom type. Keep the v1 variables while v1 definitions are deployed or running.

   | Element | v1 variable | v2 variable |
   | :-- | :-- | :-- |
   | Task | `CONNECTOR_AI_AGENT_TYPE` | `CONNECTOR_AI_AGENT_TASK_TYPE` |
   | Sub-process | `CONNECTOR_AI_AGENT_JOB_WORKER_TYPE` | `CONNECTOR_AI_AGENT_SUBPROCESS_TYPE` |

3. **Running instances are unaffected.** Already-deployed definitions and their instances keep executing on the v1 job worker until a new version with the v2 template is deployed.

v2 templates write `zeebe:agentDefinition` on the element automatically — no configuration needed.

## Manual route (Modeler)

Open the process in Camunda Hub or Desktop Modeler 5.51.0+, set the execution version to 8.10+, **Change element** to the v2 AI Agent Task / Sub-process template, and re-enter provider config from the mapping above. Tools, memory, limits, response, and error handling are conceptually unchanged; re-check values that need re-entry.
