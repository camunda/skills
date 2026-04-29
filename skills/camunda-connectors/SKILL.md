---
name: camunda-connectors
description: Browses, configures, and applies pre-built Camunda connectors (REST, Slack, Kafka, AWS, etc.) via element templates. This skill should be used when adding connector integrations to BPMN service tasks, browsing available connectors, configuring connector properties, or understanding element template schemas.
---

# Camunda Connectors

Browse and configure pre-built Camunda connectors using element templates. Apply connector configurations to BPMN service tasks for integrations with external systems (REST APIs, Slack, Kafka, AWS, email, databases, etc.).

## Prerequisites

- c8ctl CLI installed and configured (`c8 add profile`) — provides `c8 element-template` commands

## Cross-References

- **camunda-bpmn**: Use for creating the BPMN process structure (service tasks that host connectors)
- **camunda-feel**: Use for FEEL expressions in connector input/output mappings
- **camunda-deploy**: Use for deploying the configured process to a cluster

## Instructions

### Element Templates

Element templates are JSON files that encapsulate connector configuration. Each template defines:
- The **task type** identifying which connector runtime handles the job
- **Properties** with bindings that map to BPMN XML (input mappings, task headers, etc.)
- **Conditions** controlling which properties are active based on user choices
- **Constraints** validating user input (required fields, URL patterns, etc.)
- **Groups** organizing properties into logical sections (authentication, endpoint, output, error handling)

Read `references/element-template-schema.md` for a comprehensive guide to interpreting template JSON, understanding binding types, conditions, constraints, FEEL support, and how each property maps to BPMN XML.

### Discovering Connectors via Search

**Always discover the template ID via `c8 element-template search` rather than guessing or recalling an ID from memory.** Template IDs and versions evolve — the search command always reflects what's actually available in the local OOTB catalog.

```bash
c8 element-template search "REST"          # find HTTP/REST connectors
c8 element-template search "slack"         # find Slack connectors
c8 element-template search "kafka"         # find Kafka connectors
c8 element-template search ""              # list all OOTB templates
```

Each result shows the template name, ID (e.g., `io.camunda.connectors.HttpJson.v2`), and version. Pick the ID that matches your use case and pass it to `apply` (and to `list-properties` if the connector's properties aren't obvious).

To refresh the local OOTB cache (rarely needed — done automatically):

```bash
c8 element-template sync             # fetch latest catalog
c8 element-template sync --prune     # also drop entries that no longer exist upstream
```

### Inspecting a Template's Properties (when needed)

`list-properties` is a tool, not a step — only run it when you actually need the schema. Skip it when the user's request maps cleanly to obvious properties (e.g., HTTP REST: `method`, `url`, `authentication.type`; Slack: `method`, `data.channel`, `data.text`, `token`) and you can apply with `--set` directly.

Run it when:
- The connector is unfamiliar and you're not sure which property names exist
- An `apply --set` call fails with an unknown-property or ambiguous-binding error
- You need to understand which properties are required, conditional, or FEEL-only before composing the `--set` flags

```bash
c8 element-template list-properties io.camunda.connectors.HttpJson.v2
```

The output shows settable properties (skipping `Hidden` ones) with their type, FEEL support, conditions, and constraints.

### Applying a Template to a BPMN Element

Apply a template to a service task (or other supported element):

```bash
c8 element-template apply io.camunda.connectors.HttpJson.v2 Task_FetchUser process.bpmn --in-place
```

The `<template>` argument can be:
- An OOTB template ID (with optional `@<version>`, e.g., `io.camunda.connectors.HttpJson.v2@12`)
- A local file path (e.g., `./my-custom-template.json`)
- An https:// URL

`--in-place` modifies the BPMN file directly. Without it, the modified XML is printed to stdout.

This sets `zeebe:modelerTemplate`, `zeebe:modelerTemplateVersion`, `zeebe:taskDefinition`, default input mappings, and task headers.

### Setting Property Values at Apply Time

Set values inline using repeated `--set key=value` flags:

```bash
c8 element-template apply io.camunda.connectors.HttpJson.v2 Task_FetchUser process.bpmn --in-place \
  --set method=GET \
  --set url='="https://api.example.com/users/" + string(userId)' \
  --set authentication.type=bearer \
  --set authentication.token='{{secrets.API_TOKEN}}' \
  --set resultExpression='={user: response.body}'
```

This is the preferred way to configure straightforward properties — it's faster and less error-prone than editing XML by hand.

For complex cases (multi-line FEEL expressions, dynamic body templates, etc.) you may still edit the BPMN XML manually after applying. See "Manual XML configuration" below.

### Configuration Workflow

1. **Search first** — `c8 element-template search "<keyword>"` to discover the right template ID. Never guess IDs from memory.
2. **Decide on parent values** — authentication type, method, etc. These determine which child properties become active via conditions
3. **Apply with values** — `c8 element-template apply <id> <element-id> <bpmn> --in-place --set key=value ...`
4. **Inspect properties only if needed** — run `c8 element-template list-properties <id>` when the connector is unfamiliar or apply fails with an unknown/ambiguous property. Skip otherwise.
5. **Skip inactive properties** — do not set values for properties whose conditions are not met
6. **Use FEEL expressions** for dynamic values (`=` prefix for `feel: optional`, always for `feel: required`)
7. **Use secrets** for credentials: `{{secrets.API_KEY}}`
8. **Validate** with `c8 bpmn lint process.bpmn`

### HTTP REST Connector Example

```bash
# 1. Discover the template
c8 element-template search "REST"
# → io.camunda.connectors.HttpJson.v2 (REST Outbound Connector)

# 2. Apply with values (no list-properties needed — HTTP REST property names are obvious)
c8 element-template apply io.camunda.connectors.HttpJson.v2 Task_FetchUser process.bpmn --in-place \
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
  zeebe:modelerTemplateVersion="12">
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

1. **Use `c8 element-template apply`** to apply templates — never manually set `zeebe:modelerTemplate` attributes
2. **Use `list-properties` only when needed** — for unfamiliar connectors or when an apply call fails with an unknown/ambiguous property. Don't run it as a default step.
3. **Set values via `--set`** when applying — saves a second editing pass
4. **Only set active properties** — respect conditions; inactive properties should not appear in XML
5. **Use FEEL for dynamic values** — combine variables and functions with `=` prefix
6. **Use secrets for credentials** — `{{secrets.MY_SECRET}}`
7. **Validate after configuration** — `c8 bpmn lint process.bpmn`
8. **Avoid reading full BPMN XML after template application** — template icons are large base64 strings; use Grep for targeted reads

## References

For detailed reference material, read from `references/`:
- `references/element-template-schema.md` — comprehensive guide to the element template JSON schema: binding types, conditions, constraints, FEEL support, property-to-XML mapping, and step-by-step configuration examples
