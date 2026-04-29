---
name: camunda-deploy
description: Deploys BPMN processes, DMN decisions, and Camunda Forms to a Camunda 8 cluster and starts process instances via c8ctl. This skill should be used when deploying resources, starting process instances, or setting up hot-reload during development.
---

# Camunda Deploy

Deploy resources to a Camunda 8.8+ cluster and start process instances using c8ctl.

## Prerequisites

- Camunda 8.8+ cluster (local via c8run, SaaS, or Self-Managed)
- [c8ctl](https://github.com/camunda/c8ctl) CLI installed and configured

## Cross-References

- **camunda-bpmn**: Use for creating/editing BPMN processes before deployment
- **camunda-operate**: Use for monitoring deployed processes and managing instances

## Instructions

### c8ctl Profile Setup

Configure a cluster profile before first use:

```bash
c8 add profile
```

Switch between profiles:
```bash
c8 list profiles
c8 use profile <name>
```

Verify cluster connectivity:
```bash
c8 get topology
```

### Deploying Resources

Deploy a single BPMN file:
```bash
c8 deploy process.bpmn
```

Deploy multiple resources (BPMN, DMN, forms):
```bash
c8 deploy process.bpmn decision.dmn approval-form.form
```

Deploy an entire directory:
```bash
c8 deploy ./my-project
```

### Starting Process Instances

Create a process instance:
```bash
c8 create pi --id MyProcess
```

Create with variables:
```bash
c8 create pi --id MyProcess --variables '{"orderId": "ORD-123", "amount": 1500}'
```

Deploy and start in one command:
```bash
c8 run process.bpmn --variables '{"orderId": "ORD-123"}'
```

### Awaiting Completion

Start an instance and wait for it to complete:
```bash
c8 await pi --id MyProcess --variables '{"orderId": "ORD-123"}'
```

With custom timeout:
```bash
c8 await pi --id MyProcess --requestTimeout 60000
```

### Development: Watch Mode

Auto-redeploy on file changes during development:
```bash
c8 watch ./my-project
```

This watches for changes to `.bpmn`, `.dmn`, and `.form` files and redeploys automatically.

### JSON Output

Switch to JSON output for structured parsing:
```bash
c8 output json
```

Limit output fields to reduce noise:
```bash
c8 list pd --fields Key,Name,Version
```

### Deployment Verification

After deploying, verify the deployment:
```bash
c8 list pd
c8 search pd --iname="MyProcess"
```

### Troubleshooting

**Deployment fails**: Check for BPMN validation errors — run `c8 bpmn lint process.bpmn` first.

**Process won't start**: Verify the process ID matches (`c8 list pd`). Check if required variables are provided.

**Version conflicts**: Each deployment creates a new version. Use `c8 list pd --fields Key,Name,Version` to see versions.
