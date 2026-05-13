---
name: camunda-connectors
description: |
  Use this skill to browse, configure, and apply pre-built Camunda connectors (REST, Slack, Kafka, AWS, etc.) via element templates (also known as connector templates).

  Use for: discovering available connector templates, inspecting their properties, applying a template to a service task or message event, configuring input mappings (URLs, request bodies, secrets) and result expressions, understanding the element template schema, debugging connector configuration in BPMN.

  Do not use for: writing free-form REST calls in service tasks (this skill is specifically for templated connectors), or modelling the BPMN structure itself (use camunda-bpmn).

  **Workflow skill** — discover, inspect, then apply. Covers c8ctl element-template search, info, get-properties, apply, get, sync.
---

# Camunda Connectors

Browse and configure pre-built Camunda connectors using element templates. Apply connector configurations to BPMN service tasks for integrations with external systems (REST APIs, Slack, Kafka, AWS, email, databases, etc.).

## Prerequisites

- c8ctl CLI installed and configured (`c8ctl add profile`) — provides `c8ctl element-template` commands

## Cross-References

- **camunda-bpmn**: Use for creating the BPMN process structure (service tasks that host connectors)
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

Read `references/element-template-schema.md` for a comprehensive guide to interpreting template JSON, understanding binding types, conditions, constraints, FEEL support, and how each property maps to BPMN XML.

### Discovering Connectors via Search

**Always discover the template ID via `c8ctl element-template search` rather than guessing or recalling an ID from memory.** Template IDs and versions evolve — the search command reflects what's actually available in the local OOTB catalog.

```bash
c8ctl element-template search "REST"             # find HTTP/REST connectors
c8ctl element-template search "slack"            # find Slack connectors
c8ctl element-template search "kafka"            # find Kafka connectors
c8ctl element-template search "ai agent"         # find the AI Agent connector
c8ctl element-template search "connector" --limit 5   # cap results (default 20)
```

Each result shows the template name, ID (e.g., `io.camunda.connectors.HttpJson.v2`), version, applies-to, engine constraint, and description. The header reads `Showing N of M matches for '<query>'` — if `M > N`, narrow the query or raise `--limit`. Pick the ID that matches your use case.

To refresh the local OOTB cache (rarely needed — done automatically):

```bash
c8ctl element-template sync             # fetch latest catalog
c8ctl element-template sync --prune     # also drop entries that no longer exist upstream
```

#### Common templates (starting points)

For frequently-used connectors, you can skip straight to a search keyword instead of guessing the ID. The exact ID and version still come from `search` — the table below is a navigation hint, not a substitute for it.

| Use case | Search keyword | Typical template family |
|---|---|---|
| Call a REST / HTTP API (outbound) | `REST` or `HTTP` | `io.camunda.connectors.HttpJson.v2` |
| Send Slack message | `slack` | `io.camunda.connectors.Slack.v1` |
| Send / read email (SMTP / IMAP / POP3) | `email` | `io.camunda.connectors.email.v1` |
| Kafka producer (outbound) | `kafka` | `io.camunda.connectors.KAFKA.v1` |
| Kafka consumer (inbound start / intermediate / boundary) | `kafka` | `io.camunda.connectors.inbound.KafkaMessageStart.v1`, `…KafkaIntermediate.v1`, `…KafkaBoundary.v1` |
| Receive a webhook (inbound start / intermediate / boundary) | `webhook` | `io.camunda.connectors.webhook.WebhookConnector.v1`, `…WebhookConnectorIntermediate.v1`, `…WebhookConnectorBoundary.v1` |
| AI Agent (LLM-driven ad-hoc subprocess) | `ai agent` | Sub-process and Task variants — see **camunda-ai-agent** |

For anything not in this table, search first. IDs and versions evolve — the local cache is the source of truth.

### Inspecting a Template

Two complementary commands cover the questions you'll ask before applying:

**`info`** — metadata card. *What is this thing?* (applies-to, engine constraint, description, docs link). Optional; useful when the connector is unfamiliar or you want to confirm it fits the target element type.

```bash
c8ctl element-template info io.camunda.connectors.HttpJson.v2
```

**`get-properties`** — settable properties. *What knobs can I turn?* The default is a cheap condensed view: name + description, grouped. Filter with positional names (shell-style globs supported, quote them) or `--group <id>` for narrower output.

```bash
c8ctl element-template get-properties io.camunda.connectors.HttpJson.v2          # all settable properties
c8ctl element-template get-properties io.camunda.connectors.HttpJson.v2 url method  # named properties only
c8ctl element-template get-properties io.camunda.connectors.HttpJson.v2 'auth*'   # glob filter
c8ctl element-template get-properties io.camunda.connectors.HttpJson.v2 --group endpoint
```

When a property's internal id differs from its binding name (the name `--set` matches), the condensed view annotates the divergence on a continuation line, e.g.:

```
retries                              Number of retries
    [id: retryCount]
```

Here `retries` is the binding name (use this with `--set`); `retryCount` is the template's internal id. `--detailed` shows both explicitly via the `Id` field.

Add `--detailed` for full per-property cards showing **Required**, **FEEL** support, **Active when** (the conditional expression), **Pattern** constraint, **Default**, and **Choices**. Use this when you need to know whether to set a value, prefix it with `=` for FEEL, or which parent property unlocks the property:

```bash
c8ctl element-template get-properties io.camunda.connectors.HttpJson.v2 --detailed authentication.token url
```

**When to use which:**
- For connectors documented in this skill (HTTP REST, Slack), apply directly — property names are obvious.
- For unfamiliar connectors, run `get-properties` (condensed) to scan names + descriptions before applying.
- Use `--detailed <name>` when you need to know whether a property is required, FEEL-supported, or has a condition — or when an `apply --set` call fails.

#### Falling back to raw JSON (last resort)

`info` + `get-properties --detailed` cover essentially every configuration question. **Only reach for raw JSON when c8ctl commands genuinely don't surface what you need** — e.g., inspecting hidden (non-settable) properties, studying schema fields the CLI doesn't render, or authoring a custom template:

```bash
c8ctl element-template get <id> --no-icon    # raw template JSON, base64 icon stripped
```

**Pass `--no-icon` when reading the raw JSON.** Without it, the embedded base64 icon dominates the output and wastes context. Use the c8ctl commands above first; treat raw JSON as the escape hatch, not the default.

### Applying a Template to a BPMN Element

Apply a template to a service task (or other supported element):

```bash
c8ctl element-template apply -i io.camunda.connectors.HttpJson.v2 Task_FetchUser process.bpmn
```

The `<template>` argument can be:
- An OOTB template ID (with optional `@<version>`, e.g., `io.camunda.connectors.HttpJson.v2@13`). Without `@<version>`, the highest version compatible with the BPMN's `executionPlatformVersion` is auto-resolved.
- A local file path (e.g., `./my-custom-template.json`)
- An `https://` URL (GitHub blob URLs are auto-rewritten to raw content)

`-i` modifies the BPMN file directly. Without `-i`, the modified XML is printed to stdout — useful for previews, redirected output, or composing with other tooling:

```bash
c8ctl element-template apply <id> <element> process.bpmn | diff process.bpmn -    # preview the diff
c8ctl element-template apply <id> <element> process.bpmn > new-process.bpmn       # write to a different file
c8ctl element-template apply <id> <element> process.bpmn | c8ctl bpmn lint           # apply and lint in one pipeline
```

Use `-i` for the common "apply and persist" case. Use the pipeable form for previews, dry-runs, or chaining into other tooling.

Apply sets `zeebe:modelerTemplate`, `zeebe:modelerTemplateVersion`, `zeebe:taskDefinition`, default input mappings, and task headers on the target element.

### Setting Property Values at Apply Time

Set values inline using repeated `--set key=value` flags:

```bash
c8ctl element-template apply -i io.camunda.connectors.HttpJson.v2 Task_FetchUser process.bpmn \
  --set method=GET \
  --set url='="https://api.example.com/users/" + string(userId)' \
  --set authentication.type=bearer \
  --set authentication.token='{{secrets.API_TOKEN}}' \
  --set resultExpression='={user: response.body}'
```

Note the `string(userId)` wrapper — `userId` is a number and FEEL does not auto-coerce in arithmetic. Without `string()`, the expression silently evaluates to `null` (the connector then issues a request to `null`). See `camunda-feel` skill, `references/common-patterns.md` § Type Coercion Pitfalls.

`key` matches the template's property binding names — discover them with `get-properties`. When the same name appears on multiple binding types, prefix with `input:`, `output:`, `header:`, `property:`, or `taskDefinition:`:

```bash
--set input:correlationKey='=order.id'
--set header:correlationKey=staticHeaderValue
```

`apply` errors with a helpful list of valid names if you pass an unknown property, and with the qualified-name list if a bare key is ambiguous.

For complex cases (multi-line FEEL expressions, dynamic body templates, etc.) you may still edit the BPMN XML manually after applying. See "Manual XML configuration" below.

### Configuration Workflow

1. **Search first** — `c8ctl element-template search "<keyword>"` to discover the right template ID. Never guess IDs from memory.
2. **Inspect when unfamiliar** — for connectors not documented in this skill, run `c8ctl element-template get-properties <id>` to scan available properties + descriptions. Add `--detailed <name>` when you need required/FEEL/condition details.
3. **Decide on parent values** — authentication type, method, etc. These determine which child properties become active via conditions.
4. **Apply with values** — `c8ctl element-template apply -i <id> <element-id> <bpmn> --set key=value ...`
5. **Skip inactive properties** — do not set values for properties whose conditions are not met (a warning surfaces if you do).
6. **Use FEEL expressions** for dynamic values (`=` prefix for `feel: optional`, always for `feel: required`).
7. **Use secrets** for credentials: `{{secrets.API_KEY}}`.
8. **Validate** with `c8ctl bpmn lint process.bpmn`.

### Example — HTTP REST Connector

```bash
# 1. Discover the template
c8ctl element-template search "REST"
# → io.camunda.connectors.HttpJson.v2 (REST Outbound Connector)

# 2. Apply with values (no inspection needed — HTTP REST property names are obvious)
c8ctl element-template apply -i io.camunda.connectors.HttpJson.v2 Task_FetchUser process.bpmn \
  --set authentication.type=bearer \
  --set authentication.token='{{secrets.API_TOKEN}}' \
  --set method=GET \
  --set url='="https://api.example.com/users/" + string(userId)' \
  --set resultVariable=apiResponse \
  --set resultExpression='={user: response.body}' \
  --set errorExpression='=if response.statusCode >= 400 then bpmnError("HTTP_ERROR", string(response.statusCode)) else null'
```

The resulting BPMN XML:

```xml
<bpmn:serviceTask id="Task_FetchUser" name="Fetch user data"
  zeebe:modelerTemplate="io.camunda.connectors.HttpJson.v2"
  zeebe:modelerTemplateVersion="13">
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

### Manual XML Configuration (fallback)

For complex multi-line FEEL expressions or post-apply tweaks, edit the BPMN XML directly. The bindings to write are described in `references/element-template-schema.md`. Examples:

```xml
<!-- zeebe:input binding -->
<zeebe:input source="{{secrets.API_KEY}}" target="authentication.token" />

<!-- zeebe:taskHeader binding (note: feel:required values must start with =) -->
<zeebe:header key="resultExpression" value="={user: response.body, ts: now()}" />
```

### Secrets

Reference cluster secrets — never hardcode credentials:

```xml
<zeebe:input source="{{secrets.API_KEY}}" target="authentication.token" />
<zeebe:input source="{{secrets.SLACK_OAUTH_TOKEN}}" target="token" />
```

### Placeholder Values

When the actual value is not yet known:
- `TODO_REPLACE_WITH_API_URL` — clearly indicates what to replace
- `PLACEHOLDER_SLACK_CHANNEL` — identifiable placeholder
- Avoid `""`, `"test"`, or `"xxx"` — these are ambiguous

### Best Practices

1. **Use `c8ctl element-template apply`** to apply templates — never manually set `zeebe:modelerTemplate` attributes.
2. **Inspect via c8ctl, not raw JSON.** Use `info` for metadata and `get-properties` (condensed by default; add `--detailed <name>` for required/FEEL/condition cards). Only fall back to `c8ctl element-template get --no-icon` if c8ctl commands don't surface what you need.
3. **Set values via `--set`** when applying — saves a second editing pass.
4. **Only set active properties** — respect conditions; inactive properties surface a warning and are skipped.
5. **Use FEEL for dynamic values** — combine variables and functions with `=` prefix.
6. **Use secrets for credentials** — `{{secrets.MY_SECRET}}`.
7. **Validate after configuration** — `c8ctl bpmn lint process.bpmn`.
8. **Avoid reading full BPMN XML after template application** — template icons are large base64 strings; use Grep for targeted reads.

## References

For detailed reference material, read from `references/`:
- [element-template-schema.md](references/element-template-schema.md) — comprehensive guide to the element template JSON schema: binding types, conditions, constraints, FEEL support, property-to-XML mapping, and step-by-step configuration examples
