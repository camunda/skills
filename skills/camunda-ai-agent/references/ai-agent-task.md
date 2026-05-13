# AI Agent Task Variant

The Task variant is the older AI Agent implementation. Reach for it only when the recommended Sub-process variant (see `SKILL.md`) doesn't fit:

- You need to **audit, log, or pre/post-process every tool call** before it executes — possible because the loop is explicit BPMN that you can decorate.
- You need to run the agent as a **one-shot LLM call with no tools at all** — works without an accompanying ad-hoc subprocess.
- You're following an existing process design that was built against the Task variant before the Sub-process variant existed.

For everything else, prefer the Sub-process variant — it has simpler configuration, supports event subprocesses inside the agent, and ships as Camunda's recommended pattern.

## Shape

The Task variant is a `bpmn:serviceTask` with the AI Agent Task template applied, paired with a separate `bpmn:adHocSubProcess` (configured as **parallel multi-instance**) that hosts the tools, plus an explicit gateway loop in the BPMN:

```
[AI Agent service task] → [Gateway: has tool calls?]
                                     │ yes
                                     ▼
                            [ad-hoc subprocess (multi-instance)]
                                     │
                                     └─ loops back to the agent task
                                     │ no (default)
                                     ▼
                                  [continue]
```

The Sub-process variant lives inside one element; the Task variant needs three.

## Configure the multi-instance ad-hoc subprocess

The ad-hoc subprocess must be configured as parallel multi-instance with these exact mappings — they're the contract between the agent task and the tool-execution loop:

- **Input collection**: `=agent.toolCalls`
- **Input element**: `toolCall` (must be exactly this)
- **Output collection**: `toolCallResults`
- **Output element**:
  ```
  ={id: toolCall._meta.id, name: toolCall._meta.name, content: toolCallResult}
  ```
- **Active elements collection**: `=[toolCall._meta.name]`

Add a `bpmn:adHocSubProcess` input mapping that declares `toolCallResult` as a local variable (leave **Variable assignment value** blank). This makes each multi-instance iteration's `toolCallResult` local to that iteration and prevents interference between concurrent tool calls.

## Configure the AI Agent service task

Apply the AI Agent **Task** element template (different from the Sub-process variant template — search for both via `c8ctl element-template search "ai agent"`). Set:

- **Ad-hoc sub-process ID**: the element ID of the ad-hoc subprocess that hosts the tools.
- **Tool call results**: `=toolCallResults` (matches the Output collection above).
- **Agent context**: `agent.context` (default).
- **Result variable**: `agent` (default).
- Provider, model, system prompt, user prompt, limits — same as Sub-process variant; see `SKILL.md` § Applying the AI Agent Connector.

## Model the loop

Wire an exclusive gateway after the AI Agent service task:

- **Yes flow** (loop into the ad-hoc subprocess) — condition: `=not(agent.toolCalls = null) and count(agent.toolCalls) > 0`.
- **No flow** (default, exits the loop) — process continues past the agent.

After the ad-hoc subprocess completes, a sequence flow returns to the AI Agent service task. The agent reads `toolCallResults` and the conversation continues until the LLM stops requesting tool calls.

## Tool authoring

Tool authoring inside the ad-hoc subprocess is identical to the Sub-process variant — tool name comes from the activity ID, description from `<bpmn:documentation>`, parameters from `fromAi()` calls, output via `toolCallResult` (in scope when the tool finishes). See `SKILL.md` § Defining Tools and § toolCallResult.

## When to migrate to the Sub-process variant

If you have an existing Task-variant process and don't need explicit per-tool-call interception, migrating to the Sub-process variant typically removes:

- The ad-hoc subprocess multi-instance configuration block.
- The exclusive gateway and its `agent.toolCalls` condition.
- The loopback sequence flow.
- The explicit `agent.context` / `agent` wiring (handled internally).

The tool activities themselves carry over as-is. The migration mostly deletes orchestration.

## Authoritative reference

- [AI Agent Task connector](https://docs.camunda.io/docs/components/connectors/out-of-the-box-connectors/agentic-ai-aiagent-task/) — full config reference.
- [Example AI Agent Task integration](https://docs.camunda.io/docs/components/connectors/out-of-the-box-connectors/agentic-ai-aiagent-task-example/) — worked example with diagram.
