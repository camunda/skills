---
name: camunda-process-mgmt
description: |
  Use this skill to deploy BPMN, DMN, and form resources to a Camunda 8 cluster and operate live processes via c8ctl.

  Use for: deploying resources, starting process instances, inspecting running instances, listing or searching definitions and incidents, resolving incidents, completing user tasks, publishing correlation messages, cancelling instances, debugging stuck processes.

  Do not use for: authoring the BPMN, DMN, or form content itself (use camunda-bpmn, camunda-feel, camunda-forms), or installing and configuring c8ctl itself (use camunda-c8ctl).

  **Workflow skill** — operate a live cluster end-to-end. Covers c8ctl deploy, run, watch, list pi, search inc, complete ut, resolve inc, publish msg, cancel pi.
---

# Camunda Process Management

Runtime operations for Camunda 8.8+ clusters via c8ctl: deploy resources, start instances, inspect state, resolve incidents, complete tasks, publish messages, cancel instances. Single skill for everything that happens *after* the model is written.

## Prerequisites

- Camunda 8.8+ cluster (local via c8run, SaaS, or Self-Managed)
- [c8ctl](https://github.com/camunda/c8ctl) CLI installed and a profile configured for the target cluster — see **camunda-c8ctl** for setup

## Cross-References

- **camunda-c8ctl**: Use for c8ctl install, profile management, local cluster operations, and cluster-safety rules
- **camunda-bpmn**: Use for fixing BPMN process issues found during debugging
- **camunda-connectors**: Use for fixing connector configuration issues found during debugging
- **camunda-feel**: Use for diagnosing FEEL evaluation errors (EXTRACT_VALUE_ERROR, CONDITION_ERROR) in incidents
- **camunda-process-test**: Use for testing processes against an embedded Zeebe engine

## Instructions

### Deploying Resources

**Cluster safety — ask before deploying to anything that isn't local c8run.**

The globally-active c8ctl profile might still point at a shared cluster (`prod`, `staging`, customer name, …) from a previous session. A bare `c8ctl deploy process.bpmn` then silently writes there.

- Run `c8ctl which profile` first. If the name suggests a shared environment, confirm with the user before deploying.
- **Always pass `--profile=<name>` explicitly** on `deploy` and other mutating commands (`run`, `cancel`, `resolve`, `complete`, `publish`, `watch`).
- For validation deploys (just running the change once to check it works), prefer `--profile=local` against a running c8run cluster — `c8ctl cluster start` if not running.

See **camunda-c8ctl** for the authoritative cluster-safety rules.

**Example** — deploy a single BPMN file to the local profile:

```bash
c8ctl deploy process.bpmn --profile=local
```

Deploy multiple resources at once (BPMN, DMN, forms):

```bash
c8ctl deploy process.bpmn decision.dmn approval-form.form
```

Deploy an entire directory (recursive):

```bash
c8ctl deploy ./my-project
```

After deploying, verify:

```bash
c8ctl list pd
c8ctl search pd --iname="MyProcess"
```

Each deployment creates a new version of any resource it contains. Use `c8ctl list pd --fields Key,Name,Version` to see versions.

### Starting Process Instances

Create an instance for a deployed process:

```bash
c8ctl create pi --id MyProcess
```

With input variables:

```bash
c8ctl create pi --id MyProcess --variables '{"orderId": "ORD-123", "amount": 1500}'
```

Deploy and start in one step:

```bash
c8ctl run process.bpmn --variables '{"orderId": "ORD-123"}'
```

Start and block until the instance completes (useful for tests / smoke checks):

```bash
c8ctl await pi --id MyProcess --variables '{"orderId": "ORD-123"}'
```

With a custom request timeout:

```bash
c8ctl await pi --id MyProcess --requestTimeout 60000
```

### Watch Mode (Development)

Auto-redeploy on file changes during local development:

```bash
c8ctl watch ./my-project
```

Watches `.bpmn`, `.dmn`, and `.form` files and redeploys on save.

### Inspecting Process Instances

List active instances:

```bash
c8ctl list pi
```

Search by process name (`i` prefix means case-insensitive substring match):

```bash
c8ctl search pi --iprocessDefinitionName="MyProcess"
```

Get instance details with variables:

```bash
c8ctl get pi <instanceKey> --variables
```

Dump variable values for a specific instance (use `--fullValue` to avoid truncation):

```bash
c8ctl search variables --processInstanceKey=<key> --fullValue
```

Retrieve the deployed BPMN XML for a process definition:

```bash
c8ctl get pd <key> --xml
```

### Resolving Incidents

Incidents are the cluster's way of pausing an instance when something fails non-recoverably (FEEL error, missing variable, connector failure, job timeout exceeded retries). Always inspect before resolving.

List active incidents:

```bash
c8ctl list inc
c8ctl search inc --state=ACTIVE
```

Filter by error message:

```bash
c8ctl search inc --ierrorMessage="Connection refused"
```

**Debug workflow** when a process has an incident:

1. **Find the incident** and read the error type + message:

   ```bash
   c8ctl search inc --state=ACTIVE
   ```

2. **Inspect the instance variables** at the failure point:

   ```bash
   c8ctl search variables --processInstanceKey=<key> --fullValue
   ```

3. **Identify root cause**. Common categories:
   - FEEL error (EXTRACT_VALUE_ERROR / CONDITION_ERROR) → cross-ref **camunda-feel** for expression fixes; check for dotted-variable shadowing or null inputs
   - Job worker missing or timing out → check the `<zeebe:taskDefinition type="...">` matches a running worker
   - Connector misconfiguration → cross-ref **camunda-connectors** to fix the element template binding
   - BPMN logic bug → cross-ref **camunda-bpmn** to fix and redeploy

4. **Fix the underlying issue** (BPMN edit, connector reconfig, worker fix, or variable correction).

5. **Resolve the incident** to retry the failed step:

   ```bash
   c8ctl resolve inc <incidentKey>
   ```

Resolving without fixing the root cause just re-triggers the same incident. Always fix first.

### Completing User Tasks

List pending user tasks:

```bash
c8ctl list ut
```

Complete with output variables:

```bash
c8ctl complete ut <taskKey> --variables '{"approved": true, "comments": "Looks good"}'
```

Variable keys must match the form's component `key` values (see **camunda-forms**) — extra keys are ignored; missing required keys block completion downstream.

### Publishing Correlation Messages

Publish a message to wake up a waiting message event in an instance:

```bash
c8ctl publish msg <messageName> --correlationKey=<key> --variables '{"status": "approved"}'
```

The correlation key must match the value resolved from the process's message subscription expression (typically a FEEL expression over a variable, e.g. `=orderId`).

### Cancelling Instances

```bash
c8ctl cancel pi <instanceKey>
```

### JSON Output for Scripting

Switch to structured output globally:

```bash
c8ctl output json
```

Reduce noise by limiting fields:

```bash
c8ctl list pi --fields Key,State,ProcessDefinitionId
c8ctl list pd --fields Key,Name,Version
```

### Troubleshooting

**Deployment fails** — Run `c8ctl bpmn lint process.bpmn` first (see **camunda-bpmn**). Most deploy errors are caught by the linter pre-deploy.

**Process won't start** — Verify the process ID matches a deployed definition (`c8ctl list pd`). Check required input variables.

**Instance hangs at a service task** — No worker is registered for that task type, the worker crashed, or the job timed out beyond max retries. Check `c8ctl list jobs --processInstanceKey=<key>` and confirm a worker process is running for the matching task type.

**Repeated identical incidents** — You're resolving without fixing. Read the error message every time; if it doesn't change, the root cause hasn't been addressed.
