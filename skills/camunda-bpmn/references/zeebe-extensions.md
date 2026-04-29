# Zeebe Extensions and Variable Management

Camunda 8 (Zeebe) extends BPMN with the `zeebe` namespace for execution-specific configuration.

## Variable Scopes

Camunda uses a hierarchical scope system:

1. **Process Instance Scope (Root)**: Variables visible to all elements
2. **Element Instance Scope (Child)**: Created by subprocesses, activities with input mappings, multi-instance loops
   - Can access own scope AND all parent scopes
   - Variables shadow parent scope variables with the same name

### Variable Propagation

- **Task completes** → local variables merge into parent scope
- **New variables** are created in root scope by default
- **Existing variables** are updated in the scope where they exist
- **Input mappings** create a child scope with local variables
- **Output mappings** control which variables propagate back (overrides default "merge all" behavior)

## Input/Output Mappings

### Input Mappings

Create local variables in an element's scope BEFORE execution:

```xml
<zeebe:ioMapping>
  <!-- Simple: copy variable -->
  <zeebe:input source="=orderId" target="reference" />

  <!-- Nested property access -->
  <zeebe:input source="=customer.name" target="senderName" />

  <!-- Build nested structure -->
  <zeebe:input source="=customer" target="sender.name" />
  <zeebe:input source="=iban" target="sender.iban" />

  <!-- Static value (no = prefix) -->
  <zeebe:input source="GET" target="method" />

  <!-- FEEL expression -->
  <zeebe:input source="=&quot;https://api.example.com/users/&quot; + string(userId)" target="url" />
</zeebe:ioMapping>
```

### Output Mappings

Control which variables propagate to parent scope AFTER execution:

```xml
<zeebe:ioMapping>
  <!-- Extract specific field -->
  <zeebe:output source="=result.status" target="paymentStatus" />

  <!-- Multiple outputs -->
  <zeebe:output source="=result.transactionId" target="transactionId" />
  <zeebe:output source="=result.amount" target="paidAmount" />

  <!-- Build nested output -->
  <zeebe:output source="=transactionId" target="order.transactionId" />
</zeebe:ioMapping>
```

When output mappings are defined, ONLY mapped variables propagate. Unmapped local variables are discarded.

### Variable Context by Element Type

| Context | Access |
|---------|--------|
| Gateway conditions | Parent scope variables |
| Input mappings (source) | Parent scope variables |
| Output mappings (source) | Local scope variables (created by task) |
| Form default values | Parent scope variables |
| Timer expressions | Parent scope variables |
| Script expressions | Local scope (with input mappings) or parent scope |

## Task Definition

For service tasks with custom job workers:

```xml
<zeebe:taskDefinition type="payment-processor" retries="3" />
```

- `type`: Must exactly match the worker's registered task type (case-sensitive)
- `retries`: Number of retry attempts on failure (default: 3)

## Form Definition

Link user tasks to Camunda Forms:

```xml
<zeebe:userTask />
<zeebe:formDefinition formId="review-form" />
```

- `<zeebe:userTask/>` is **required** for native user tasks (8.5+)
- `formId` must match the `id` field in the corresponding `.form` JSON file
- For embedded forms: `<zeebe:formDefinition formKey="camunda-forms:bpmn:formId" />`

## Assignment Definition

```xml
<zeebe:assignmentDefinition
  assignee="=initiator"
  candidateGroups="finance-team"
  candidateUsers="user1,user2" />
```

- `assignee`: Direct assignment (bypasses claiming)
- `candidateGroups`: Group-based (users claim from group) — preferred
- `candidateUsers`: Comma-separated user IDs

## Task Headers

Key-value pairs passed to job workers:

```xml
<zeebe:taskHeaders>
  <zeebe:header key="resultVariable" value="apiResponse" />
  <zeebe:header key="resultExpression" value="={user: response.body}" />
  <zeebe:header key="errorExpression" value="=if response.statusCode &gt;= 400 then bpmnError(&quot;HTTP_ERROR&quot;, string(response.statusCode)) else null" />
</zeebe:taskHeaders>
```

Common headers for HTTP connector:
- `resultVariable`: Store raw response
- `resultExpression`: FEEL expression to extract specific values
- `errorExpression`: FEEL expression to throw BPMN error on failure

## Script Task

```xml
<zeebe:script expression="=now()" resultVariable="currentTime" />
```

The expression is a FEEL expression. Result is stored in `resultVariable`.

## Called Decision (DMN)

```xml
<zeebe:calledDecision decisionId="risk-assessment" resultVariable="riskLevel" />
```

## Called Element (Call Activity)

```xml
<zeebe:calledElement processId="payment-process" propagateAllChildVariables="false" />
```

Set `propagateAllChildVariables="false"` and use explicit output mappings for cleaner variable management.

## Multi-Instance Loop

```xml
<zeebe:loopCharacteristics
  inputCollection="=items"
  inputElement="item"
  outputCollection="results"
  outputElement="=result" />
```

## Secrets

Reference cluster secrets in connector configurations:

```xml
<zeebe:input source="{{secrets.API_KEY}}" target="authentication.apiKey" />
```

Secrets are resolved at runtime by the Camunda platform. Never hardcode credentials.

## Message Subscription

For message correlation on intermediate catch events:

```xml
<bpmn:message id="Message_1" name="payment-received">
  <bpmn:extensionElements>
    <zeebe:subscription correlationKey="=orderId" />
  </bpmn:extensionElements>
</bpmn:message>
```

The correlation key must be unique per waiting instance to ensure correct routing.
