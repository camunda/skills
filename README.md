> [!NOTE]
> Technical preview. Skills are under heavy development and are subject to change.

# Camunda Skills

Official AI coding skills for Camunda 8 development. Build working Camunda solutions in minutes with AI guidance.

These skills follow the [Agent Skills](https://agentskills.io) open standard and work with Claude Code, Cursor, GitHub Copilot, Codex, Gemini CLI, and other compatible AI coding agents.

## Available Skills

| Skill | Description |
|-------|-------------|
| **camunda-c8ctl** | Install and configure c8ctl, set up a local cluster, manage profiles and plugins |
| **camunda-docs** | Look up the official Camunda 8 docs via the camunda-docs MCP server (with `llms.txt` fallback) |
| **camunda-bpmn** | Create and edit BPMN 2.0 processes for Camunda 8/Zeebe |
| **camunda-feel** | Write and debug FEEL expressions |
| **camunda-dmn** | Author DMN decisions — decision tables, hit policies, literal expressions, business-rule task wiring |
| **camunda-forms** | Create Camunda Form JSON schemas for user tasks |
| **camunda-connectors** | Browse and configure pre-built connectors via element templates |
| **camunda-development** | Choose between OOTB connectors, custom connector templates, custom Java connectors, and job workers before writing integration code |
| **camunda-job-workers** | Implement job workers in Java, Camunda Spring Boot, or TypeScript |
| **camunda-connectors-development** | Build custom Camunda 8 connectors — JSON-only template on a protocol connector, or custom Java connector via the Connectors SDK (outbound + inbound) |
| **camunda-process-mgmt** | Deploy resources, start/inspect instances, resolve incidents, complete tasks — via c8ctl |
| **camunda-ai-agents** | Build AI agents in BPMN — AI Agent connector on an ad-hoc subprocess, tools, `fromAi()`, prompts |

## Prerequisites

- **Camunda 8.8+** cluster — local via [c8run](https://docs.camunda.io/docs/self-managed/setup/deploy/local/c8run/), SaaS, or Self-Managed
- **[c8ctl](https://github.com/camunda/c8ctl)** CLI installed and configured — provides all skill tooling (`c8ctl bpmn lint`, `c8ctl element-template`, `c8ctl feel evaluate`, deploy, watch, operate)

## Installation

### Any AI coding agent

Several installers in the [Agent Skills](https://agentskills.io) ecosystem support a range of agents — Claude Code, GitHub Copilot, Cursor, Codex, Gemini CLI, Goose, and others. Two common ones:

```bash
# npm-based
npx skills add camunda/skills --skill '*'

# GitHub CLI -- select "all skills"
gh skill install camunda/skills
```

See each tool's `--help` for supported agents and options (version pinning, scope).

### Claude Code Plugin

```bash
# Register this repo as a Claude Code marketplace (one-time)
claude plugin marketplace add camunda/skills

# Install the plugin
claude plugin install camunda-skills@camunda-skills
```

### Manual (local clone)

Clone this repository and copy `skills/<skill-name>/` directories into your agent's skills lookup path (e.g. `~/.claude/skills/` for Claude Code user-wide, `<project>/.claude/skills/` for project-scoped; consult your agent's docs for other agents).

To try the skills with Claude Code without installing — useful for evaluating before you commit — load them session-only against a local clone:

```bash
git clone https://github.com/camunda/skills && cd skills
claude --plugin-dir .
# or, equivalent shortcut while developing this repo:
make try
```

## Quick Start

1. Install c8ctl and start a local cluster:
   ```bash
   npm install -g @camunda8/cli
   c8ctl cluster start          # downloads c8run on first run
   ```

   For SaaS or Self-Managed clusters, run `c8ctl add profile` instead — see the **camunda-c8ctl** skill.

2. Ask your AI agent:
   > "Create an invoice approval process with a user task for review and an HTTP connector to notify the accounting system"

3. The agent will use the appropriate skills to create your BPMN process, forms, and guide you through deployment.

## Issues

Bug or feature request? [Open an issue](https://github.com/camunda/skills/issues/new/choose). General Camunda 8 questions belong on the [Camunda Forum](https://forum.camunda.io).

## License

Apache 2.0 — see [LICENSE](LICENSE).
