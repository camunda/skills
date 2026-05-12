---
name: camunda-ai-agent
description: Models and configures AI agents in Camunda 8 BPMN — the AI Agent connector (Sub-process and Task variants) running tools modeled as BPMN activities, with fromAi() parameters, system/user prompt FEEL strings, tool descriptions, and agent context for feedback loops. Use when creating, editing, or debugging an agentic AI process: an LLM that calls tools modeled as BPMN activities.
---

# Camunda AI Agent

Build agentic AI processes in Camunda 8.8+: an LLM driver (the AI Agent connector) calling tools modeled as BPMN activities inside an ad-hoc subprocess. Covers shape, prompts, tool modeling with `fromAi()`, the two implementation variants, and the feedback-loop concept.

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

## Two Implementations

The AI Agent ships in two variants. Pick before modeling.

| Variant | When to use | Where it lives |
|---|---|---|
| **AI Agent Sub-process** (recommended) | Most use cases. Tool feedback loop is handled internally — you don't model it. Supports event subprocesses inside the agent. | Element template applied to a `bpmn:adHocSubProcess` (job-worker implementation). |
| **AI Agent Task** | When you need explicit control over the feedback loop (auditing tool calls, pre/post-processing, or a one-shot LLM call with no tools). | Element template applied to a `bpmn:serviceTask`, paired with a separate multi-instance `bpmn:adHocSubProcess` and an explicit BPMN loop. |

The rest of this skill defaults to the Sub-process variant. The Task variant is covered briefly at the end.

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

## The BPMN Shape (Sub-process Variant)

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

- The element type must be `bpmn:adHocSubProcess`. A regular `bpmn:subProcess` or a service task will not host the Sub-process variant of the connector.
- A tool activity is **a root node with no incoming sequence flow** and **not a boundary event**. An incoming flow turns the node into a regular flow step and the agent never sees it.
- The ad-hoc subprocess must contain **at least one activity** — BPMN semantics; an empty agent is rejected.
- Tools should write their result to a variable named `toolCallResult` (see below).

## Defining Tools

Three things determine whether the LLM picks a tool correctly:

1. **Tool name** — the **activity ID** in the ad-hoc subprocess (e.g., `LookupCustomer`, `GetCurrentWeather`). The connector uses the BPMN `id`, not the human-facing `name` attribute, as the tool name passed to the LLM. Pick descriptive IDs.

2. **Tool description** — the value of `<bpmn:documentation>` on the activity. If documentation is missing, the connector falls back to the activity's `name` attribute, but **always set documentation explicitly**. Strong descriptions say what the tool does, when to use it, when not to, and what it returns:

   > "Look up a customer by ID. Returns the customer's name, tier, and account status. Call this when the user mentions a customer ID or name. Do not call for anonymous queries."

3. **Input schema** — derived automatically from `fromAi()` calls inside the activity's input mappings (see next section). No `fromAi()` calls → empty schema → the LLM can't pass parameters.

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

Every tool should write its result to a variable named `toolCallResult`. The connector collects these and passes them back to the LLM as tool-call responses.

Ways to set `toolCallResult` depending on tool type:

- **Connector with result expression**: `value="={toolCallResult: response.body}"` (or any FEEL shape).
- **Connector with result variable**: name the result variable `toolCallResult`.
- **Output mapping**: `<zeebe:output source="=someValue" target="toolCallResult" />`.
- **Script task**: `<zeebe:script expression="..." resultVariable="toolCallResult" />`.

The value can be primitive (string, number) or a complex FEEL context — it'll be serialized to JSON before being sent to the LLM.

If `toolCallResult` is **missing or empty**, the agent doesn't stall: the connector sends a generic "tool executed successfully without returning a result" message to the LLM. The LLM then has no useful data to reason about and may make worse decisions on the next turn. Always set `toolCallResult` meaningfully.

For the Task variant (multi-instance ad-hoc subprocess), define a local input mapping on the ad-hoc subprocess that creates `toolCallResult` as a local variable — this prevents interference between parallel tool calls.

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

With the Sub-process variant, the feedback loop is **internal**: the agent job worker repeatedly calls the LLM, activates the tools it chose, collects results, and re-prompts until the LLM produces a final response or `maxModelCalls` is reached. You model only the tools, not the loop.

With the Task variant, the loop is **explicit in the BPMN**: a multi-instance ad-hoc subprocess runs the tools, and an exclusive gateway routes back to the AI Agent task while `agent.toolCalls` is non-empty. The Task example in the official docs is the canonical reference.

## Response Interaction (User Feedback Loop)

Independent of the tool loop, you may want a user to review or amend the agent's final response and bounce it back in. For example, a user task collects a `followUpInput` variable; a flow routes back to the agent; the user-prompt FEEL switches between the initial and follow-up input:

```
data.userPrompt.prompt = =if (is defined(followUpInput)) then followUpInput else initialUserInput
```

The agent context (memory of the prior conversation) is preserved across re-entries by passing the agent's previous result back in:

- **Task variant** — set `Agent context = agent.context`, `Result variable = agent`. The connector reads `agent.context` on entry and writes the new state to `agent` on exit.
- **Sub-process variant** — the context handling is internal; verify against the [Sub-process docs](https://docs.camunda.io/docs/components/connectors/out-of-the-box-connectors/agentic-ai-aiagent-subprocess/) for the current configuration field.

## Limits and Memory

- `data.limits.maxModelCalls` — caps the number of LLM calls per agent execution. Always set it (5–20 is a typical starting range); without a sensible cap a misbehaving prompt can rack up cost. There is no time-based limit.
- `data.memory.contextWindowSize` — caps how many prior messages the agent replays to the LLM (default 20). Smaller saves tokens, larger preserves more context.
- `data.memory.storage.type` — `in-process` (default), `camunda-document` (offload to the Camunda Document store when context grows past variable size limits), or `custom`. Use the hyphenated form.

## Sub-Flow as a Tool

A tool can be a multi-step sub-process when the operation has internal sequencing (e.g., send-then-wait, fetch-then-transform, or a small business workflow). The LLM sees only the sub-process root — the steps inside are invisible.

```xml
<bpmn:subProcess id="SendCustomerEmail" name="Send email to customer">
  <bpmn:documentation>Send an email to the customer and record that it was sent. Use this when the resolution should be communicated by email.</bpmn:documentation>
  <bpmn:startEvent id="SendStart" />
  <bpmn:sequenceFlow sourceRef="SendStart" targetRef="ComposeEmail" />
  <bpmn:serviceTask id="ComposeEmail" name="Compose">
    <bpmn:extensionElements>
      <zeebe:taskDefinition type="io.camunda:http-json:1" />
      <zeebe:ioMapping>
        <zeebe:input
          source='={"to": fromAi(toolCall.recipient, "Recipient", "string"), "subject": fromAi(toolCall.subject, "Subject", "string"), "body": fromAi(toolCall.body, "Body", "string")}'
          target="body" />
        <!-- method, url, etc. -->
      </zeebe:ioMapping>
      <zeebe:taskHeaders>
        <zeebe:header key="resultExpression" value="={toolCallResult: response.body}" />
      </zeebe:taskHeaders>
    </bpmn:extensionElements>
  </bpmn:serviceTask>
  <!-- more steps as needed -->
  <bpmn:endEvent id="SendEnd" />
</bpmn:subProcess>
```

For tools that wait on an external callback (chat reply, webhook, async approval), the same pattern applies — the sub-process internally does a send step that captures a correlation key, then an intermediate catch event that waits for the corresponding message. The webhook connector documentation in **camunda-connectors** covers the catch-event side; verify field names against the current connector template before relying on a specific shape.

## The Task Variant — Quick Notes

If the Sub-process variant doesn't fit (you need to audit tool calls, pre-/post-process them, or run the agent without any tools), use the Task variant:

1. Apply the AI Agent **Task** template to a `bpmn:serviceTask`.
2. Add a separate `bpmn:adHocSubProcess` configured as **parallel multi-instance** with:
   - Input collection: `=agent.toolCalls`
   - Input element: `toolCall`
   - Output collection: `toolCallResults`
   - Output element: `={id: toolCall._meta.id, name: toolCall._meta.name, content: toolCallResult}`
   - Active elements collection: `=[toolCall._meta.name]`
3. Configure the AI Agent Task with **Ad-hoc sub-process ID** pointing at that subprocess, and **Tool call results** = `=toolCallResults`.
4. Model the loop explicitly: agent task → exclusive gateway (`not(agent.toolCalls = null) and count(agent.toolCalls) > 0`) → ad-hoc subprocess → back to agent task. Default flow exits the loop.
5. Set `Agent context = agent.context` and `Result variable = agent` on the agent task.

Refer to the [Task-variant worked example](https://docs.camunda.io/docs/components/connectors/out-of-the-box-connectors/agentic-ai-aiagent-task-example/) for a full diagram before modelling this from scratch.

## Pitfalls

These are non-obvious failure modes the lint loop will not catch.

- **Tool has an incoming sequence flow** — it stops being a tool and becomes a regular flow step. Tools must be root nodes inside the ad-hoc subprocess.
- **Tool name confusion** — the LLM-visible tool name is the BPMN **`id`** (e.g., `LookupCustomer`), not the `name` attribute. Use descriptive PascalCase IDs.
- **Missing or empty `toolCallResult`** — the LLM receives a generic "tool succeeded with no result" message instead of useful output. Tool selection on later turns degrades.
- **`bpmn:subProcess` instead of `bpmn:adHocSubProcess`** for the Sub-process variant — the connector won't bind to a regular sub-process.
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

- Host element is `bpmn:adHocSubProcess` (Sub-process variant) or service task + multi-instance ad-hoc subprocess (Task variant).
- Every tool is a root node, has a `<bpmn:documentation>`, and writes `toolCallResult`.
- Both prompts start with `=`.
- `data.limits.maxModelCalls` is set.
- API keys are pulled from `{{secrets.*}}`, not literal values.
