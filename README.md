# Camunda Skills

Official AI coding skills for Camunda 8 development. Build working Camunda solutions in minutes with AI guidance.

These skills follow the [Agent Skills](https://agentskills.io) open standard and work with Claude Code, Cursor, GitHub Copilot, Codex, Gemini CLI, and other compatible AI coding agents.

## Available Skills

| Skill | Description |
|-------|-------------|
| **camunda-c8ctl** | Install and configure c8ctl, set up a local cluster, manage profiles and plugins |
| **camunda-bpmn** | Create and edit BPMN 2.0 processes for Camunda 8/Zeebe |
| **camunda-feel** | Write and debug FEEL expressions |
| **camunda-forms** | Create Camunda Form JSON schemas for user tasks |
| **camunda-connectors** | Browse and configure pre-built connectors via element templates |
| **camunda-deploy** | Deploy resources and start process instances via c8ctl |
| **camunda-operate** | Monitor instances, resolve incidents, complete tasks via c8ctl |

## Prerequisites

- **Camunda 8.8+** cluster — local via [c8run](https://docs.camunda.io/docs/self-managed/setup/deploy/local/c8run/), SaaS, or Self-Managed
- **[c8ctl](https://github.com/camunda/c8ctl)** CLI installed and configured — provides all skill tooling (`c8 bpmn lint`, `c8 element-template`, `c8 feel eval`, deploy, watch, operate)
- **Node.js 18+** — only required for the optional auto-layout script in the camunda-bpmn skill

## Installation

### Claude Code Plugin

```bash
claude plugin add camunda/skills
```

### Other AI Agents (Cursor, Copilot, Codex, Gemini CLI)

```bash
npx skills add camunda/skills
```

### Manual

Clone this repository and copy the `skills/` directory into your project's `.agents/skills/` directory.

## Quick Start

1. Install c8ctl and start a local cluster:
   ```bash
   npm install -g @camunda8/cli
   c8 cluster start          # downloads c8run on first run
   ```

   For SaaS or Self-Managed clusters, run `c8 add profile` instead — see the **camunda-c8ctl** skill.

2. Ask your AI agent:
   > "Create an invoice approval process with a user task for review and an HTTP connector to notify the accounting system"

3. The agent will use the appropriate skills to create your BPMN process, forms, and guide you through deployment.

## License

Apache 2.0 — see [LICENSE](LICENSE).
