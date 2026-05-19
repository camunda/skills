# Element template schema — reader's guide

This file covers what you need to *read* an existing OOTB element template well enough to configure it with `c8ctl element-template apply --set`. For the full authoring schema — every property type, binding type, conditional shape, inbound variant — see `camunda-connectors-development/references/element-template-json.md`.

## Reading a property — decision order

When inspecting a template property (typically via `c8ctl element-template get-properties <id> --detailed <name>`), answer these in order:

1. **Is `type` `Hidden`?** → fixed technical value. Don't override; the template owns it.
2. **Does `constraints.notEmpty` apply?** → the property is required; `apply` will fail without a value.
3. **Does `condition` apply?** → the property is active only when another property equals (or `oneOf`s) a specific value. Set the parent first.
4. **What is `binding.type`?** → determines the BPMN XML the value lands in (`zeebe:input`, `zeebe:taskHeader`, etc. — see the mapping table below).
5. **What is `feel`?** → `required` ⇒ value must start with `=`. `optional` ⇒ plain literal or FEEL. `static` ⇒ raw value, persisted as FEEL automatically (Boolean, Number).
6. **Is there a `value`?** → that's the default. Override only if needed.
7. **Are there `choices`?** → the value must be one of them.

Reach for `--detailed` rather than the condensed listing whenever an `apply --set` call fails or you're unsure about the FEEL prefix.

## Property → BPMN XML mapping

The `binding.type` on each property determines where the value lands in the resulting BPMN XML.

| Template binding | BPMN XML element | Source / target |
|---|---|---|
| `zeebe:input` with `name: "url"` | `<zeebe:input source="..." target="url" />` | user value → `source` |
| `zeebe:output` with `source: "= body"` | `<zeebe:output source="= body" target="..." />` | user value → `target` |
| `zeebe:taskHeader` with `key: "resultExpression"` | `<zeebe:header key="resultExpression" value="..." />` | user value → `value` |
| `zeebe:taskDefinition` with `property: "type"` | `<zeebe:taskDefinition type="..." />` | template-owned, almost always `Hidden` |
| `zeebe:property` with `name: "inbound.type"` | `<zeebe:property name="inbound.type" value="..." />` | inbound; template-owned |

Nested input names use dot notation: `name: "authentication.token"` produces `target="authentication.token"` and the connector deserialises it into a nested object.

When the same name appears across binding types (e.g. an outbound + inbound connector both with `correlationKey`), `--set` accepts a prefix to disambiguate: `input:`, `output:`, `header:`, `property:`, `taskDefinition:`.

## Common task headers

The headers most often set on outbound connector templates:

| Header | Purpose |
|---|---|
| `resultVariable` | Name a process variable that receives the raw connector response |
| `resultExpression` | FEEL expression evaluated against the response; result merged into the process scope |
| `errorExpression` | FEEL expression mapping connector errors to BPMN errors (returns `bpmnError(...)` or `null`) |
| `retryBackoff` | ISO 8601 duration between retries (e.g. `PT5S`) |

Inbound connectors surface `resultVariable` and `resultExpression` under the same **Output mapping** group — the engine writes the event payload into the process scope when the trigger fires, identically to how outbound writes the response.

## Worked example — HTTP REST connector with `apply --set`

```bash
c8ctl element-template apply -i io.camunda.connectors.HttpJson.v2 Task_FetchUser process.bpmn \
  --set authentication.type=bearer \
  --set authentication.token='{{secrets.API_TOKEN}}' \
  --set method=GET \
  --set url='="https://api.example.com/users/" + string(userId)' \
  --set resultVariable=apiResponse \
  --set resultExpression='={user: response.body}' \
  --set errorExpression='=if response.statusCode >= 400 then bpmnError("HTTP_ERROR", string(response.statusCode)) else null'
```

Resulting BPMN (the `data:image/svg+xml;base64,...` icon blob is elided here for readability — leave it in place in the real file):

```xml
<bpmn:serviceTask id="Task_FetchUser" name="Fetch user data"
  zeebe:modelerTemplate="io.camunda.connectors.HttpJson.v2"
  zeebe:modelerTemplateVersion="13"
  zeebe:modelerTemplateIcon="data:image/svg+xml;base64,...">
  <bpmn:extensionElements>
    <zeebe:taskDefinition type="io.camunda:http-json:1" retries="3" />
    <zeebe:ioMapping>
      <zeebe:input source="bearer" target="authentication.type" />
      <zeebe:input source="{{secrets.API_TOKEN}}" target="authentication.token" />
      <zeebe:input source="GET" target="method" />
      <zeebe:input source="=&quot;https://api.example.com/users/&quot; + string(userId)" target="url" />
    </zeebe:ioMapping>
    <zeebe:taskHeaders>
      <zeebe:header key="resultVariable" value="apiResponse" />
      <zeebe:header key="resultExpression" value="={user: response.body}" />
      <zeebe:header key="errorExpression" value="=if response.statusCode &gt;= 400 then bpmnError(&quot;HTTP_ERROR&quot;, string(response.statusCode)) else null" />
    </zeebe:taskHeaders>
  </bpmn:extensionElements>
</bpmn:serviceTask>
```

Validate with `c8ctl bpmn lint process.bpmn` after applying.

## Multi-line FEEL context literal values

For any `feel: required` property that takes a structured value (the REST connector's `body` is the typical case), pass a FEEL **context literal**, not a JSON object:

```bash
c8ctl element-template apply -i <id> <element> process.bpmn \
  --set 'body=={
    orderId: orderId,
    amount: amount
  }'
```

- Keys are unquoted (`{ orderId: ... }`); `{ "orderId": ... }` is rejected by the FEEL parser.
- `--set 'key==<value>'` (compact `==`) is the multi-line-friendly form; `--set key='=<value>'` is the canonical single-line form. Either works.

## Where to look next

- Full element-template authoring schema (property types, all binding types, inbound variants, FEEL features, the field-ordering rule): `camunda-connectors-development/references/element-template-json.md`
- Discovering OOTB templates: the main `SKILL.md` (`c8ctl element-template search` / `info` / `get-properties`)
- Building a *custom* connector template: **camunda-connectors-development**
