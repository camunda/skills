# Plugin Lifecycle

Reference for managing c8ctl plugins — the extension mechanism that ships the `cluster`, `bpmn`, `feel`, and `element-template` default plugins, and that lets you install third-party or custom commands.

## Default Plugins (Already Installed)

c8ctl ships with these plugins pre-loaded — no install step needed:

| Plugin | Provides |
|--------|----------|
| `cluster` | `c8ctl cluster start/stop/status/logs/list/install/...` (local c8run management) |
| `bpmn` | `c8ctl bpmn lint` |
| `feel` | `c8ctl feel evaluate` |
| `element-template` | `c8ctl element-template search/info/get-properties/apply/get/sync` |

## Plugin Commands

```bash
# List installed plugins
c8ctl list plugins

# Install from npm
c8ctl load plugin <package-name>

# Install from a URL (Git, file, https://)
c8ctl load plugin --from https://github.com/camunda/c8ctl-plugin-diagram-renderer
c8ctl load plugin --from git://github.com/user/repo.git
c8ctl load plugin --from file:///path/to/local/plugin

# Upgrade
c8ctl upgrade plugin <package-name>             # to latest
c8ctl upgrade plugin <package-name> 1.2.3       # to specific version

# Downgrade
c8ctl downgrade plugin <package-name> 1.0.0

# Uninstall
c8ctl unload plugin <package-name>

# Reconcile installed plugins with the registry file (e.g. after manual edits)
c8ctl sync plugin

# Scaffold a new plugin from template (for plugin authors)
c8ctl init plugin my-plugin
```

## Storage Layout

Plugins are installed to a user-specific directory and tracked in a registry file:

| OS | Plugins Directory | Registry File |
|----|-------------------|---------------|
| Linux | `~/.config/c8ctl/plugins/node_modules` | `~/.config/c8ctl/plugins.json` |
| macOS | `~/Library/Application Support/c8ctl/plugins/node_modules` | `~/Library/Application Support/c8ctl/plugins.json` |
| Windows | `%APPDATA%\c8ctl\plugins\node_modules` | `%APPDATA%\c8ctl\plugins.json` |

Override the data directory with the `C8CTL_DATA_DIR` environment variable.

## Discovering Plugins

Plugins surface their commands in `c8ctl help` output once loaded. After installing a plugin:

```bash
c8ctl help                              # see new command groups appear
c8ctl help <new-command>                # full reference for the plugin's commands
```

## Notable Third-Party Plugins

- **`c8ctl-plugin-diagram-renderer`** — renders BPMN diagrams as PNG (or inline in terminals that support it: iTerm2, Ghostty, Kitty). Useful for visualizing process state at a particular instance.

  ```bash
  c8ctl load plugin --from https://github.com/camunda/c8ctl-plugin-diagram-renderer
  c8ctl diagram <process-instance-id> --output ./diagram.png
  ```

## Building a Custom Plugin

Plugins are regular npm packages with a `c8ctl-plugin.js` entry point. The runtime exposes a typed API:

```typescript
import type { c8ctlPluginRuntime } from '@camunda8/cli/runtime';

const c8ctl = globalThis.c8ctl as c8ctlPluginRuntime;
const client = c8ctl.createClient();          // SDK client wired to active profile
const tenantId = c8ctl.resolveTenantId();     // active tenant
const logger = c8ctl.getLogger();             // output-aware logging

logger.info(`Operating on tenant: ${tenantId}`);
```

Plugins automatically respect:

- The active profile (and `--profile` overrides)
- The active tenant (and `--tenantId` overrides)
- The session output mode (`text` vs `json`)

To get started:

```bash
c8ctl init plugin my-tool             # scaffold from template
cd my-tool
# implement c8ctl-plugin.js
c8ctl load plugin --from file://$(pwd)
c8ctl help                            # confirm your commands appear
```

## Debug Mode

Plugin loading and other internals are silent by default. Enable debug output to see what's happening:

```bash
DEBUG=1 c8ctl list plugins
C8CTL_DEBUG=true c8ctl <command>
```

Debug output is written to stderr with timestamps, so it doesn't interfere with normal command output or JSON parsing.
