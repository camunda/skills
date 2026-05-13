# Tool Modeling — XML examples

Worked-out BPMN snippets for the four shapes of AI Agent tool: REST
connector, script task, user task, and multi-step sub-flow. The shapes
themselves and the rules around them live in `SKILL.md`; this file is
purely reference XML you can mirror.

All examples assume the activity is a **root child** of the
`bpmn:adHocSubProcess` (no incoming sequence flow) and that the tool's
description goes in a `<bpmn:documentation>` element.

## REST connector tool

A service task wired to the HTTP connector. The LLM-supplied parameter
(`toolCall.customerId`) is interpolated into the URL via `fromAi()`,
and the response body is written into `toolCallResult` via
`resultExpression`.

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

For real REST connector configuration, apply the HTTP connector template
via `c8ctl element-template apply` (see **camunda-connectors**) — the
snippet above shows the resulting XML shape.

## Script tool

A FEEL script task. Two `fromAi()` calls in the expression auto-derive
two LLM-supplied parameters; `resultVariable="toolCallResult"` returns
the computed value to the agent.

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

## User task tool (human-in-the-loop)

A user task hands the conversation to a human. The human's output is
mapped to `toolCallResult` so the agent sees their answer as the
tool-call response.

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

## Sub-flow tool

When a tool needs internal sequencing (send-then-wait,
fetch-then-transform, a small business workflow), wrap the steps in a
`bpmn:subProcess`. The LLM sees only the sub-process root — its
description, `fromAi()` declarations, and the final `toolCallResult` —
and never sees the internal steps.

`toolCallResult` can be written by any activity inside the sub-flow,
not just the first or last. The variable just needs to exist in the
sub-process scope when the sub-process completes. In the example below,
the first activity writes an intermediate variable (`emailResponse`)
and the second shapes the final tool result.

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

### Async sub-flow (external callback)

For tools that wait on an external callback (chat reply, webhook, async
approval), the same wrapper applies: the sub-process internally does a
send step that captures a correlation key, then an intermediate catch
event that waits for the corresponding message and sets `toolCallResult`
from the inbound payload. The webhook connector docs in
**camunda-connectors** cover the catch-event side; verify field names
against the current connector template before relying on a specific
shape.
