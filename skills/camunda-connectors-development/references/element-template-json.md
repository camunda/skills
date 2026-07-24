# Element template JSON schema reference

The element template is the JSON document that gives a connector (or a worker) its Modeler UI. Same schema across Path A (hand-edited customisation of an OOTB template) and Path B (auto-generated from `@ElementTemplate`).

`$schema` declares the shape Modeler validates against:

```json
"$schema": "https://unpkg.com/@camunda/zeebe-element-templates-json-schema/resources/schema.json"
```

## Top-level fields

| Field | Purpose |
|---|---|
| `$schema` | JSON schema URL Modeler validates against |
| `id` | Unique template identifier (reverse-DNS recommended, e.g. `io.example.connector.countries.v1`) |
| `name` | Human-readable template name in the Modeler element picker |
| `version` | Integer version. New versions allow processes to opt in; old versions remain pinned to existing elements |
| `description` | One-line subtitle in the element picker |
| `documentationRef` | URL surfaced as a *Documentation* link in the properties panel |
| `category` | Optional `{ id, name }` for grouping templates in the Modeler picker |
| `appliesTo` | BPMN element types the template can attach to (e.g. `["bpmn:Task"]`, `["bpmn:StartEvent"]`) |
| `elementType` | Concrete element type to morph the host into (e.g. `{ "value": "bpmn:ServiceTask" }`) |
| `icon` | Inline data-URL or relative path for the element icon in Modeler |
| `groups` | Ordered list of property groups (sections in the properties panel) |
| `properties` | Ordered list of property definitions (declaration order matters — see Field ordering) |

## Property structure

```json
{
  "id": "lookupBy",
  "label": "Lookup by",
  "description": "Which REST Countries endpoint to query",
  "type": "Dropdown",
  "group": "lookup",
  "value": "name",
  "feel": "optional",
  "optional": false,
  "tooltip": "All REST Countries endpoints share the /v3.1/<key>/<query> shape",
  "constraints": { "notEmpty": true },
  "condition": { "property": "mode", "equals": "lookup" },
  "binding": { "type": "zeebe:input", "name": "lookupBy" },
  "choices": [
    { "name": "Name",    "value": "name" },
    { "name": "Capital", "value": "capital" }
  ]
}
```

### Property types

| `type` | UI shape |
|---|---|
| `String` | Single-line text input |
| `Text` | Multi-line text area |
| `Boolean` | Checkbox |
| `Dropdown` | Select from `choices` (each `{ name, value }`) |
| `Hidden` | No UI; the connector still receives the bound `value` |

### `feel`

Controls whether the property accepts FEEL expressions:

- `"optional"` — both literal and FEEL accepted. Most fields use this.
- `"required"` — only FEEL (leading `=`) is accepted. Result expressions, error expressions, and computed inputs.

Omit the field if FEEL has no meaning for the property (e.g. a `Boolean`).

### `optional`

- `false` (default) — the field is required to deploy a process using the template.
- `true` — the field can be left blank.

`optional: true` plus `feel: "optional"` is the lightest-touch combination — accepts anything, including absent.

### `constraints`

Validation applied in Modeler at save / deploy time:

```json
"constraints": {
  "notEmpty": true,
  "pattern": {
    "value": "^[a-z0-9-]+$",
    "message": "Lowercase letters, digits, and hyphens only"
  }
}
```

`pattern.message` is the error string Modeler shows on violation. The runtime does *not* re-validate — these are UX-side guards.

### `condition`

Show or hide the property based on another property's value. The conditioned property is hidden (and its value is omitted from the binding) when the condition is false.

```json
"condition": { "property": "authMode", "equals": "bearer" }
```

Multi-value match:

```json
"condition": { "property": "method", "oneOf": ["POST", "PUT", "PATCH"] }
```

The referenced `property` field must be declared *earlier* in the `properties` array — same field-ordering rule as FEEL value references.

### `generatedValue`

Auto-fills the property when the user creates a fresh element. Used for message-name uniqueness on inbound intermediate-catch / boundary events:

```json
"generatedValue": { "type": "uuid" }
```

Without this, two parallel inbound events in the same process would share a message name and collide.

### `tooltip`

Hover text in the Modeler property panel. One sentence; longer prose belongs in `description` (rendered above the field) or `documentationRef`.

## Binding types

The binding writes the property value into the BPMN element XML when the template is applied. The binding type determines *where* the value lands.

| Binding | Shape | Used for |
|---|---|---|
| `zeebe:taskDefinition` | `{ "type": "zeebe:taskDefinition", "property": "type" }` | Outbound connector type (job type). The `value` is the connector's registered type. |
| `zeebe:taskHeader` | `{ "type": "zeebe:taskHeader", "key": "<header>" }` | Static task headers. Standard keys: `resultVariable`, `resultExpression`, `errorExpression`, `retryBackoff`. |
| `zeebe:input` | `{ "type": "zeebe:input", "name": "<var>" }` | Input mappings — values the connector receives as variables. |
| `zeebe:output` | `{ "type": "zeebe:output", "source": "=...", "target": "<var>" }` | Output mappings — emit a value into the process scope (rare; usually done via `resultExpression`). |
| `zeebe:property` | `{ "type": "zeebe:property", "name": "<key>" }` | **Inbound** connector properties (type, config, correlation). |
| `bpmn:Message#property` | `{ "type": "bpmn:Message#property", "name": "name" }` | Inbound message name (intermediate catch, message start, receive task). |
| `bpmn:Message#zeebe:subscription#property` | `{ ..., "name": "correlationKey" }` | Inbound correlation-key FEEL expression for catch/receive variants. |

### Outbound bindings, end to end

A minimal outbound template wires three bindings:

1. `zeebe:taskDefinition` `property: "type"` — value is the connector's registered type (e.g. `io.example.connector.countries:1`). This is the load-bearing line that routes the job to the connector.
2. `zeebe:input` `name: "<var>"` — per-property input variables.
3. `zeebe:taskHeader` `key: "resultExpression"` (and `errorExpression`) — output mapping and error mapping.

### Inbound bindings, end to end

Inbound templates use `zeebe:property` instead of `zeebe:taskDefinition`:

```json
{ "type": "Hidden", "value": "io.example.connector.fxrates:1",
  "binding": { "type": "zeebe:property", "name": "inbound.type" } }
```

For message-correlated variants (intermediate catch event, receive task, message start event), add:

```json
{ "id": "messageName", "label": "Message name", "type": "Hidden",
  "generatedValue": { "type": "uuid" },
  "binding": { "type": "bpmn:Message#property", "name": "name" } },

{ "id": "correlationKey", "label": "Correlation key", "type": "String",
  "feel": "required",
  "binding": { "type": "bpmn:Message#zeebe:subscription#property", "name": "correlationKey" } }
```

The correlation key binds to a FEEL expression that the engine evaluates against process variables; the message name is the deduplication key the engine uses to match events to instances.

## Template variants per BPMN attachment

The same connector usually ships multiple template files, one per BPMN element it can attach to. Each declares its own `appliesTo` + `elementType`:

| Variant | `appliesTo` | `elementType` |
|---|---|---|
| Outbound service task | `["bpmn:Task"]` | `{ "value": "bpmn:ServiceTask" }` |
| Inbound start event | `["bpmn:StartEvent"]` | `{ "value": "bpmn:StartEvent" }` |
| Inbound message start event | `["bpmn:StartEvent"]` | `{ "value": "bpmn:StartEvent", "eventDefinition": "bpmn:MessageEventDefinition" }` |
| Inbound intermediate catch event | `["bpmn:IntermediateCatchEvent"]` | `{ "value": "bpmn:IntermediateCatchEvent" }` |
| Inbound boundary event | `["bpmn:BoundaryEvent"]` | `{ "value": "bpmn:BoundaryEvent" }` |
| Inbound receive task | `["bpmn:ReceiveTask"]` | `{ "value": "bpmn:ReceiveTask" }` |

Modeler offers the template only on matching elements; one connector class can back several templates via the `@ElementTemplate` annotation's per-variant configuration in the Maven plugin.

## Field ordering

> Properties referenced by another property's FEEL `value` or `condition.property` must be declared *earlier* in the `properties` array.

Out-of-order references silently evaluate to `null` at runtime (FEEL) or always-false (condition). Modeler does not flag this. When customising a Path A template, double-check ordering after edits — the OOTB template fetched via `c8ctl element-template get` is ordered correctly, but manual reorders can break it.

The Maven plugin orders by annotation source order; if hand-authored templates need to mix generated and manual sections, put computed `Hidden` properties last.

## Output mapping — `resultVariable` vs. `resultExpression`

The standard *Output mapping* group exposes:

- **`resultVariable`** (`String`, `zeebe:taskHeader` with key `resultVariable`) — name a variable that receives the entire connector return value.
- **`resultExpression`** (`Text`, `feel: "required"`, `zeebe:taskHeader` with key `resultExpression`) — FEEL expression evaluated against the return value; the resulting context is merged into the process scope.

Templates should expose both; users pick one (or neither) per element.

## Error handling — `errorExpression`

```json
{
  "id": "errorExpression",
  "label": "Error expression",
  "type": "Text",
  "group": "errors",
  "feel": "required",
  "binding": { "type": "zeebe:taskHeader", "key": "errorExpression" }
}
```

The FEEL expression receives a context with `error.code` and `error.message` (populated from `ConnectorException`) and returns either `bpmnError(code, message)` or `null`. The element template should pre-populate sensible mappings for documented error codes; users can override.

## Where to look next

- Path A walkthrough (customising an OOTB template): `protocol-connector-templates.md`
- Auto-generating templates from Java annotations: `element-template-generator.md`
- Path B outbound code (where the bindings show up as `@Variable` / `@Header`): `connector-sdk-outbound.md`
- Path B inbound code (where `zeebe:property` bindings show up via `bindProperties`): `connector-sdk-inbound.md`
