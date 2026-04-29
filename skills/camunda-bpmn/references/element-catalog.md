# BPMN Element Catalog for Camunda 8

Complete reference for BPMN 2.0 elements supported by Camunda 8 (Zeebe engine).

## Start Events

| Type | XML | When to Use |
|------|-----|-------------|
| None | `<bpmn:startEvent>` | Default single entry point |
| Message | `<bpmn:startEvent><bpmn:messageEventDefinition messageRef="..."/>` | External trigger with correlation |
| Timer | `<bpmn:startEvent><bpmn:timerEventDefinition>` | Scheduled or periodic execution |
| Signal | `<bpmn:startEvent><bpmn:signalEventDefinition>` | Broadcast to all instances (rare) |

**Message Start Event:**
```xml
<bpmn:startEvent id="Start_OrderReceived" name="Order received">
  <bpmn:messageEventDefinition messageRef="Message_Order" />
  <bpmn:outgoing>Flow_1</bpmn:outgoing>
</bpmn:startEvent>
<bpmn:message id="Message_Order" name="order-received" />
```

**Timer Start Event:**
```xml
<bpmn:startEvent id="Start_Daily" name="Daily trigger">
  <bpmn:timerEventDefinition>
    <bpmn:timeCycle xsi:type="bpmn:tFormalExpression">R/PT24H</bpmn:timeCycle>
  </bpmn:timerEventDefinition>
</bpmn:startEvent>
```

Note: Processes with ONLY a timer start event cannot be started manually. Add a second None start event for development/testing.

## End Events

| Type | XML | When to Use |
|------|-----|-------------|
| None | `<bpmn:endEvent>` | Normal completion |
| Error | `<bpmn:endEvent><bpmn:errorEventDefinition errorRef="..."/>` | Throw error to parent |
| Message | `<bpmn:endEvent><bpmn:messageEventDefinition>` | Send message on completion |
| Terminate | `<bpmn:endEvent><bpmn:terminateEventDefinition/>` | Cancel all tokens in scope |

## Intermediate Events

**Intermediate Catch (wait for):**
```xml
<!-- Message catch -->
<bpmn:intermediateCatchEvent id="Event_WaitApproval" name="Approval received">
  <bpmn:messageEventDefinition messageRef="Message_Approval" />
</bpmn:intermediateCatchEvent>

<!-- Timer catch -->
<bpmn:intermediateCatchEvent id="Event_Wait3Days" name="Wait 3 days">
  <bpmn:timerEventDefinition>
    <bpmn:timeDuration xsi:type="bpmn:tFormalExpression">="PT3D"</bpmn:timeDuration>
  </bpmn:timerEventDefinition>
</bpmn:intermediateCatchEvent>
```

**Message correlation** requires a unique correlation key per process instance:
```xml
<bpmn:message id="Message_Approval" name="approval-decision">
  <bpmn:extensionElements>
    <zeebe:subscription correlationKey="=orderId" />
  </bpmn:extensionElements>
</bpmn:message>
```

## Boundary Events

Attached to tasks or subprocesses. Default is interrupting (`cancelActivity="true"`).

```xml
<!-- Interrupting timer boundary (cancels the task after 4 hours) -->
<bpmn:boundaryEvent id="Boundary_Timeout" attachedToRef="Task_Review" cancelActivity="true">
  <bpmn:timerEventDefinition>
    <bpmn:timeDuration xsi:type="bpmn:tFormalExpression">="PT4H"</bpmn:timeDuration>
  </bpmn:timerEventDefinition>
  <bpmn:outgoing>Flow_Escalate</bpmn:outgoing>
</bpmn:boundaryEvent>

<!-- Non-interrupting timer (sends reminder, task continues) -->
<bpmn:boundaryEvent id="Boundary_Reminder" attachedToRef="Task_Review" cancelActivity="false">
  <bpmn:timerEventDefinition>
    <bpmn:timeDuration xsi:type="bpmn:tFormalExpression">="PT1H"</bpmn:timeDuration>
  </bpmn:timerEventDefinition>
  <bpmn:outgoing>Flow_Remind</bpmn:outgoing>
</bpmn:boundaryEvent>

<!-- Error boundary (catches specific error from service task) -->
<bpmn:boundaryEvent id="Boundary_Error" attachedToRef="Task_CallAPI">
  <bpmn:errorEventDefinition errorRef="Error_APIFailed" />
  <bpmn:outgoing>Flow_HandleError</bpmn:outgoing>
</bpmn:boundaryEvent>
<bpmn:error id="Error_APIFailed" name="API Failed" errorCode="API_ERROR" />
```

An empty `<bpmn:errorEventDefinition/>` catches ANY error (wildcard).

## Tasks

### User Task
```xml
<bpmn:userTask id="Task_Review" name="Review application">
  <bpmn:extensionElements>
    <zeebe:userTask />
    <zeebe:formDefinition formId="review-form" />
    <zeebe:assignmentDefinition candidateGroups="reviewers" />
  </bpmn:extensionElements>
</bpmn:userTask>
```

- `<zeebe:userTask/>` is **required** for native user tasks (8.5+). Without it, falls back to deprecated job-based model.
- `formId` must match the `id` field in the `.form` JSON file.
- `candidateGroups` for group assignment (users claim from group). `assignee` for direct assignment.

### Service Task
```xml
<bpmn:serviceTask id="Task_ProcessPayment" name="Process payment">
  <bpmn:extensionElements>
    <zeebe:taskDefinition type="payment-processor" retries="3" />
  </bpmn:extensionElements>
</bpmn:serviceTask>
```

For connectors (REST, Slack, etc.), use the **camunda-connectors** skill to apply element templates instead of manual configuration.

### Script Task
```xml
<bpmn:scriptTask id="Task_Calculate" name="Calculate total">
  <bpmn:extensionElements>
    <zeebe:script expression="=sum(items.price)" resultVariable="orderTotal" />
  </bpmn:extensionElements>
</bpmn:scriptTask>
```

### Business Rule Task
```xml
<bpmn:businessRuleTask id="Task_EvaluateRisk" name="Evaluate risk">
  <bpmn:extensionElements>
    <zeebe:calledDecision decisionId="risk-assessment" resultVariable="riskLevel" />
  </bpmn:extensionElements>
</bpmn:businessRuleTask>
```

DMN file must be deployed alongside the BPMN. `decisionId` matches `<decision id="...">` in the DMN.

## Gateways

### Exclusive Gateway (XOR)
```xml
<bpmn:exclusiveGateway id="Gateway_Decision" name="Approved?" default="Flow_Reject">
  <bpmn:incoming>Flow_In</bpmn:incoming>
  <bpmn:outgoing>Flow_Approve</bpmn:outgoing>
  <bpmn:outgoing>Flow_Reject</bpmn:outgoing>
</bpmn:exclusiveGateway>

<bpmn:sequenceFlow id="Flow_Approve" name="Yes" sourceRef="Gateway_Decision" targetRef="End_Approved">
  <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">=approved = true</bpmn:conditionExpression>
</bpmn:sequenceFlow>
<bpmn:sequenceFlow id="Flow_Reject" name="No" sourceRef="Gateway_Decision" targetRef="End_Rejected" />
```

### Parallel Gateway (AND)
```xml
<!-- Fork -->
<bpmn:parallelGateway id="Gateway_Fork">
  <bpmn:incoming>Flow_In</bpmn:incoming>
  <bpmn:outgoing>Flow_A</bpmn:outgoing>
  <bpmn:outgoing>Flow_B</bpmn:outgoing>
</bpmn:parallelGateway>

<!-- Join (MUST match fork) -->
<bpmn:parallelGateway id="Gateway_Join">
  <bpmn:incoming>Flow_A_Done</bpmn:incoming>
  <bpmn:incoming>Flow_B_Done</bpmn:incoming>
  <bpmn:outgoing>Flow_Out</bpmn:outgoing>
</bpmn:parallelGateway>
```

### Inclusive Gateway (OR)
Same structure as parallel but with conditions on outgoing flows. One or more paths fire. Must also have a matching join.

## Subprocesses

### Embedded Subprocess
```xml
<bpmn:subProcess id="Sub_OrderProcessing" name="Process order">
  <bpmn:startEvent id="Sub_Start" />
  <bpmn:endEvent id="Sub_End" />
  <!-- internal elements and flows -->
</bpmn:subProcess>
```

### Call Activity (reusable subprocess)
```xml
<bpmn:callActivity id="Call_PaymentProcess" name="Execute payment">
  <bpmn:extensionElements>
    <zeebe:calledElement processId="payment-process" propagateAllChildVariables="false" />
  </bpmn:extensionElements>
</bpmn:callActivity>
```

### Event Subprocess
Triggered by events within a parent scope. Must have a start event (message, timer, error, signal).
```xml
<bpmn:subProcess id="EventSub_CancelHandler" triggeredByEvent="true">
  <bpmn:startEvent id="EventSub_Start" isInterrupting="true">
    <bpmn:messageEventDefinition messageRef="Message_Cancel" />
  </bpmn:startEvent>
  <!-- handler logic -->
</bpmn:subProcess>
```

## Multi-Instance

Apply to any task or subprocess for iteration:

```xml
<bpmn:serviceTask id="Task_ProcessItem" name="Process item">
  <bpmn:multiInstanceLoopCharacteristics>
    <bpmn:extensionElements>
      <zeebe:loopCharacteristics inputCollection="=items" inputElement="item"
        outputCollection="results" outputElement="=result" />
    </bpmn:extensionElements>
  </bpmn:multiInstanceLoopCharacteristics>
</bpmn:serviceTask>
```

- `inputCollection`: FEEL expression for the list to iterate
- `inputElement`: Variable name for the current item (available in task scope)
- `outputCollection`: Name for the collected results
- `outputElement`: FEEL expression for each iteration's output
