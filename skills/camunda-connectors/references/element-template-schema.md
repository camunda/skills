# Element Template Schema Reference

Element templates are JSON files that define how connectors are configured. Understanding the schema is essential for reading templates, knowing what values to provide, and correctly mapping properties to BPMN XML.

## Template Structure Overview

```json
{
  "$schema": "https://unpkg.com/@camunda/zeebe-element-templates-json-schema/resources/schema.json",
  "name": "REST Outbound Connector",
  "id": "io.camunda.connectors.HttpJson.v2",
  "description": "Invoke REST API",
  "version": 12,
  "appliesTo": ["bpmn:Task"],
  "elementType": { "value": "bpmn:ServiceTask" },
  "groups": [ ... ],
  "properties": [ ... ],
  "icon": { "contents": "data:image/svg+xml;base64,..." }
}
```

### Top-Level Fields

| Field | Purpose |
|-------|---------|
| `name` | Human-readable connector name |
| `id` | Unique template identifier (used in `zeebe:modelerTemplate`) |
| `version` | Integer version number (used in `zeebe:modelerTemplateVersion`) |
| `appliesTo` | BPMN element types this template works with (e.g., `bpmn:Task`, `bpmn:StartEvent`) |
| `elementType.value` | The BPMN element type is changed to this when the template is applied (e.g., `bpmn:ServiceTask`) |
| `groups` | Logical groupings for properties in the UI (authentication, endpoint, output, etc.) |
| `properties` | The array of configurable properties — the heart of the template |
| `icon` | SVG/PNG icon (often large base64 — avoid reading into context) |
| `engines` | Minimum Camunda version compatibility (e.g., `{"camunda": "^8.3"}`) |
| `documentationRef` | URL to official connector documentation |

## Properties Array

Each property object in the `properties` array defines one configurable field. The key concept: each property maps a user-facing input to an underlying BPMN XML binding.

### Property Fields

| Field | Required | Description |
|-------|----------|-------------|
| `binding` | Yes | How this property maps to BPMN XML (see Binding Types below) |
| `type` | No | Input type: `String`, `Text`, `Boolean`, `Number`, `Dropdown`, `Hidden` |
| `label` | No | Display label in the properties panel |
| `description` | No | Help text below the input field |
| `value` | No | Default value. If `type` is `Hidden`, this is the fixed value |
| `id` | No | Identifier used by other properties' `condition` references |
| `group` | No | Which group this property appears in |
| `feel` | No | FEEL expression support: `"required"`, `"optional"`, or `"static"` |
| `optional` | No | If `true`, empty values are NOT persisted in XML |
| `constraints` | No | Validation rules (see Constraints below) |
| `condition` | No | Show this property only when a condition is met (see Conditions below) |
| `choices` | No | For `Dropdown` type: array of `{name, value}` pairs |
| `editable` | No | If `false`, the user cannot change this value |

### How to Read a Property

When examining a template property, answer these questions in order:

1. **Is it `Hidden`?** → This is a technical value set automatically. Do not change it. The `value` is fixed.
2. **Does it have `constraints.notEmpty: true`?** → This property is required. A value must be provided.
3. **Does it have a `condition`?** → This property only applies when another property has a specific value.
4. **What is the `binding.type`?** → This determines what BPMN XML element is created (see below).
5. **What is the `feel` value?** → This determines whether the value can/must be a FEEL expression.
6. **Does it have a `value`?** → This is the default. Override only if needed.
7. **Does it have `choices`?** → The value must be one of the listed options.

## Binding Types

The `binding` object is the bridge between the template property and the BPMN XML. Each binding type produces a different XML structure.

### `zeebe:input` — Input Mapping

Creates `<zeebe:input source="[value]" target="[name]" />` inside `<zeebe:ioMapping>`.

```json
{
  "label": "URL",
  "type": "String",
  "feel": "optional",
  "binding": { "type": "zeebe:input", "name": "url" }
}
```

**Result XML:**
```xml
<zeebe:ioMapping>
  <zeebe:input source="https://api.example.com" target="url" />
</zeebe:ioMapping>
```

The `name` in the binding becomes the `target` attribute. The user-provided value (or FEEL expression) becomes the `source` attribute.

**Nested properties** use dot notation: `"name": "authentication.token"` creates `target="authentication.token"`. The connector runtime deserializes this into a nested object.

### `zeebe:output` — Output Mapping

Creates `<zeebe:output source="[source]" target="[value]" />`.

```json
{
  "label": "Result Variable",
  "type": "String",
  "binding": { "type": "zeebe:output", "source": "= body" }
}
```

**Result XML:**
```xml
<zeebe:ioMapping>
  <zeebe:output source="= body" target="response" />
</zeebe:ioMapping>
```

Note the inversion: `binding.source` is fixed (what to extract from task output), and the user provides the `target` (process variable name).

### `zeebe:taskHeader` — Task Header

Creates `<zeebe:header key="[key]" value="[value]" />` inside `<zeebe:taskHeaders>`.

```json
{
  "label": "Result Expression",
  "type": "Text",
  "feel": "required",
  "binding": { "type": "zeebe:taskHeader", "key": "resultExpression" }
}
```

**Result XML:**
```xml
<zeebe:taskHeaders>
  <zeebe:header key="resultExpression" value="={user: response.body}" />
</zeebe:taskHeaders>
```

Common task headers in connectors:
- `resultVariable` — name of process variable to store raw response
- `resultExpression` — FEEL expression to extract specific fields from the response
- `errorExpression` — FEEL expression to throw BPMN errors on failure
- `retryBackoff` — ISO 8601 duration between retries

### `zeebe:taskDefinition` — Task Definition

Sets `<zeebe:taskDefinition type="[value]" />` or retries.

```json
{
  "type": "Hidden",
  "value": "io.camunda:http-json:1",
  "binding": { "type": "zeebe:taskDefinition", "property": "type" }
}
```

**Result XML:**
```xml
<zeebe:taskDefinition type="io.camunda:http-json:1" retries="3" />
```

This is almost always `Hidden` — the task type identifies which connector runtime handles the job. The `property` parameter can be `type` or `retries`.

### `zeebe:property` — Extension Property

Creates `<zeebe:property name="[name]" value="[value]" />`. Used primarily by inbound connectors.

```json
{
  "type": "Hidden",
  "value": "io.camunda:webhook:1",
  "binding": { "type": "zeebe:property", "name": "inbound.type" }
}
```

## Conditions

Properties can be shown/hidden based on other property values. This is how templates handle different modes (e.g., authentication types).

### Simple condition

```json
{
  "label": "Bearer Token",
  "condition": {
    "property": "authentication.type",
    "equals": "bearer"
  }
}
```

This property only appears (and only gets persisted to XML) when `authentication.type` equals `"bearer"`.

### oneOf condition

```json
{
  "label": "Request Body",
  "condition": {
    "property": "method",
    "oneOf": ["POST", "PUT", "PATCH"]
  }
}
```

### allMatch (multiple conditions)

```json
{
  "condition": {
    "allMatch": [
      { "property": "method", "equals": "chat.postMessage" },
      { "property": "data.messageType", "equals": "plainText" }
    ]
  }
}
```

### Why conditions matter for configuration

When setting property values in BPMN XML, only set values for properties whose conditions are met. For example, if `authentication.type` is `"noAuth"`, do NOT set `authentication.token`, `authentication.username`, or `authentication.password` — those properties are inactive and their values would be meaningless.

## Constraints

Validation rules that define what values are acceptable.

```json
{
  "constraints": {
    "notEmpty": true,
    "minLength": 1,
    "maxLength": 255,
    "pattern": {
      "value": "^(=|(http://|https://|secrets|\\{\\{).*$)",
      "message": "Must be a http(s) URL"
    }
  }
}
```

| Constraint | Meaning |
|-----------|---------|
| `notEmpty: true` | Value is required — must not be empty |
| `minLength` / `maxLength` | String length limits |
| `pattern.value` | Regex the value must match |
| `pattern.message` | Error message shown when pattern fails |

### Common patterns in connector templates

- URL: `^(=|(http://|https://|secrets|\\{\\{).*$)` — accepts URLs, FEEL expressions (`=...`), or secrets (`{{secrets.X}}`)
- Numbers: `^\\d+$` — digits only

## FEEL Expression Support

The `feel` field controls how values interact with FEEL:

| Value | Behavior |
|-------|----------|
| `"required"` | Value must be a FEEL expression (prefixed with `=`). Used for `resultExpression`, `errorExpression`, complex mappings. |
| `"optional"` | Value can be a plain string OR a FEEL expression. Used for most input fields (URL, auth tokens, etc.) |
| `"static"` | Value is persisted as FEEL but no expression editor is shown. Used for `Boolean` and `Number` fields. |
| (absent) | For `zeebe:input`/`zeebe:output` bindings, defaults to `"static"`. For others, no FEEL support. |

### Providing values based on `feel`

- **`feel: "required"`**: Always prefix the value with `=`: `={user: response.body}`
- **`feel: "optional"`**: Use plain values for static content (`GET`, `noAuth`), prefix with `=` for dynamic content (`="https://api.example.com/users/" + string(userId)`)
- **`feel: "static"`**: Provide the raw value (e.g., `20`, `true`) — it will be treated as FEEL automatically

## Groups

Groups organize properties into collapsible sections in the properties panel. Common groups across connector templates:

| Group ID | Purpose | Typical Properties |
|----------|---------|-------------------|
| `authentication` | Auth configuration | Token, username/password, OAuth settings |
| `endpoint` | Target configuration | URL, method, headers, query parameters |
| `payload` | Request body | Body content, content type |
| `output` | Response handling | resultVariable, resultExpression |
| `error` | Error handling | errorExpression |
| `retries` | Retry configuration | Retry count, backoff duration |
| `connector` | Template metadata | Hidden version/ID fields |

## Reading a Template: Step-by-Step Workflow

To configure a connector after applying a template:

1. **Read the template JSON** (but avoid the `icon` field — it's a large base64 string)
2. **Identify the groups** to understand the structure
3. **Find the task definition** — the `Hidden` property with `zeebe:taskDefinition` binding tells you the connector type
4. **Identify required properties** — look for `constraints.notEmpty: true` or properties without `optional: true`
5. **Check conditions** — some properties only apply when other properties have specific values. Start with the "parent" dropdown properties (authentication type, method, etc.)
6. **Decide on the parent values first** (e.g., `authentication.type = "bearer"`) — this determines which child properties become active
7. **Set values for active required properties** — use real values, FEEL expressions, or `{{secrets.X}}` for credentials
8. **Set values for active optional properties** as needed
9. **Skip inactive properties** — do not set values for properties whose conditions are not met

## Configuring Properties in BPMN XML

After `c8ctl element-template apply` applies the template, it creates default `zeebe:ioMapping` entries and `zeebe:taskHeaders`. Use `--set key=value` flags at apply time for straightforward configuration, or edit the BPMN XML manually for complex cases.

To inspect what properties are settable on a given template, run:

```bash
c8ctl element-template get-properties <template-id>             # condensed: name + description per property, grouped
c8ctl element-template get-properties <template-id> --detailed  # full cards: Required, FEEL, Active when, Pattern, Default, Choices
```

The condensed default skips `Hidden` properties. `--detailed` is the full per-property card with everything `--set` needs to pick a value.

### Mapping from template property to BPMN XML

| Template Binding | BPMN XML Element | Source/Target |
|-----------------|------------------|---------------|
| `zeebe:input` with `name: "url"` | `<zeebe:input source="..." target="url" />` | User value → `source` |
| `zeebe:output` with `source: "= body"` | `<zeebe:output source="= body" target="..." />` | User value → `target` |
| `zeebe:taskHeader` with `key: "resultExpression"` | `<zeebe:header key="resultExpression" value="..." />` | User value → `value` |
| `zeebe:taskDefinition` with `property: "type"` | `<zeebe:taskDefinition type="..." />` | Fixed by template |

### Example: Configuring an HTTP Connector

Apply with values inline using `c8ctl element-template apply ... --set ...`. The template defines these key properties:

```
authentication.type  → zeebe:input, name="authentication.type"  (Dropdown: noAuth, basic, bearer, apiKey, oauth)
method               → zeebe:input, name="method"               (Dropdown: GET, POST, PUT, DELETE, PATCH)
url                  → zeebe:input, name="url"                  (String, feel: optional, required)
headers              → zeebe:input, name="headers"              (String, feel: required, optional)
body                 → zeebe:input, name="body"                 (Text, feel: optional, condition: method in POST/PUT/PATCH)
resultVariable       → zeebe:taskHeader, key="resultVariable"   (String)
resultExpression     → zeebe:taskHeader, key="resultExpression" (Text, feel: required)
errorExpression      → zeebe:taskHeader, key="errorExpression"  (Text, feel: required)
```

Resulting BPMN XML for a GET request with bearer auth:

```xml
<bpmn:serviceTask id="Task_FetchUser" name="Fetch user data"
  zeebe:modelerTemplate="io.camunda.connectors.HttpJson.v2"
  zeebe:modelerTemplateVersion="12">
  <bpmn:extensionElements>
    <zeebe:taskDefinition type="io.camunda:http-json:1" retries="3" />
    <zeebe:ioMapping>
      <zeebe:input source="bearer" target="authentication.type" />
      <zeebe:input source="{{secrets.API_TOKEN}}" target="authentication.token" />
      <zeebe:input source="GET" target="method" />
      <zeebe:input source="=&quot;https://api.example.com/users/&quot; + string(userId)" target="url" />
      <zeebe:input source="20" target="connectionTimeoutInSeconds" />
      <zeebe:input source="20" target="readTimeoutInSeconds" />
    </zeebe:ioMapping>
    <zeebe:taskHeaders>
      <zeebe:header key="resultVariable" value="apiResponse" />
      <zeebe:header key="resultExpression" value="={user: response.body}" />
      <zeebe:header key="errorExpression" value="=if response.statusCode &gt;= 400 then bpmnError(&quot;HTTP_ERROR&quot;, string(response.statusCode)) else null" />
      <zeebe:header key="retryBackoff" value="PT0S" />
    </zeebe:taskHeaders>
  </bpmn:extensionElements>
</bpmn:serviceTask>
```

### Secrets

Credentials should always use the Camunda secrets syntax rather than hardcoded values:

```xml
<zeebe:input source="{{secrets.SLACK_OAUTH_TOKEN}}" target="token" />
<zeebe:input source="{{secrets.AWS_ACCESS_KEY}}" target="authentication.accessKey" />
```

The `{{secrets.NAME}}` syntax is resolved at runtime by the Camunda platform. The URL constraint pattern `^(=|(http://|https://|secrets|\\{\\{).*$)` explicitly allows this syntax.

### Placeholder Values

When the actual value is not yet known, use clearly identifiable placeholders:

```xml
<!-- Good: clearly indicates what needs to be replaced -->
<zeebe:input source="TODO_REPLACE_WITH_API_URL" target="url" />
<zeebe:input source="TODO_REPLACE_WITH_CHANNEL_ID" target="data.channel" />

<!-- Bad: ambiguous or could be mistaken for real values -->
<zeebe:input source="" target="url" />
<zeebe:input source="test" target="data.channel" />
```
