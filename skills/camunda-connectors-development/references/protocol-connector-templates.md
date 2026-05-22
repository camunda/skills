# Path A — JSON-only template on a protocol connector

Customise an existing protocol connector (REST, SOAP, GraphQL, Kafka, RabbitMQ, AWS SQS/SNS/EventBridge) into a domain-specific template by editing JSON only. No Java, no extra runtime, no separate deployment — the customised template lives in your repo as a single `.json` file.

## When this path applies

The integration is a single call over one of the protocols above, AND you want a polished domain-specific UI in Modeler (named fields, hidden infrastructure, sensible defaults). Multi-step orchestration, proprietary protocols, or non-HTTP/non-messaging I/O require Path B.

The same pattern works for specialising any OOTB connector (not just protocol ones) — see SKILL.md § *Specialising any OOTB template*.

## Canonical workflow

1. **Discover the base template.** `c8ctl element-template search "<keyword>"` to find the protocol connector (e.g. *REST Outbound*), then `c8ctl element-template get <id>` to fetch its JSON. This is the starting point — every property, binding, and default is already shaped correctly for the underlying job worker.
2. **Author the customised template.** Copy the fetched JSON into a new file under `resources/element-templates/` (or wherever your project stores templates). Give it a new `id` and `name`. Hide infrastructure properties (`"type": "Hidden"`), pre-fill them with FEEL, expose only the domain inputs, group them into custom groups.
3. **Validate.** Run `c8ctl element-template apply -i <template> <element-id> <bpmn>` against a test BPMN to confirm the bindings produce the expected XML, and run `c8ctl bpmn lint` on the result.
4. **Hand off.** The `.json` file is the deliverable. The user uploads it to their Modeler project (SaaS) or drops it under `resources/element-templates/` (Desktop) to apply it to elements.

## Hiding infrastructure properties

Properties the consumer should never see — URL, HTTP method, internal headers — get `"type": "Hidden"` with a `value` baked in. The UI no longer renders them, but the connector still receives them at runtime.

```json
{
  "id": "method",
  "type": "Hidden",
  "value": "GET",
  "binding": { "type": "zeebe:taskHeader", "key": "method" }
}
```

Use the same shape to lock the URL down to a single base path, force-set authentication, or set fixed query/header values.

## Pre-filling URL with FEEL

The URL field accepts FEEL expressions (leading `=`) so you can compute it from earlier domain inputs. A REST Countries lookup template that exposes only the lookup mode and the query value:

```json
{
  "id": "url",
  "type": "Hidden",
  "value": "=\"https://restcountries.com/v3.1/\" + lookupBy + \"/\" + query",
  "binding": { "type": "zeebe:taskHeader", "key": "url" }
}
```

`lookupBy` and `query` are domain properties declared elsewhere in the template's `properties` array. The user picks a *lookup mode* (`name` / `capital` / `alpha` / `currency`) from a dropdown and types a *query* string; the connector receives the fully-formed URL.

### URL constraint regex

The URL property in the REST template enforces:

```
^(=|(http://|https://|secrets|\{\{).*$
```

— a FEEL expression (`=...`), an absolute `http://` or `https://` URL, the deprecated `secrets.NAME` form, or a `{{secrets.NAME}}` placeholder. Anything else fails the Modeler-side validation. Preserve this constraint when customising; loosening it lets users save broken templates.

## Field-ordering rule

> Any property whose FEEL `value` references another property must appear *after* the referenced property in the `properties` array.

Out-of-order references silently evaluate to `null` at runtime. The Modeler does not flag this. The `lookupBy` and `query` properties in the REST Countries example must appear *before* the hidden `url` property that references them.

This rule applies to all Path A customisations, all hand-authored templates, and the auto-generated templates from `@ElementTemplate` — though in the auto-generated case the plugin orders properties by annotation source order.

## Suppressing the auth UI

The REST template's `authentication.type` defaults to a `Dropdown` with options like `noAuth`, `basic`, `bearer`, `oauth-client-credentials`. To force one auth type and hide the picker:

```json
{
  "id": "authentication.type",
  "type": "Hidden",
  "value": "bearer",
  "binding": { "type": "zeebe:input", "name": "authentication.type" }
},
{
  "id": "authentication.token",
  "type": "String",
  "label": "API token",
  "value": "{{secrets.MY_API_TOKEN}}",
  "binding": { "type": "zeebe:input", "name": "authentication.token" }
}
```

The user sees the token field only; `noAuth` is the analogous value for unauthenticated APIs.

## Custom groups

Group domain properties into labelled sections so the Modeler's properties panel groups them visually:

```json
{
  "groups": [
    { "id": "lookup", "label": "Country lookup" },
    { "id": "output", "label": "Output mapping" }
  ],
  "properties": [
    {
      "id": "lookupBy",
      "label": "Lookup by",
      "type": "Dropdown",
      "group": "lookup",
      "choices": [
        { "name": "Name",            "value": "name" },
        { "name": "Capital",         "value": "capital" },
        { "name": "ISO 3166-1 code", "value": "alpha" },
        { "name": "Currency",        "value": "currency" }
      ],
      "binding": { "type": "zeebe:input", "name": "lookupBy" }
    },
    {
      "id": "query",
      "label": "Query value",
      "type": "String",
      "group": "lookup",
      "feel": "optional",
      "binding": { "type": "zeebe:input", "name": "query" }
    }
  ]
}
```

The pre-existing *Output mapping* group from the REST template should be kept (or re-declared) so users can still bind `resultVariable` / `resultExpression`.

## Worked example — the full REST Countries template

A minimal but complete customisation:

```json
{
  "$schema": "https://unpkg.com/@camunda/zeebe-element-templates-json-schema/resources/schema.json",
  "name": "Country lookup",
  "id": "io.example.connector.countries.v1",
  "description": "Look up country reference data via the REST Countries API",
  "appliesTo": ["bpmn:Task"],
  "elementType": { "value": "bpmn:ServiceTask" },
  "groups": [
    { "id": "lookup", "label": "Country lookup" },
    { "id": "output", "label": "Output mapping" }
  ],
  "properties": [
    {
      "type": "Hidden",
      "value": "io.camunda:http-json:1",
      "binding": { "type": "zeebe:taskDefinition", "property": "type" }
    },
    {
      "id": "lookupBy",
      "label": "Lookup by",
      "type": "Dropdown",
      "group": "lookup",
      "choices": [
        { "name": "Name",            "value": "name" },
        { "name": "Capital",         "value": "capital" },
        { "name": "ISO 3166-1 code", "value": "alpha" },
        { "name": "Currency",        "value": "currency" }
      ],
      "binding": { "type": "zeebe:input", "name": "lookupBy" }
    },
    {
      "id": "query",
      "label": "Query value",
      "type": "String",
      "group": "lookup",
      "feel": "optional",
      "binding": { "type": "zeebe:input", "name": "query" }
    },
    {
      "type": "Hidden",
      "value": "GET",
      "binding": { "type": "zeebe:input", "name": "method" }
    },
    {
      "type": "Hidden",
      "value": "=\"https://restcountries.com/v3.1/\" + lookupBy + \"/\" + query",
      "binding": { "type": "zeebe:input", "name": "url" }
    },
    {
      "type": "Hidden",
      "value": "noAuth",
      "binding": { "type": "zeebe:input", "name": "authentication.type" }
    },
    {
      "id": "resultVariable",
      "label": "Result variable",
      "type": "String",
      "group": "output",
      "binding": { "type": "zeebe:taskHeader", "key": "resultVariable" }
    },
    {
      "id": "resultExpression",
      "label": "Result expression",
      "type": "Text",
      "group": "output",
      "feel": "required",
      "binding": { "type": "zeebe:taskHeader", "key": "resultExpression" }
    }
  ]
}
```

The user sees: a *Lookup by* dropdown, a *Query value* string field, and the output-mapping group. Everything else is hidden. The connector receives a fully-formed `GET https://restcountries.com/v3.1/name/germany` — without the user knowing it's a REST connector underneath.

The hidden `zeebe:taskDefinition` `type` is what binds the element to the underlying protocol connector (`io.camunda:http-json:1` for the REST connector). Verify the exact `type` value of the protocol connector you're layering on with `c8ctl element-template get-properties <id>` before hard-coding it — it's the load-bearing line.

## Tools that generate templates from API specs

When the OpenAPI / Postman spec for the target system is the starting point, **`congen-cli`** (Postman collection → REST connector template; CLI in the `camunda/connectors` repository, not currently distributed as a standalone binary — verify availability before recommending) can produce a draft template that you then refine using the same JSON edits described above.

## Validating the template

The JSON schema linked via `$schema` lets any JSON-schema-aware editor flag malformed properties. To verify the bindings actually produce the expected BPMN XML, round-trip through `c8ctl`:

```bash
c8ctl element-template apply -i my-template.json <element-id> <bpmn-file>
```

Omit `-i` to print the result to stdout, include `-i` to write back. Confirms the binding writes the expected `zeebe:taskDefinition` + `zeebe:input` + `zeebe:taskHeaders` XML. Follow with `c8ctl bpmn lint` on the resulting BPMN.

## Where to look next

- Element template schema (property types, binding types, FEEL features): `element-template-json.md`
- If Path A doesn't fit (multi-step logic, proprietary protocol, inbound): `connector-sdk-outbound.md` / `connector-sdk-inbound.md`
- Discovering the OOTB catalog you're extending: **camunda-connectors**
