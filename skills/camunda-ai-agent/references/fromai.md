# fromAi() — full signature and patterns

The `fromAi()` FEEL function tags a value as "the LLM will provide this
at runtime". At execution time it returns its first argument unchanged;
at tool-resolution time the connector scans for these calls and builds
a JSON Schema from them.

`fromAi()` is valid in any input mapping — service task ioMapping,
script task expression, user task ioMapping, and inside
connector-template-provided input fields (which are also input mappings
under the hood).

## Signature

```
fromAi(value, description, type, schema, options)
```

| Argument | Required | Meaning |
|---|---|---|
| `value` | yes | A reference to `toolCall.<paramName>`. The last segment becomes the parameter name the LLM sees. |
| `description` | no | `null` or a string constant. This is the one thing the LLM has to understand what value to provide — be explicit. |
| `type` | no | `"string"` (default), `"number"`, `"boolean"`, `"array"`, `"object"`. Must be a string constant. |
| `schema` | no | A FEEL context constant for a JSON Schema fragment (e.g., enum values, item types). |
| `options` | no | E.g. `{required: false}` for optional parameters. |

Both positional and named-argument forms are accepted.

## Examples

**Simplest form — just declare a parameter**

```xml
<zeebe:input source="=fromAi(toolCall.url)" target="url" />
```

**With description and type**

```xml
<zeebe:input
  source='=fromAi(toolCall.firstNumber, "The first number.", "number")'
  target="firstNumber" />
```

**Interpolated into a URL**

```xml
<zeebe:input
  source='="https://api.example.com/customers/" + fromAi(toolCall.id, "Customer ID", "string")'
  target="url" />
```

**With an enum schema**

```xml
<zeebe:input
  source='=fromAi(toolCall.documentType, "The document type", "string", { enum: ["invoice", "receipt", "contract"] })'
  target="documentType" />
```

**Optional parameter via named args**

```xml
<zeebe:input
  source='=fromAi(value: toolCall.note, description: "Optional note", options: { required: false })'
  target="note" />
```

**Multiple `fromAi()` calls in a single JSON body**

```xml
<zeebe:input
  source='={"to": fromAi(toolCall.recipient, "Recipient email", "string"), "subject": fromAi(toolCall.subject, "Email subject", "string"), "body": fromAi(toolCall.body, "Email body", "string")}'
  target="body" />
```
