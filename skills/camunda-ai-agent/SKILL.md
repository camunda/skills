---
name: camunda-ai-agent
description: |
  Use this skill to model and configure AI agents in Camunda 8 BPMN using the AI Agent Sub-process connector — an LLM driver applied to an ad-hoc subprocess with tools as BPMN activities.

  Use for: shaping the ad-hoc subprocess that hosts the agent, defining tools as service/script/user tasks or sub-processes, declaring LLM-supplied parameters via fromAi(), writing system/user prompt FEEL strings, wiring toolCallResult outputs, setting model and call limits, enabling multi-turn agent context, debugging tool-call resolution.

  Do not use for: the older AI Agent Task variant (see references/ai-agent-task.md), or generic BPMN authoring outside the agent host (use camunda-bpmn).

  **Workflow skill** — model the agent host, its tools, prompts, and limits. Covers c8ctl element-template apply for the AI Agent connector template.
---

# Camunda AI Agent

Build agentic AI processes in Camunda 8.8+: an LLM driver (the AI Agent connector, **Sub-process variant**) applied to an ad-hoc subprocess with tools modeled as BPMN activities. Covers shape, prompts, tool modeling with `fromAi()`, sub-flow tools, and multi-turn agent context.

The older **Task variant** (AI Agent connector on a service task paired with an external multi-instance ad-hoc subprocess and explicit feedback loop) is documented in [references/ai-agent-task.md](references/ai-agent-task.md) for the niche cases where you need to audit or intercept every tool call. The Sub-process variant is the recommended choice for everything else, and is what the rest of this skill teaches.

## Prerequisites

- Camunda 8.8+ cluster (the AI Agent connector ships in 8.8+)
- c8ctl CLI installed and a profile configured — see **camunda-c8ctl**
- An API key for the model provider you'll use (Anthropic, Amazon Bedrock, Azure OpenAI, Google Vertex AI, OpenAI, or any OpenAI-compatible provider). Store it as a Camunda cluster secret, never in the BPMN file.

## Cross-References

- **camunda-bpmn**: BPMN basics, ad-hoc subprocess element, namespaces, the mandatory lint loop.
- **camunda-connectors**: The underlying `c8ctl element-template` workflow used to apply the AI Agent template (and the REST connector commonly used as a tool).
- **camunda-feel**: FEEL syntax for prompts, `fromAi()` calls, result expressions, type coercion.
- **camunda-process-mgmt**: Deploying the process, starting an instance, inspecting incidents from agent invocations.

## Authoritative References

- [AI Agent connector overview](https://docs.camunda.io/docs/components/connectors/out-of-the-box-connectors/agentic-ai-aiagent/)
- [AI Agent Sub-process](https://docs.camunda.io/docs/components/connectors/out-of-the-box-connectors/agentic-ai-aiagent-subprocess/) (recommended variant)
- [AI Agent Task](https://docs.camunda.io/docs/components/connectors/out-of-the-box-connectors/agentic-ai-aiagent-task/)
- [Tool Definitions](https://docs.camunda.io/docs/components/connectors/out-of-the-box-connectors/agentic-ai-aiagent-tool-definitions/) — how tool name, description, and `inputSchema` are derived
- [`fromAi()` FEEL function](https://docs.camunda.io/docs/components/modeler/feel/builtin-functions/feel-built-in-functions-miscellaneous/#fromaivalue)

## Applying the AI Agent Connector

**Example** — apply the template via c8ctl rather than hand-writing the many provider/prompt/memory fields:

```bash
# 1. Find the current template ID and version — they evolve
c8ctl element-template search "ai agent"

# 2. Inspect the properties you care about
c8ctl element-template get-properties <id>
c8ctl element-template get-properties <id> --detailed data.systemPrompt.prompt

# 3. Apply to your ad-hoc subprocess element
c8ctl element-template apply -i <id> AgentTools process.bpmn \
  --set provider.type=anthropic \
  --set provider.anthropic.authentication.apiKey='{{secrets.ANTHROPIC_API_KEY}}' \
  --set provider.anthropic.model.model=claude-sonnet-4-5 \
  --set data.systemPrompt.prompt='="You are a customer support agent. Use the available tools to look up customers and orders, and escalate to a human only when needed."' \
  --set data.userPrompt.prompt='="Customer " + customerId + " reports: " + issue' \
  --set data.limits.maxModelCalls='=10'
```

The template handles `zeebe:taskDefinition`, the `zeebe:adHoc` collection bindings, default input mappings, and the model-provider-specific fields — they change across template versions, don't hand-code them.

Supported providers: `anthropic`, `bedrock`, `azure-openai`, `vertex-ai`, `openai`, plus OpenAI-compatible (custom endpoint).

## The BPMN Shape

The host is `bpmn:adHocSubProcess` — not a service task and not a regular sub-process. Tools live inside it.

```
bpmn:adHocSubProcess  (template applied here)
└── <root activities, each one a tool>
    bpmn:serviceTask   — e.g., REST connector call
    bpmn:scriptTask    — FEEL computation
    bpmn:userTask      — human-in-the-loop
    bpmn:subProcess    — multi-step or async tool
```

Hard rules that the lint loop does NOT catch — verify by hand:

- The element type must be `bpmn:adHocSubProcess`. A regular `bpmn:subProcess` or a service task will not host the connector.
- A tool's **root node** is the entry activity that the LLM picks. A root node has **no incoming sequence flow** and is **not a boundary event**. An incoming flow turns the node into a regular flow step and the agent never sees it.
- The ad-hoc subprocess must contain **at least one activity** — BPMN semantics; an empty agent is rejected.
- Somewhere in the tool's execution flow, the variable `toolCallResult` must be set — for a single-activity tool that's the activity itself; for a sub-flow tool, it can be any activity inside the sub-flow.

## Defining Tools

Three things determine whether the LLM picks a tool correctly:

1. **Tool name** — the **activity ID** in the ad-hoc subprocess (e.g., `LookupCustomer`, `GetCurrentWeather`). The connector uses the BPMN `id`, not the human-facing `name` attribute, as the tool name passed to the LLM. Pick descriptive IDs.

2. **Tool description** — the value of `<bpmn:documentation>` on the activity. If documentation is missing, the connector falls back to the activity's `name` attribute, but **always set documentation explicitly**. Strong descriptions say what the tool does, when to use it, when not to, and what it returns:

   > "Look up a customer by ID. Returns the customer's name, tier, and account status. Call this when the user mentions a customer ID or name. Do not call for anonymous queries."

3. **Input schema** — derived automatically from `fromAi()` calls inside the activity's input mappings. No `fromAi()` calls → empty schema → the LLM can't pass parameters.

A tool can be a **single activity** (service task, script task, user task) or a **sub-flow** rooted at a `bpmn:subProcess` containing further activities. In both cases the LLM only sees the root node — descriptions, inputs, and schema are read from there. The internal sub-flow steps are invisible to the LLM; they execute in sequence per normal BPMN semantics and propagate variables up when the sub-process completes.

Worked XML for each of the four shapes (REST, script, user task, sub-flow) is in [references/tool-modeling.md](references/tool-modeling.md).

## fromAi() — Declaring AI-Generated Parameters

`fromAi()` tags a value as "the LLM will provide this at runtime". The first argument must be a reference to `toolCall.<paramName>` — the last segment becomes the LLM-visible parameter name. The function takes an optional description, type (`"string"` default, plus `"number"`, `"boolean"`, `"array"`, `"object"`), a JSON-Schema fragment, and an options context for things like `{required: false}`.

```xml
<zeebe:input
  source='="https://api.example.com/customers/" + fromAi(toolCall.id, "Customer ID", "string")'
  target="url" />
```

Full signature, all 6 calling variants (positional, named, enum schemas, optional params, multi-call JSON bodies) in [references/fromai.md](references/fromai.md).

## toolCallResult — Returning Output to the Agent

When a tool completes, the connector reads the variable named `toolCallResult` from the tool's scope and forwards it to the LLM as the tool-call response. The rule is about **scope**, not which activity sets it:

- **Single-activity tool** — the activity itself sets `toolCallResult` (via a result expression / result variable / output mapping / script result variable).
- **Sub-flow tool** — any activity inside the sub-flow can set `toolCallResult`; BPMN variable scoping propagates the value to the sub-process scope when it completes.

Ways to set it depending on the activity type:

- **Connector with result expression**: `value="={toolCallResult: response.body}"`.
- **Connector with result variable**: name the result variable `toolCallResult`.
- **Output mapping**: `<zeebe:output source="=someValue" target="toolCallResult" />`.
- **Script task**: `<zeebe:script expression="..." resultVariable="toolCallResult" />`.

The value can be primitive (string, number) or a complex FEEL context — it'll be serialized to JSON before being sent to the LLM. If `toolCallResult` is missing or empty when the tool completes, the connector sends a generic "tool succeeded without returning a result" message to the LLM and the next turn degrades. Always set it meaningfully.

## Prompts

Both `data.systemPrompt.prompt` and `data.userPrompt.prompt` are FEEL strings — they start with `=`.

```xml
<zeebe:input
  source='="You are a customer support agent. Use available tools to look up customers and orders. Escalate to a human only when needed."'
  target="data.systemPrompt.prompt" />
<zeebe:input
  source='="Customer " + customerId + " (priority: " + priority + ") reports: " + issue'
  target="data.userPrompt.prompt" />
```

- **Static prompt**: `="You are ..."`. The `=` is mandatory even for plain text.
- **Variable interpolation**: `="Customer " + customerId + " reports: " + issue`. `+` coerces scalars to string.
- **Feedback-loop prompt**: `=if (is defined(followUpInput)) then followUpInput else initialUserInput`. Used when looping back into the agent with user follow-up — see "Response Interaction" below.

For long, structured prompts, build the string in a script task upstream and pass it in via a variable.

## Tool-Call Feedback Loop

The tool feedback loop is **internal**: the agent job worker repeatedly calls the LLM, activates the tools it chose, collects results, and re-prompts until the LLM produces a final response or `data.limits.maxModelCalls` is reached. You don't model the loop — only the tools.

## Response Interaction (User Feedback Loop)

After the agent produces its final response, you may want a user (or another agent acting as a judge) to review or amend it and bounce it back in. The pattern is to route from the ad-hoc subprocess to a user task that collects `followUpInput`, then back to the same agent ad-hoc subprocess. The user-prompt FEEL switches between the initial and the follow-up input:

```
data.userPrompt.prompt = =if (is defined(followUpInput)) then followUpInput else initialUserInput
```

The agent preserves conversation context across re-entries; see the [Sub-process docs](https://docs.camunda.io/docs/components/connectors/out-of-the-box-connectors/agentic-ai-aiagent-subprocess/) for the current context-handling field names, since these have evolved across template versions.

## Limits and Memory

- `data.limits.maxModelCalls` — caps the number of LLM calls per agent execution. Always set it (5–20 is a typical starting range); without a sensible cap a misbehaving prompt can rack up cost. There is no time-based limit.
- `data.memory.contextWindowSize` — caps how many prior messages the agent replays to the LLM (default 20). Smaller saves tokens, larger preserves more context.
- `data.memory.storage.type` — `in-process` (default), `camunda-document` (offload to the Camunda Document store when context grows past variable size limits), or `custom`. Use the hyphenated form.

## Troubleshooting

Non-obvious failure modes the lint loop will not catch.

- **Tool has an incoming sequence flow** — it stops being a tool and becomes a regular flow step. The tool's ROOT node must have no incoming flow. Internal activities inside a sub-flow tool can (and do) have incoming flows — that's how the sub-flow works.
- **Tool name confusion** — the LLM-visible tool name is the BPMN **`id`**, not the `name` attribute. Use descriptive PascalCase IDs.
- **Bare-string prompts** — both system and user prompts are FEEL. Even literals must be `="..."`.
- **Number-in-string FEEL** — concatenating a number into a URL or message requires `string(x)`; `+` between a string and an un-coerced number fails. Cross-ref **camunda-feel** § type coercion.
- **Hyphenated memory storage type** — `in-process`, `camunda-document`, `custom`. Not camelCase.

## Closing Step

Run the BPMN lint loop (see **camunda-bpmn**) before declaring the agent process done:

```bash
c8ctl bpmn lint process.bpmn
```

Lint catches structural BPMN problems but does not validate connector-template inputs. After lint is clean, verify by hand:

- Host element is `bpmn:adHocSubProcess` with the AI Agent template applied.
- Every tool's root node has no incoming sequence flow and has a `<bpmn:documentation>` element.
- Every tool's flow ends with `toolCallResult` set in scope.
- Both prompts start with `=`.
- `data.limits.maxModelCalls` is set.
- API keys are pulled from `{{secrets.*}}`, not literal values.

## References

For detailed reference material, read from `references/`:
- [tool-modeling.md](references/tool-modeling.md) — worked XML for the four tool shapes (REST connector, script task, user task, sub-flow), including async-callback sub-flows
- [fromai.md](references/fromai.md) — full `fromAi()` signature, all calling variants (positional, named, enum schemas, optional params, multi-call JSON bodies)
- [ai-agent-task.md](references/ai-agent-task.md) — the older Task variant (audit/intercept every tool call) — niche use only
