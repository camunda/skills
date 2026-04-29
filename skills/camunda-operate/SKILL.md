---
name: camunda-operate
description: Monitors process instances, resolves incidents, completes user tasks, and publishes messages on a Camunda 8 cluster via c8ctl. This skill should be used when debugging running processes, inspecting incidents, completing tasks, or managing process instance lifecycle.
---

# Camunda Operate

Monitor and debug running processes on a Camunda 8.8+ cluster using c8ctl.

## Prerequisites

- Camunda 8.8+ cluster (local via c8run, SaaS, or Self-Managed)
- [c8ctl](https://github.com/camunda/c8ctl) CLI installed and configured

## Cross-References

- **camunda-deploy**: Use for deploying resources and starting instances
- **camunda-bpmn**: Use for fixing BPMN process issues found during debugging

## Instructions

### Listing Process Instances

List active instances:
```bash
c8 list pi
```

Search by process name:
```bash
c8 search pi --iprocessDefinitionName="MyProcess"
```

Get instance details with variables:
```bash
c8 get pi <instanceKey> --variables
```

Search variables for a specific instance:
```bash
c8 search variables --processInstanceKey=<key> --fullValue
```

### Inspecting Incidents

List all incidents:
```bash
c8 list inc
```

Search incidents by state:
```bash
c8 search inc --state=ACTIVE
```

Search by error message:
```bash
c8 search inc --ierrorMessage="Connection refused"
```

### Debugging Workflow

When a process has incidents:

1. **Find the incident**:
   ```bash
   c8 search inc --state=ACTIVE
   ```

2. **Identify root cause**: Read the error message and error type from the incident output.

3. **Inspect instance variables**:
   ```bash
   c8 search variables --processInstanceKey=<key> --fullValue
   ```

4. **Fix the issue**: This may involve:
   - Fixing the BPMN process (use **camunda-bpmn** skill)
   - Fixing connector configuration (use **camunda-connectors** skill)
   - Updating variables on the instance
   - Redeploying the fixed process (use **camunda-deploy** skill)

5. **Resolve the incident** (retry the failed step):
   ```bash
   c8 resolve inc <incidentKey>
   ```

### Completing User Tasks

List pending user tasks:
```bash
c8 list ut
```

Complete a user task with variables:
```bash
c8 complete ut <taskKey> --variables '{"approved": true, "comments": "Looks good"}'
```

### Publishing Messages

Publish a message to correlate with a waiting process instance:
```bash
c8 publish msg <messageName> --correlationKey=<key> --variables '{"status": "approved"}'
```

The correlation key must match the value in the process's message subscription.

### Cancelling Instances

Cancel a running process instance:
```bash
c8 cancel pi <instanceKey>
```

### Getting Process Definition XML

Retrieve the deployed BPMN XML:
```bash
c8 get pd <key> --xml
```

### JSON Output

For structured output (useful for parsing and debugging):
```bash
c8 output json
c8 list pi --fields Key,State,ProcessDefinitionId
```
