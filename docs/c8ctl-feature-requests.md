# c8ctl Feature Requests

Missing c8ctl features identified during skills development. These would improve the AI-assisted development experience.

---

## 1. Element Templates: List

**Command**: `c8 element-templates list [--type outbound|inbound] [--search <query>]`

**Description**: List available element templates from the Camunda connector catalog. Support filtering by connector type (outbound/inbound) and text search.

**Why**: AI agents need to browse available connectors to suggest appropriate integrations. Currently requires extracting from an npm package or querying the marketplace API manually.

**Expected output**:
```
NAME                              TYPE       DESCRIPTION
http-json-connector               outbound   REST API calls (GET, POST, PUT, DELETE)
slack-outbound-connector          outbound   Send Slack messages
kafka-outbound-connector          outbound   Publish to Kafka topics
sendgrid-connector                outbound   Send emails via SendGrid
```

**Sources**: `@camunda/connectors-element-templates` npm package or `https://marketplace.cloud.camunda.io/api/v1/ootb-connectors`

---

## 2. Element Templates: Get

**Command**: `c8 element-templates get <template-name> [--output <file>]`

**Description**: Download a specific element template JSON by name. Outputs the template JSON to stdout or a file.

**Why**: AI agents need to read template definitions to understand required properties and configure connectors correctly.

**Expected output**: Complete element template JSON (single object, latest version).

---

## 3. Element Templates: Apply

**Command**: `c8 element-templates apply --diagram <bpmn-file> --element <element-id> --template <template-name> [--output <file>]`

**Description**: Apply an element template to a BPMN element. This is what `element-templates-cli` does today, but integrated into c8ctl for a unified experience.

**Why**: Applying element templates is a critical step in connector configuration. Having it in c8ctl means one tool for everything instead of requiring a separate npm package.

**Reference implementation**: `element-templates-cli` npm package (v0.5)

---

## 4. FEEL Expression Evaluation

**Command**: `c8 evaluate expression '<expression>' [--variables '<json>']`

**Description**: Evaluate a FEEL expression against a set of variables using the cluster's expression evaluation endpoint.

**Why**: AI agents need to validate and debug FEEL expressions during process development. The REST API endpoint exists (`POST /v2/expressions/evaluation`) but there's no c8ctl command for it.

**Expected output**:
```json
{"result": 1150}
```

**REST API**: `POST /v2/expressions/evaluation` with body `{"expression": "=amount * 1.15", "variables": {"amount": 1000}}`

---

## 5. BPMN Validation

**Command**: `c8 bpmn validate <file> [--config <bpmnlintrc>]`

**Description**: Validate a BPMN file for Camunda 8 compatibility. Could integrate bpmnlint with camunda-compat rules.

**Why**: Validation before deployment catches errors early. Currently requires `npx bpmnlint` with separate configuration.

**Alternative**: Could be a c8ctl plugin wrapping bpmnlint, rather than a core feature.

---

## 6. Dry Run for Deployment

**Command**: `c8 deploy <file> --dry-run`

**Description**: Validate a deployment without actually deploying. Returns what would be deployed and any validation errors.

**Why**: Allows AI agents to preview deployment effects safely. Supports the plan-validate-execute pattern recommended for AI agent tooling.
