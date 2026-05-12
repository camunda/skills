---
name: camunda-process-mgmt
description: Deploys BPMN/DMN/forms to a Camunda 8 cluster and manages live processes via c8ctl — starts and inspects instances, resolves incidents, completes user tasks, publishes correlation messages, cancels instances. Use when running, inspecting, debugging, or fixing live Camunda 8 processes.
---

# Camunda Process Management

Runtime operations for Camunda 8.8+ clusters via c8ctl: deploy resources, start instances, inspect state, resolve incidents, complete tasks, publish messages, cancel instances. Single skill for everything that happens *after* the model is written.

## Prerequisites

- Camunda 8.8+ cluster (local via c8run, SaaS, or Self-Managed)
- [c8ctl](https://github.com/camunda/c8ctl) CLI installed and a profile configured for the target cluster — see **camunda-c8ctl** for setup

## Cross-References

- **camunda-c8ctl**: Use for installing c8ctl, configuring profiles, starting a local c8run cluster
- **camunda-bpmn**: Use for fixing BPMN process issues found during debugging
- **camunda-connectors**: Use for fixing connector configuration issues found during debugging
- **camunda-feel**: Use for diagnosing FEEL evaluation errors (EXTRACT_VALUE_ERROR, CONDITION_ERROR) in incidents

## Instructions

### Deploying Resources

Deploy a single BPMN file:

```bash
c8 deploy process.bpmn
```

Deploy multiple resources at once (BPMN, DMN, forms):

```bash
c8 deploy process.bpmn decision.dmn approval-form.form
```

Deploy an entire directory (recursive):

```bash
c8 deploy ./my-project
```

After deploying, verify:

```bash
c8 list pd
c8 search pd --iname="MyProcess"
```

Each deployment creates a new version of any resource it contains. Use `c8 list pd --fields Key,Name,Version` to see versions.

### Starting Process Instances

Create an instance for a deployed process:

```bash
c8 create pi --id MyProcess
```

With input variables:

```bash
c8 create pi --id MyProcess --variables '{"orderId": "ORD-123", "amount": 1500}'
```

Deploy and start in one step:

```bash
c8 run process.bpmn --variables '{"orderId": "ORD-123"}'
```

Start and block until the instance completes (useful for tests / smoke checks):

```bash
c8 await pi --id MyProcess --variables '{"orderId": "ORD-123"}'
```

With a custom request timeout:

```bash
c8 await pi --id MyProcess --requestTimeout 60000
```

### Watch Mode (Development)

Auto-redeploy on file changes during local development:

```bash
c8 watch ./my-project
```

Watches `.bpmn`, `.dmn`, and `.form` files and redeploys on save.

### Inspecting Process Instances

List active instances:

```bash
c8 list pi
```

Search by process name (`i` prefix means case-insensitive substring match):

```bash
c8 search pi --iprocessDefinitionName="MyProcess"
```

Get instance details with variables:

```bash
c8 get pi <instanceKey> --variables
```

Dump variable values for a specific instance (use `--fullValue` to avoid truncation):

```bash
c8 search variables --processInstanceKey=<key> --fullValue
```

Retrieve the deployed BPMN XML for a process definition:

```bash
c8 get pd <key> --xml
```

### Resolving Incidents

Incidents are the cluster's way of pausing an instance when something fails non-recoverably (FEEL error, missing variable, connector failure, job timeout exceeded retries). Always inspect before resolving.

List active incidents:

```bash
c8 list inc
c8 search inc --state=ACTIVE
```

Filter by error message:

```bash
c8 search inc --ierrorMessage="Connection refused"
```

**Debug workflow** when a process has an incident:

1. **Find the incident** and read the error type + message:

   ```bash
   c8 search inc --state=ACTIVE
   ```

2. **Inspect the instance variables** at the failure point:

   ```bash
   c8 search variables --processInstanceKey=<key> --fullValue
   ```

3. **Identify root cause**. Common categories:
   - FEEL error (EXTRACT_VALUE_ERROR / CONDITION_ERROR) → cross-ref **camunda-feel** for expression fixes; check for dotted-variable shadowing or null inputs
   - Job worker missing or timing out → check the `<zeebe:taskDefinition type="...">` matches a running worker
   - Connector misconfiguration → cross-ref **camunda-connectors** to fix the element template binding
   - BPMN logic bug → cross-ref **camunda-bpmn** to fix and redeploy

4. **Fix the underlying issue** (BPMN edit, connector reconfig, worker fix, or variable correction).

5. **Resolve the incident** to retry the failed step:

   ```bash
   c8 resolve inc <incidentKey>
   ```

Resolving without fixing the root cause just re-triggers the same incident. Always fix first.

### Completing User Tasks

List pending user tasks:

```bash
c8 list ut
```

Complete with output variables:

```bash
c8 complete ut <taskKey> --variables '{"approved": true, "comments": "Looks good"}'
```

Variable keys must match the form's component `key` values (see **camunda-forms**) — extra keys are ignored; missing required keys block completion downstream.

### Publishing Correlation Messages

Publish a message to wake up a waiting message event in an instance:

```bash
c8 publish msg <messageName> --correlationKey=<key> --variables '{"status": "approved"}'
```

The correlation key must match the value resolved from the process's message subscription expression (typically a FEEL expression over a variable, e.g. `=orderId`).

### Cancelling Instances

```bash
c8 cancel pi <instanceKey>
```

### JSON Output for Scripting

Switch to structured output globally:

```bash
c8 output json
```

Reduce noise by limiting fields:

```bash
c8 list pi --fields Key,State,ProcessDefinitionId
c8 list pd --fields Key,Name,Version
```

### Troubleshooting

**Deployment fails** — Run `c8 bpmn lint process.bpmn` first (see **camunda-bpmn**). Most deploy errors are caught by the linter pre-deploy.

**Process won't start** — Verify the process ID matches a deployed definition (`c8 list pd`). Check required input variables.

**Instance hangs at a service task** — No worker is registered for that task type, the worker crashed, or the job timed out beyond max retries. Check `c8 list jobs --processInstanceKey=<key>` and confirm a worker process is running for the matching task type.

**Repeated identical incidents** — You're resolving without fixing. Read the error message every time; if it doesn't change, the root cause hasn't been addressed.
