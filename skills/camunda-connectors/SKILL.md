---
name: camunda-connectors
description: Browses, configures, and applies pre-built Camunda connectors (REST, Slack, Kafka, AWS, etc.) via element templates. This skill should be used when adding connector integrations to BPMN service tasks, browsing available connectors, configuring connector properties, or understanding element template schemas.
---

# Camunda Connectors

Browse and configure pre-built Camunda connectors using element templates. Apply connector configurations to BPMN service tasks for integrations with external systems (REST APIs, Slack, Kafka, AWS, email, databases, etc.).

## Prerequisites

- Node.js 18+ (for element-templates-cli and template extraction via npx)

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

### Extracting Templates

Before browsing or applying templates, extract them locally:

```bash
node scripts/extract-templates.js
```

This downloads `@camunda/connectors-element-templates` from npm and extracts the latest version of each template to `~/.camunda/element-templates/`. Cached — subsequent runs are fast.

### Browsing Available Connectors

```bash
ls ~/.camunda/element-templates/
```

Common templates:
- `http-json-connector.json` — REST API calls (GET, POST, PUT, DELETE)
- `slack-outbound-connector.json` — Send Slack messages
- `kafka-outbound-connector.json` — Publish to Kafka topics
- `sendgrid-connector.json` — Send emails via SendGrid
- `aws-s3-connector.json` — AWS S3 operations
- `aws-lambda-connector.json` — Invoke AWS Lambda functions
- `rabbitmq-outbound-connector.json` — Publish to RabbitMQ
- `agenticai-aiagent-job-worker.json` — AI Agent connector

To understand what a connector requires, read its template JSON and inspect the `properties` array. Focus on properties with `constraints.notEmpty: true` (required) and check `condition` fields to understand which properties are active for a given configuration.

### Applying Templates to BPMN Elements

Apply a template using `element-templates-cli`:

```bash
npx -y element-templates-cli@0.5 \
  --diagram process.bpmn \
  --template ~/.camunda/element-templates/http-json-connector.json \
  --element Activity_FetchData \
  --output process.bpmn
```

The CLI sets `zeebe:modelerTemplate`, `zeebe:modelerTemplateVersion`, `zeebe:taskDefinition`, default input mappings, and task headers. Ignore stderr warnings about document imports.

**After applying, configure the template properties** by editing the BPMN XML — see the configuration workflow below.

### Configuration Workflow

1. **Read the template JSON** — understand the property groups and identify required fields
2. **Start with "parent" dropdown properties** — authentication type, method, etc. These determine which child properties become active via conditions
3. **Set required active properties** — those with `constraints.notEmpty: true` whose conditions are met
4. **Set optional properties** as needed
5. **Skip inactive properties** — do not set values for properties whose conditions are not met
6. **Use FEEL expressions** for dynamic values (prefix with `=` for `feel: "optional"`, always for `feel: "required"`)
7. **Use secrets** for credentials: `{{secrets.API_KEY}}`
8. **Validate** with `npx -y bpmnlint@11 process.bpmn`

### HTTP REST Connector Example

```bash
# 1. Apply template
npx -y element-templates-cli@0.5 \
  --diagram process.bpmn \
  --template ~/.camunda/element-templates/http-json-connector.json \
  --element Task_FetchUser \
  --output process.bpmn
```

```xml
<!-- 2. Configure: GET request with bearer token auth -->
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
</zeebe:taskHeaders>
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

1. **Always use the CLI** to apply templates — never manually set `zeebe:modelerTemplate` attributes
2. **Read the template JSON first** — understand the property tree (parent dropdowns → conditional children)
3. **Only set active properties** — respect conditions; inactive properties should not appear in XML
4. **Use FEEL for dynamic values** — combine variables and functions with `=` prefix
5. **Use secrets for credentials** — `{{secrets.MY_SECRET}}`
6. **Validate after configuration** — `npx -y bpmnlint@11 process.bpmn`
7. **Avoid reading full BPMN XML after template application** — template icons are large base64 strings; use Grep for targeted reads

## References

For detailed reference material, read from `references/`:
- `references/element-template-schema.md` — comprehensive guide to the element template JSON schema: binding types, conditions, constraints, FEEL support, property-to-XML mapping, and step-by-step configuration examples
