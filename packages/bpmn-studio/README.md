# @camunda8/bpmn-studio

An MCP server for designing, linting, viewing and testing Camunda 8 BPMN processes with an AI agent. Ask an agent to "make a BPMN process" and get the diagram back **inside the chat**: an interactive bpmn.io modeler you can edit, Camunda lint markers, and a **test studio** that runs the process on an in-memory engine. You can start instances, complete jobs and user tasks, and watch the tokens move.

It ships as the `bpmn-studio` plugin in the [camunda/skills](https://github.com/camunda/skills) marketplace, alongside the `camunda-skills` plugin it pairs with. The `bpmn-studio` skill lives in [`plugins/bpmn-studio`](../../plugins/bpmn-studio).

| Host | What you get |
|---|---|
| Claude Desktop / claude.ai, ChatGPT, VS Code (hosts with MCP Apps) | Inline modeler + test studio, two-way edits |
| Claude Code, Copilot CLI, Codex CLI, Cursor | The same tools, text only (lint reports, test traces) |

## Install

**Claude Code**

```sh
/plugin marketplace add camunda/skills
/plugin install camunda-skills@camunda-skills
/plugin install bpmn-studio@camunda-skills
```

**Any MCP host (stdio).** Requires Node.js 20+.

```json
{
  "mcpServers": {
    "bpmn-studio": { "command": "npx", "args": ["-y", "@camunda8/bpmn-studio", "--stdio"] }
  }
}
```

Claude Desktop doesn't load your shell `PATH` (for example nvm), so use the absolute path to `npx` there. Set `BPMN_MCP_ROOT` to the folder where relative paths resolve and where `save_bpmn` may write (default: the server's working directory).

**Remote (claude.ai / ChatGPT).** `PORT=3001 npx @camunda8/bpmn-studio` serves Streamable HTTP at `/mcp`. Expose it over HTTPS and add it as a custom connector. For Claude, set `BPMN_MCP_UI_DOMAIN` to `sha256(<connector URL>)[:32].claudemcpcontent.com`.

## Tools

- `show_bpmn`: opens the diagram in the interactive view.
- `lint_bpmn`: the same rules as `c8ctl bpmn lint`: `bpmnlint:recommended` plus `camunda-compat/camunda-cloud-X-Y`, chosen from `modeler:executionPlatformVersion`.
- `test_bpmn`: runs a scripted scenario with expectations on the in-memory engine, server side. It lints first and refuses to run a diagram with lint errors (warnings don't block). When refused, the view opens on the Model tab with the lint markers.
- `get_bpmn_edits`: picks up what the user changed in the view.
- `save_bpmn`: writes `.bpmn` files, only under `BPMN_MCP_ROOT`.
- App-only tools that the view calls: `ui_lint`, `ui_sync`, `ui_engine`.

## The view

`dist/mcp-app.html` is a single file (about 4.4 MB, engine WASM inlined).

- **Model** tab: bpmn-js modeler with the Zeebe properties panel and lint overlays. Edits are synced to the agent with `updateModelContext` and `ui_sync`; the user can type a note to the agent about a change. **Save** writes the file.
- **Test** tab: deploys the current diagram, starts instances with variables, and lets you complete or fail jobs, throw BPMN errors, complete user tasks, correlate messages, broadcast signals and advance the clock. Active and taken elements are highlighted. For `test_bpmn` runs, it replays the scenario.
- **Engine**: the [nanobpm](https://github.com/nanobpm/nano-bpm) WASM engine (`@nanobpm/engine-wasm`, Apache-2.0) runs in the iframe when the host's CSP allows WebAssembly compilation. Otherwise the view falls back to the same engine on the server (`ui_engine`); the footer shows which one is in use.

The engine is a fast in-memory test engine, not a Camunda cluster: connectors, real workers and forms don't run. Deploy to a real cluster with c8ctl.

## Develop

```sh
npm ci
npm run build        # generates the lint rule table, type-checks, builds view + server into dist/
npm run smoke        # MCP client smoke test over stdio
```

`dist/index.js` is self-contained (all dependencies bundled, engine `.wasm` copied next to it), so the published package has no runtime dependencies.

To try the plugin against a local build in Claude Code, temporarily point `plugins/bpmn-studio/.mcp.json` at it (`"command": "node", "args": ["<checkout>/packages/bpmn-studio/dist/index.js", "--stdio"]`) and run `claude --plugin-dir plugins/bpmn-studio` from the repo root.

**Browser e2e (optional).** Clone and build the [ext-apps](https://github.com/modelcontextprotocol/ext-apps) `examples/basic-host`, run it against `PORT=3001 node dist/index.js`, then run `node e2e/host.mjs http://localhost:8090 /tmp/shot` and `node e2e/collab.mjs http://localhost:8090 $PWD/fixtures/order-approval.bpmn` (Playwright).

## Layout

```
main.ts                  stdio / HTTP entry
src/server/              MCP server, lint (c8ctl parity), engine sessions, scenario runner
src/ui/                  view: modeler, test studio, engine client (WASM → server fallback)
src/shared/engine.ts     engine ops shared by view and server
scripts/                 build steps, lint rule table generator, smoke test
```
