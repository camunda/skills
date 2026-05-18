---
name: camunda-connectors
description: |
  Use this skill to browse, configure, and apply pre-built Camunda connectors (REST, Slack, Kafka, AWS, etc.) via element templates (also known as connector templates).

  Use for: discovering available connector templates, inspecting their properties, applying a template to a service task or message event, configuring input mappings (URLs, request bodies, secrets) and result expressions, understanding the element template schema, debugging connector configuration in BPMN.

  Do not use for: writing free-form REST calls in service tasks (this skill is specifically for templated connectors), or modelling the BPMN structure itself (use camunda-bpmn).

  **Workflow skill** — discover, inspect, then apply. Covers c8ctl element-template search, info, get-properties, apply, get, sync.
---

# Camunda Connectors

Browse and configure pre-built Camunda connectors using element templates. Apply connector configurations to BPMN service tasks and event elements for integrations with external systems (REST APIs, Slack, Kafka, AWS, email, databases, etc.).

## Prerequisites

- c8ctl CLI installed and configured (`c8ctl add profile`) — provides `c8ctl element-template` commands
- **Local OOTB catalog synced** — run `c8ctl element-template sync` **once** before using `search`, `info`, `get-properties`, `get`, or `apply` with an OOTB template ID. Re-run (optionally with `--prune`) to pick up upstream changes. Applying a template from a local file path or `https://` URL bypasses the cache and does not require sync.

## Cross-References

- **camunda-bpmn**: Use for creating the BPMN process structure (service tasks and event elements that host connectors)
- **camunda-feel**: Use for FEEL expressions in connector input/output mappings
- **camunda-process-mgmt**: Use for deploying the configured process to a cluster

## Instructions

### Element Templates

Element templates (also called **connector templates** — the terms are used interchangeably in Camunda's docs and tooling) are JSON files that encapsulate connector configuration. Each template defines:
- The **task type** identifying which connector runtime handles the job
- **Properties** with bindings that map to BPMN XML (input mappings, task headers, etc.)
- **Conditions** controlling which properties are active based on user choices
- **Constraints** validating user input (required fields, URL patterns, etc.)
- **Groups** organizing properties into logical sections (authentication, endpoint, output, error handling)

Read `references/element-template-schema.md` for the binding-types-and-XML-mapping deep dive.

### Discovering Connectors via Search

**Always discover the template ID via `c8ctl element-template search` rather than guessing or recalling an ID from memory.** Template IDs and versions evolve — the search command reflects what's actually available in the local OOTB catalog.

```bash
c8ctl element-template search "REST"             # find HTTP/REST connectors
c8ctl element-template search "slack"            # find Slack connectors
c8ctl element-template search "kafka"            # find Kafka connectors
c8ctl element-template search "connector" --limit 5   # cap results (default 20)
```

Each result shows the template name, ID (e.g. `io.camunda.connectors.HttpJson.v2`), version, `appliesTo`, engine constraint, and description. The header reads `Showing N of M matches for '<query>'` — if `M > N`, narrow the query or raise `--limit`. Pick the ID that matches your use case.

Inbound integrations typically ship as a *family* of templates — one per BPMN element type the inbound event can attach to (message-start event, intermediate-catch event, boundary event, receive task, …). `search` returns each variant; pick the one that matches the BPMN shape you're modelling.

### Inspecting a Template

Two commands cover the questions you'll ask before applying:

- **`c8ctl element-template info <id>`** — metadata card (applies-to, engine constraint, description, docs link). Useful when the connector is unfamiliar.
- **`c8ctl element-template get-properties <id> [<name>...]`** — settable properties (condensed: name + description, grouped). Accepts positional names (shell-style globs work, quote them) and `--group <id>` to narrow. Add `--detailed` for per-property cards showing **Required**, **FEEL**, **Active when**, **Pattern**, **Default**, **Choices** — reach for `--detailed` when an `apply --set` call fails or when you need to know whether to prefix a value with `=`.

```bash
c8ctl element-template get-properties io.camunda.connectors.HttpJson.v2 url method
c8ctl element-template get-properties io.camunda.connectors.HttpJson.v2 --group endpoint
c8ctl element-template get-properties io.camunda.connectors.HttpJson.v2 --detailed authentication.token
```

If a property's internal id differs from its binding name (the name `--set` matches), the condensed view annotates it as `[id: <internal>]` on a continuation line — always use the top-line name with `--set`.

### Applying a Template to a BPMN Element

Apply a template to a service task (or other supported element) — one call produces a fully-configured connector:

```bash
c8ctl element-template apply -i io.camunda.connectors.HttpJson.v2 Task_FetchUser process.bpmn
```

The `<template>` argument can be:
- An OOTB template ID (with optional `@<version>`, e.g. `io.camunda.connectors.HttpJson.v2@13`). Without `@<version>`, the highest version compatible with the BPMN's `executionPlatformVersion` is auto-resolved. **Requires `c8ctl element-template sync` to have run at least once.**
- A local file path (e.g. `./my-custom-template.json`) — no sync required
- An `https://` URL (GitHub blob URLs are auto-rewritten to raw content) — no sync required

`-i` modifies the BPMN file in place. Without `-i`, the modified XML is printed to stdout — useful for previews, redirected output, or composing with other tooling:

```bash
c8ctl element-template apply <id> <element> process.bpmn | diff process.bpmn -    # preview the diff
c8ctl element-template apply <id> <element> process.bpmn > new-process.bpmn       # write to a different file
c8ctl element-template apply <id> <element> process.bpmn | c8ctl bpmn lint        # apply and lint in one pipeline
```

Apply writes `zeebe:modelerTemplate`, `zeebe:modelerTemplateVersion`, `zeebe:modelerTemplateIcon`, `zeebe:taskDefinition`, the `zeebe:input` mappings, and the `zeebe:taskHeaders` onto the element. All of those must stay consistent — `apply` owns them.

### Setting Property Values at Apply Time

Set every value via repeated `--set key=value` flags on the same `apply` call:

```bash
c8ctl element-template apply -i io.camunda.connectors.HttpJson.v2 Task_FetchUser process.bpmn \
  --set method=GET \
  --set url='="https://api.example.com/users/" + string(userId)' \
  --set authentication.type=bearer \
  --set authentication.token='{{secrets.API_TOKEN}}' \
  --set resultExpression='={user: response.body}'
```

Note the `string(userId)` wrapper — `userId` is a number and FEEL does not auto-coerce in string concatenation. Without `string()`, the expression silently evaluates to `null` (the connector then issues a request to `null`). See **camunda-feel** for FEEL type coercion details.

`key` matches the template's property binding names — discover them with `get-properties`. When the same name appears on multiple binding types, prefix with `input:`, `output:`, `header:`, `property:`, or `taskDefinition:`:

```bash
--set input:correlationKey='=order.id'
--set header:correlationKey=staticHeaderValue
```

`apply` errors with a helpful list of valid names if you pass an unknown property, and with the qualified-name list if a bare key is ambiguous.

### Result Mapping — `resultVariable` and `resultExpression`

Connectors expose two properties under the **Output mapping** group that control what gets written back into the process scope when the connector completes:

- **`resultVariable`** — name of a single process variable that receives the raw response. Plain string, no `=` prefix. Use when downstream tasks just need the whole response under one name.
- **`resultExpression`** — FEEL expression evaluated against the response, with its result merged into the process scope. Requires the `=` prefix. Use to extract specific fields, rename them, or compute derived values.

Both can be set together — `resultVariable` captures the raw response, `resultExpression` shapes named variables alongside it. **If neither is set, the response is discarded** and downstream tasks see no new variables from this connector.

```bash
--set resultVariable=apiResponse \
--set resultExpression='={user: response.body.user, status: response.statusCode}'
```

The same mechanism applies to **inbound connectors** — e.g. the Slack inbound connector surfaces `resultVariable` + `resultExpression` under the same Output mapping group. The engine writes the incoming event payload into the process scope when the trigger fires, identically to how outbound writes the response when the service task completes.

### Example — HTTP REST Connector

```bash
# 1. Discover the template
c8ctl element-template search "REST"
# → io.camunda.connectors.HttpJson.v2 (REST Outbound Connector)

# 2. Apply with all values in one call
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

After applying, validate with `c8ctl bpmn lint process.bpmn`.

### Common Pitfalls

- **`apply` is the only writer.** It owns `zeebe:modelerTemplate{,Version,Icon}`, `zeebe:taskDefinition`, the `zeebe:input` mappings, and the `zeebe:taskHeaders` — they identify the template and the runtime that handles the job and must stay consistent. Don't hand-edit the BPMN to add, change, or remove connector properties; don't strip the icon attribute. Re-run `apply` with different `--set` values instead.
- **`feel: required` values must start with `=`.** A bare value is treated as a literal string, not a FEEL expression. Confirm with `get-properties --detailed <name>` if unsure.
- **Set only active properties.** Conditional properties (e.g. `authentication.token` only applies when `authentication.type=bearer`) are silently skipped if their gating property isn't set in the same call. Decide the parent value first, then set the children.
- **Outbound and inbound connectors both need `resultVariable` and/or `resultExpression`.** Omitting both means the connector's response is discarded.
- **Use `{{secrets.NAME}}` for credentials.** Never hardcode tokens, API keys, or webhook URLs in `--set`. See **camunda-c8ctl** for the secrets bootstrap on local clusters.
- **For values that are not yet known, use a clear placeholder** like `TODO_REPLACE_WITH_API_URL` or `PLACEHOLDER_SLACK_CHANNEL`. Avoid `""`, `"test"`, or `"xxx"` — those can be mistaken for intended values.

## References

For detailed reference material, read from `references/`:
- [element-template-schema.md](references/element-template-schema.md) — element template JSON schema: binding types, conditions, constraints, FEEL support, property-to-XML mapping
