---
name: camunda-ai-agent
description: |
  Models and configures AI agents in Camunda 8 BPMN using the AI Agent Sub-process connector — an LLM driver applied to an ad-hoc subprocess with tools modeled as BPMN activities, fromAi() parameters, system/user prompt FEEL strings, tool descriptions, and multi-turn agent context. Use when creating, editing, or debugging an agentic AI process — an LLM that calls tools modeled as BPMN activities.
---

# Camunda AI Agent

Build agentic AI processes in Camunda 8.8+: an LLM driver (the AI Agent connector, **Sub-process variant**) applied to an ad-hoc subprocess with tools modeled as BPMN activities. Covers shape, prompts, tool modeling with `fromAi()`, sub-flow tools, and multi-turn agent context.

The older **Task variant** (AI Agent connector on a service task paired with an external multi-instance ad-hoc subprocess and explicit feedback loop) is documented in `references/ai-agent-task.md` for the niche cases where you need to audit or intercept every tool call. The Sub-process variant is the recommended choice for everything else, and is what the rest of this skill teaches.

## Prerequisites

- Camunda 8.8+ cluster (the AI Agent connector ships in 8.8+)
- c8ctl CLI installed and a profile configured — see **camunda-c8ctl**
- An API key for the model provider you'll use (Anthropic, Amazon Bedrock, Azure OpenAI, Google Vertex AI, OpenAI, or any OpenAI-compatible provider). Store it as a Camunda cluster secret, never in the BPMN file.

## Cross-References

- **camunda-bpmn**: BPMN basics, ad-hoc subprocess element, namespaces, the mandatory lint loop.
- **camunda-connectors**: The underlying `c8 element-template` workflow used to apply the AI Agent template (and the REST connector commonly used as a tool).
- **camunda-feel**: FEEL syntax for prompts, `fromAi()` calls, result expressions, type coercion.
- **camunda-process-mgmt**: Deploying the process, starting an instance, inspecting incidents from agent invocations.

## Authoritative References

- [AI Agent connector overview](https://docs.camunda.io/docs/components/connectors/out-of-the-box-connectors/agentic-ai-aiagent/)
- [AI Agent Sub-process](https://docs.camunda.io/docs/components/connectors/out-of-the-box-connectors/agentic-ai-aiagent-subprocess/) (recommended variant)
- [AI Agent Task](https://docs.camunda.io/docs/components/connectors/out-of-the-box-connectors/agentic-ai-aiagent-task/)
- [Tool Definitions](https://docs.camunda.io/docs/components/connectors/out-of-the-box-connectors/agentic-ai-aiagent-tool-definitions/) — how tool name, description, and `inputSchema` are derived
- [`fromAi()` FEEL function](https://docs.camunda.io/docs/components/modeler/feel/builtin-functions/feel-built-in-functions-miscellaneous/#fromaivalue)

When in doubt about field names, supported types, or schema details, prefer the official docs over this skill's examples.

## Applying the AI Agent Connector

The connector has a lot of fields (provider auth, prompts, memory, limits, response shape, event handling). Apply the template via c8ctl rather than hand-writing them.

```bash
# 1. Find the current template ID and version — they evolve
c8 element-template search "ai agent"

# 2. Inspect the properties you care about (condensed view, then detailed for specifics)
c8 element-template get-properties <id>
c8 element-template get-properties <id> --detailed data.systemPrompt.prompt

# 3. Apply to your ad-hoc subprocess element
c8 element-template apply -i <id> AgentTools process.bpmn \
  --set provider.type=anthropic \
  --set provider.anthropic.authentication.apiKey='{{secrets.ANTHROPIC_API_KEY}}' \
  --set provider.anthropic.model.model=claude-sonnet-4-5 \
  --set data.systemPrompt.prompt='="You are a customer support agent. Use the available tools to look up customers and orders, and escalate to a human only when needed."' \
  --set data.userPrompt.prompt='="Customer " + customerId + " reports: " + issue' \
  --set data.limits.maxModelCalls='=10'
```

The template handles the `zeebe:taskDefinition`, the `zeebe:adHoc` collection bindings, default input mappings, and the model-provider-specific fields. Avoid hand-coding these — they change across template versions.

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
- Somewhere in the tool's execution flow, the variable `toolCallResult` must be set — for a simple single-activity tool that's the activity itself; for a sub-flow tool, it can be any activity inside the sub-flow (see below).

## Defining Tools

Three things determine whether the LLM picks a tool correctly:

1. **Tool name** — the **activity ID** in the ad-hoc subprocess (e.g., `LookupCustomer`, `GetCurrentWeather`). The connector uses the BPMN `id`, not the human-facing `name` attribute, as the tool name passed to the LLM. Pick descriptive IDs.

2. **Tool description** — the value of `<bpmn:documentation>` on the activity. If documentation is missing, the connector falls back to the activity's `name` attribute, but **always set documentation explicitly**. Strong descriptions say what the tool does, when to use it, when not to, and what it returns:

   > "Look up a customer by ID. Returns the customer's name, tier, and account status. Call this when the user mentions a customer ID or name. Do not call for anonymous queries."

3. **Input schema** — derived automatically from `fromAi()` calls inside the activity's input mappings (see next section). No `fromAi()` calls → empty schema → the LLM can't pass parameters.

A tool can be a **single activity** (service task, script task, user task) or a **sub-flow** rooted at a `bpmn:subProcess` containing further activities. In both cases the LLM only sees the root node — descriptions, inputs, and schema are read from there. The internal sub-flow steps are invisible to the LLM; they execute in sequence per normal BPMN semantics and propagate variables up when the sub-process completes.

### REST connector tool

```xml
<bpmn:serviceTask id="LookupCustomer" name="Look up customer">
  <bpmn:documentation>Look up a customer by ID. Returns name, tier, and account status. Call this when the user mentions a customer ID. Do not call for anonymous queries.</bpmn:documentation>
  <bpmn:extensionElements>
    <zeebe:taskDefinition type="io.camunda:http-json:1" retries="1" />
    <zeebe:ioMapping>
      <zeebe:input source="GET" target="method" />
      <zeebe:input
        source='="https://api.example.com/customers/" + fromAi(toolCall.customerId, "The customer ID to look up", "string")'
        target="url" />
    </zeebe:ioMapping>
    <zeebe:taskHeaders>
      <zeebe:header key="resultExpression" value="={toolCallResult: response.body}" />
    </zeebe:taskHeaders>
  </bpmn:extensionElements>
</bpmn:serviceTask>
```

For real REST connector configuration, apply the HTTP connector template via `c8 element-template apply` (see **camunda-connectors**) — the snippet above shows the resulting XML shape.

### Script tool

```xml
<bpmn:scriptTask id="ComputeRefund" name="Compute refund amount">
  <bpmn:documentation>Compute the refund amount for an order, taking partial refunds into account.</bpmn:documentation>
  <bpmn:extensionElements>
    <zeebe:script
      expression="=fromAi(toolCall.orderTotal, &quot;Order total&quot;, &quot;number&quot;) * (1 - fromAi(toolCall.refundRatio, &quot;Refund ratio between 0 and 1&quot;, &quot;number&quot;))"
      resultVariable="toolCallResult" />
  </bpmn:extensionElements>
</bpmn:scriptTask>
```

### User task tool (human-in-the-loop)

```xml
<bpmn:userTask id="EscalateToHuman" name="Escalate to human agent">
  <bpmn:documentation>Hand the conversation to a human support agent. Call this when the customer's issue cannot be resolved with the available tools, or when they explicitly ask for a human.</bpmn:documentation>
  <bpmn:extensionElements>
    <zeebe:userTask />
    <zeebe:formDefinition formId="EscalationForm" />
    <zeebe:ioMapping>
      <zeebe:output source="=resolution" target="toolCallResult" />
    </zeebe:ioMapping>
  </bpmn:extensionElements>
</bpmn:userTask>
```

## fromAi() — Declaring AI-Generated Parameters

The `fromAi()` FEEL function tags a value as "the LLM will provide this at runtime". It returns its first argument unchanged at execution time, but at tool-resolution time the connector scans for these calls and builds a JSON Schema from them.

Signature (positional or named):

```
fromAi(value, description, type, schema, options)
```

- **value** (required) — must be a reference to `toolCall.<paramName>`. The last segment becomes the parameter name the LLM sees.
- **description** (optional) — null or a string constant. This is the one thing the LLM has to understand what value to provide — be explicit.
- **type** (optional) — `"string"` (default), `"number"`, `"boolean"`, `"array"`, `"object"`. Must be a string constant.
- **schema** (optional) — a FEEL context constant for a JSON Schema fragment (e.g., enum values, item types).
- **options** (optional) — e.g. `{required: false}` for optional parameters.

```xml
<!-- Simplest form: just declare a parameter -->
<zeebe:input source="=fromAi(toolCall.url)" target="url" />

<!-- With description and type -->
<zeebe:input
  source='=fromAi(toolCall.firstNumber, "The first number.", "number")'
  target="firstNumber" />

<!-- Inside an interpolated URL -->
<zeebe:input
  source='="https://api.example.com/customers/" + fromAi(toolCall.id, "Customer ID", "string")'
  target="url" />

<!-- With an enum schema -->
<zeebe:input
  source='=fromAi(toolCall.documentType, "The document type", "string", { enum: ["invoice", "receipt", "contract"] })'
  target="documentType" />

<!-- Optional parameter via named args -->
<zeebe:input
  source='=fromAi(value: toolCall.note, description: "Optional note", options: { required: false })'
  target="note" />

<!-- Inside a JSON body — multiple fromAi calls in one expression -->
<zeebe:input
  source='={"to": fromAi(toolCall.recipient, "Recipient email", "string"), "subject": fromAi(toolCall.subject, "Email subject", "string"), "body": fromAi(toolCall.body, "Email body", "string")}'
  target="body" />
```

`fromAi()` is valid in any input mapping — service task ioMapping, script task expression, user task ioMapping, and inside connector-template-provided input fields (which are also input mappings under the hood).

## toolCallResult — Returning Output to the Agent

When a tool completes, the connector reads the variable named `toolCallResult` from the tool's scope and forwards it to the LLM as the tool-call response. The rule is about **scope**, not which activity sets it:

- **Single-activity tool** — the activity itself sets `toolCallResult` (via a result expression / result variable / output mapping / script result variable).
- **Sub-flow tool** (root is a `bpmn:subProcess` containing further activities) — any activity inside the sub-flow can set `toolCallResult`. Typically the last meaningful activity does — e.g., the receive/transform step at the end of a send-then-wait pattern. BPMN variable scoping propagates the value to the sub-process scope when it completes.

Ways to set `toolCallResult` depending on the activity type:

- **Connector with result expression**: `value="={toolCallResult: response.body}"` (or any FEEL shape).
- **Connector with result variable**: name the result variable `toolCallResult`.
- **Output mapping**: `<zeebe:output source="=someValue" target="toolCallResult" />`.
- **Script task**: `<zeebe:script expression="..." resultVariable="toolCallResult" />`.

The value can be primitive (string, number) or a complex FEEL context — it'll be serialized to JSON before being sent to the LLM.

If `toolCallResult` is **missing or empty** at the end of the tool's execution, the agent doesn't stall: the connector sends a generic "tool executed successfully without returning a result" message to the LLM. The LLM then has no useful data to reason about and may make worse decisions on the next turn. Always set `toolCallResult` meaningfully somewhere in the tool flow.

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

Patterns:

- **Static prompt**: `="You are ..."`. The `=` is mandatory even for plain text.
- **Variable interpolation**: `="Customer " + customerId + " reports: " + issue`. `+` coerces scalars to string.
- **Feedback-loop prompt**: `=if (is defined(followUpInput)) then followUpInput else initialUserInput`. Used when looping back into the agent with user follow-up — see "Response interaction" below.

For long, structured prompts, build the string in a script task upstream and pass it in via a variable — keeps the inline FEEL legible.

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

## Sub-Flow as a Tool

A tool can be a multi-step sub-process when the operation has internal sequencing (e.g., send-then-wait, fetch-then-transform, or a small business workflow). The LLM sees only the sub-process root — the steps inside are invisible.

`toolCallResult` can be written by any activity inside the sub-flow, not necessarily the first or last one. The variable just needs to exist in the sub-process scope when the sub-process completes. In the example below, the final transform step writes it:

```xml
<bpmn:subProcess id="SendCustomerEmail" name="Send email to customer">
  <bpmn:documentation>Send an email to the customer and record that it was sent. Use this when the resolution should be communicated by email.</bpmn:documentation>
  <bpmn:startEvent id="SendStart" />
  <bpmn:sequenceFlow sourceRef="SendStart" targetRef="ComposeEmail" />

  <bpmn:serviceTask id="ComposeEmail" name="Compose and send">
    <bpmn:extensionElements>
      <zeebe:taskDefinition type="io.camunda:http-json:1" />
      <zeebe:ioMapping>
        <zeebe:input
          source='={"to": fromAi(toolCall.recipient, "Recipient", "string"), "subject": fromAi(toolCall.subject, "Subject", "string"), "body": fromAi(toolCall.body, "Body", "string")}'
          target="body" />
        <!-- method, url, etc. -->
      </zeebe:ioMapping>
      <zeebe:taskHeaders>
        <zeebe:header key="resultExpression" value="={emailResponse: response.body}" />
      </zeebe:taskHeaders>
    </bpmn:extensionElements>
  </bpmn:serviceTask>
  <bpmn:sequenceFlow sourceRef="ComposeEmail" targetRef="RecordSent" />

  <bpmn:scriptTask id="RecordSent" name="Build tool result">
    <bpmn:extensionElements>
      <zeebe:script
        expression='={sent: true, messageId: emailResponse.id, sentAt: now()}'
        resultVariable="toolCallResult" />
    </bpmn:extensionElements>
  </bpmn:scriptTask>
  <bpmn:sequenceFlow sourceRef="RecordSent" targetRef="SendEnd" />

  <bpmn:endEvent id="SendEnd" />
</bpmn:subProcess>
```

The first activity (`ComposeEmail`) writes an intermediate variable (`emailResponse`); the second activity (`RecordSent`) shapes the final tool result and writes `toolCallResult`. Either step could have written `toolCallResult` directly — the agent only sees the value that exists in scope when the sub-process completes.

For tools that wait on an external callback (chat reply, webhook, async approval), the same pattern applies — the sub-process internally does a send step that captures a correlation key, then an intermediate catch event that waits for the corresponding message and sets `toolCallResult` from the inbound payload. The webhook connector docs in **camunda-connectors** cover the catch-event side; verify field names against the current connector template before relying on a specific shape.

## Pitfalls

These are non-obvious failure modes the lint loop will not catch.

- **Tool has an incoming sequence flow** — it stops being a tool and becomes a regular flow step. The tool's ROOT node must have no incoming flow. Internal activities inside a sub-flow tool can (and do) have incoming flows — that's how the sub-flow works.
- **Tool name confusion** — the LLM-visible tool name is the BPMN **`id`** (e.g., `LookupCustomer`), not the `name` attribute. Use descriptive PascalCase IDs.
- **Missing or empty `toolCallResult` at sub-process completion** — for a sub-flow tool, ensure that at least one activity inside the sub-flow sets `toolCallResult`. A missing value yields a generic "tool succeeded with no result" message to the LLM and degrades the next turn.
- **`bpmn:subProcess` instead of `bpmn:adHocSubProcess` for the agent host** — the connector binds to `bpmn:adHocSubProcess` only. (Inner sub-flow tools ARE plain `bpmn:subProcess` — that's correct.)
- **Bare-string prompts** — both system and user prompts are FEEL. Even literals must be `="..."`.
- **Number-in-string FEEL** — concatenating a number into a URL or message requires `string(x)`; `+` between a string and an un-coerced number fails. Cross-ref **camunda-feel** § type coercion.
- **Empty ad-hoc subprocess** — at least one tool activity is required by BPMN semantics; an agent with no tools is rejected.
- **Hyphenated memory storage type** — `in-process`, `camunda-document`, `custom`. Not camelCase.
- **Hand-coded template internals** — the AI Agent template has many provider-specific fields and they evolve. Apply via `c8 element-template apply --set` rather than writing the input mappings by hand.
- **No `maxModelCalls`** — without a cap, a confused agent will iterate. Always set it to a finite value.

## Closing Step

Run the BPMN lint loop (see **camunda-bpmn**) before declaring the agent process done:

```bash
c8 bpmn lint process.bpmn
```

Lint catches structural BPMN problems but does not validate connector-template inputs. After lint is clean, verify by hand:

- Host element is `bpmn:adHocSubProcess` with the AI Agent template applied.
- Every tool's root node has no incoming sequence flow and has a `<bpmn:documentation>` element.
- Every tool's flow ends with `toolCallResult` set in scope (single-activity tool sets it directly; sub-flow tool sets it on some inner activity).
- Both prompts start with `=`.
- `data.limits.maxModelCalls` is set.
- API keys are pulled from `{{secrets.*}}`, not literal values.
