# Path A — JSON-only template on a protocol connector

Customise an existing protocol connector (REST, SOAP, GraphQL, Kafka, RabbitMQ, AWS SQS/SNS/EventBridge) into a domain-specific template by editing JSON only. No Java, no extra runtime, no separate deployment — the customised template lives in your repo as a single `.json` file and is uploaded to Web Modeler.

## When this path applies

The integration is a single call over one of the protocols above, AND you want a polished domain-specific UI in Modeler (named fields, hidden infrastructure, sensible defaults). Multi-step orchestration, proprietary protocols, or non-HTTP/non-messaging I/O require Path B.

## Canonical workflow

1. **Model the call once in Web Modeler.** Drop the OOTB protocol connector (e.g. *REST Outbound*) onto a service task and fill in URL, method, headers, body, auth — everything the call needs.
2. **Save as Template.** Right-click the configured element → *Save as Template* (Web Modeler Desktop and SaaS). Modeler emits a JSON file mirroring the configured connector with the same property structure.
3. **Edit the JSON.** Hide infrastructure properties, pre-fill them with FEEL, expose only the domain inputs, group them into custom groups.
4. **Upload as a template** to the Modeler project (SaaS) or place under `resources/element-templates/` (Desktop), then attach it to elements in a process.

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

The URL field accepts FEEL expressions (leading `=`) so you can compute it from earlier domain inputs. Bake a SWAPI-style example:

```json
{
  "id": "url",
  "type": "Hidden",
  "value": "=\"https://swapi.dev/api/\" + resource + \"/\" + index",
  "binding": { "type": "zeebe:taskHeader", "key": "url" }
}
```

`resource` and `index` are domain properties declared elsewhere in the template's `properties` array. The user picks a *resource* from a dropdown and types an *index*; the connector receives the fully-formed URL.

### URL constraint regex

The URL property in the REST template enforces:

```
^(=|(http://|https://|secrets|\{\{).*$
```

— a FEEL expression (`=...`), an absolute `http://` or `https://` URL, the deprecated `secrets.NAME` form, or a `{{secrets.NAME}}` placeholder. Anything else fails the Modeler-side validation. Preserve this constraint when customising; loosening it lets users save broken templates.

## Field-ordering rule

> Any property whose FEEL `value` references another property must appear *after* the referenced property in the `properties` array.

Out-of-order references silently evaluate to `null` at runtime. The Modeler does not flag this. The `resource` and `index` properties in the SWAPI example must appear *before* the hidden `url` property that references them.

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
    { "id": "endpoint", "label": "Star Wars resource" },
    { "id": "output",   "label": "Output mapping" }
  ],
  "properties": [
    {
      "id": "resource",
      "label": "Resource",
      "type": "Dropdown",
      "group": "endpoint",
      "choices": [
        { "name": "People",    "value": "people" },
        { "name": "Planets",   "value": "planets" },
        { "name": "Starships", "value": "starships" }
      ],
      "binding": { "type": "zeebe:input", "name": "resource" }
    },
    {
      "id": "index",
      "label": "Resource ID",
      "type": "String",
      "group": "endpoint",
      "feel": "optional",
      "binding": { "type": "zeebe:input", "name": "index" }
    }
  ]
}
```

The pre-existing *Output mapping* group from the REST template should be kept (or re-declared) so users can still bind `resultVariable` / `resultExpression`.

## Worked example — the full SWAPI template

A minimal but complete customisation:

```json
{
  "$schema": "https://unpkg.com/@camunda/zeebe-element-templates-json-schema/resources/schema.json",
  "name": "Star Wars API",
  "id": "io.example.connector.swapi.v1",
  "description": "Look up Star Wars resources via the SWAPI REST API",
  "appliesTo": ["bpmn:Task"],
  "elementType": { "value": "bpmn:ServiceTask" },
  "groups": [
    { "id": "endpoint", "label": "SWAPI resource" },
    { "id": "output",   "label": "Output mapping" }
  ],
  "properties": [
    {
      "type": "Hidden",
      "value": "io.camunda:http-json:1",
      "binding": { "type": "zeebe:taskDefinition", "property": "type" }
    },
    {
      "id": "resource",
      "label": "Resource",
      "type": "Dropdown",
      "group": "endpoint",
      "choices": [
        { "name": "People",    "value": "people" },
        { "name": "Planets",   "value": "planets" },
        { "name": "Starships", "value": "starships" }
      ],
      "binding": { "type": "zeebe:input", "name": "resource" }
    },
    {
      "id": "index",
      "label": "Resource ID",
      "type": "String",
      "group": "endpoint",
      "feel": "optional",
      "binding": { "type": "zeebe:input", "name": "index" }
    },
    {
      "type": "Hidden",
      "value": "GET",
      "binding": { "type": "zeebe:input", "name": "method" }
    },
    {
      "type": "Hidden",
      "value": "=\"https://swapi.dev/api/\" + resource + \"/\" + index",
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

The user sees: a *Resource* dropdown, a *Resource ID* string field, and the output-mapping group. Everything else is hidden. The connector receives a fully-formed `GET https://swapi.dev/api/people/1` — without the user knowing it's a REST connector underneath.

The hidden `zeebe:taskDefinition` `type` is what binds the element to the underlying protocol connector (`io.camunda:http-json:1` for the REST connector). Verify the exact `type` value of the protocol connector you're layering on with `c8ctl element-template get-properties <id>` before hard-coding it — it's the load-bearing line.

## Tools that generate templates from API specs

Sometimes the OpenAPI / Postman spec for the target system is the starting point, not Web Modeler. Two tools in the connectors ecosystem produce REST templates from specs:

- **`congen-cli`** — Postman collection → REST connector template. CLI tool in the `camunda/connectors` repository, not currently distributed as a standalone binary. Verify availability before recommending.
- **Web Modeler's OpenAPI/Swagger/Postman generator** — the SaaS / Desktop UI has a *Create from REST API* flow that ingests a spec and produces an initial template.

Both produce a template you then refine using the same JSON edits described above. Treat their output as the *Save as Template* starting point, not a finished artefact.

## Validating the template

Upload to Modeler and apply it to a service task; the Modeler validates the schema and surfaces errors inline. For repo-side validation, the JSON schema linked via `$schema` is the same one Modeler uses — most JSON-schema-aware editors will flag malformed properties without needing to round-trip through Modeler.

To round-trip a template against `c8ctl`:

```bash
c8ctl element-template apply -i my-template.json <element-id> <bpmn-file>
```

prints the resulting BPMN (omit `-i` to print, include `-i` to write back). Confirms the binding writes the expected `zeebe:taskDefinition` + `zeebe:input` + `zeebe:taskHeaders` XML.

## Where to look next

- Element template schema (property types, binding types, FEEL features): `element-template-json.md`
- If Path A doesn't fit (multi-step logic, proprietary protocol, inbound): `connector-sdk-outbound.md` / `connector-sdk-inbound.md`
- Discovering the OOTB catalog you're extending: **camunda-connectors**
