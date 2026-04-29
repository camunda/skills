# Local Cluster (c8 cluster)

Reference for the `c8 cluster` command group — c8ctl's default plugin that wraps [c8run](https://docs.camunda.io/docs/self-managed/setup/deploy/local/c8run/) to provide a one-command local Camunda 8 cluster.

## Why c8 cluster Over Direct c8run

c8run is a standalone Camunda distribution. `c8 cluster` is a thin wrapper that:

- Downloads the right binary for your platform (macOS x86_64/aarch64, Linux x86_64/aarch64, Windows x86_64) from the Camunda Download Center
- Caches binaries locally so repeat starts are instant
- Manages start/stop lifecycle and exposes a status check
- Resolves friendly version aliases (`stable`, `alpha`, `8.9`)
- Surfaces logs without you needing to know where c8run wrote them

Use `c8 cluster` when you want a local cluster for development. Use raw c8run if you need full control over the distribution layout.

## Commands

| Command | Purpose |
|---------|---------|
| `c8 cluster start [version]` | Start the cluster. Defaults to `stable`. |
| `c8 cluster start --debug` | Start with raw c8run logs streamed to stderr |
| `c8 cluster stop` | Gracefully stop the running cluster |
| `c8 cluster status` | Report whether a cluster is running, with connection details |
| `c8 cluster logs` | Stream `camunda.log` and `connectors.log` (`tail -f`) |
| `c8 cluster list` | List locally cached versions and current alias resolutions |
| `c8 cluster list-remote` | List all versions available on the download server |
| `c8 cluster install <version>` | Download a version without starting it (pre-cache) |
| `c8 cluster delete <version>` | Remove a cached version to reclaim disk space |

## Version Aliases

`stable` and `alpha` are resolved dynamically by querying the Camunda Download Center, so you always get the latest available without waiting for plugin updates.

| Alias | Resolves to |
|-------|-------------|
| `stable` | Highest minor release that is GA (e.g. `8.9`) |
| `alpha` | Highest minor release overall (e.g. `8.10-alpha1`) |

A `<major>.<minor>` like `8.8` or `8.9` is also a rolling reference — the download server's `8.8/` directory updates in place with new patch releases.

If the download server is unreachable, aliases fall back to the values shipped in the plugin's `package.json`.

### `start` vs `install` Update Behavior

- **`start`** uses the local version if available. A non-blocking remote check runs in the background — if a newer rolling release exists, a hint is printed (e.g. `A newer server version is available. Install it with: c8ctl cluster install 8.9`). If the network is unreachable, the hint is silently skipped.
- **`install`** always checks the remote for a newer rolling release (via ETag comparison) and re-downloads if one is available.

## Cache Locations

| Platform | Path |
|----------|------|
| macOS | `~/Library/Caches/c8run/` |
| Linux | `~/.cache/c8run/` |
| Windows | `%LOCALAPPDATA%\c8run\cache\` |

Override with the `C8RUN_CACHE_DIR` environment variable.

## What's Running

After `c8 cluster start`, the local cluster exposes:

- **Orchestration Cluster REST API**: `http://localhost:8080/v2`
- **Operate**: `http://localhost:8080/operate`
- **Tasklist**: `http://localhost:8080/tasklist`
- **Identity** (if enabled): `http://localhost:8080/identity`

c8ctl's default localhost fallback (`http://localhost:8080/v2`) means commands work without a profile against a freshly-started local cluster.

Open the web apps via:

```bash
c8 open operate
c8 open tasklist
c8 open modeler   # opens Camunda Modeler in the browser if available
c8 open optimize
```

## Common Workflows

### First-time local setup

```bash
# One command — downloads binary, starts cluster, waits until healthy
c8 cluster start
c8 get topology   # confirm it's alive
```

### Switching between rolling minors

```bash
c8 cluster stop
c8 cluster start 8.9    # rolling — picks up patches
```

### Pinning to an exact build for reproducibility

```bash
c8 cluster start 8.9.0-alpha5
```

### Updating a cached rolling release

```bash
c8 cluster install 8.9    # re-checks remote, re-downloads if newer
c8 cluster start 8.9      # uses the freshly-cached version
```

### Troubleshooting a failed start

```bash
c8 cluster status                # is it actually running?
c8 cluster logs                  # check Camunda log output
c8 cluster start --debug         # stream raw c8run output on next attempt
```

## Requirements

- **Java**: c8run requires JRE 21+ on the local machine (downloaded separately or installed via your package manager / SDKMAN).
- **Disk**: ~1–2 GB per cached version.
- **Ports**: `8080` (apps + REST API), `9600` (broker management). If these are taken by another process, `c8 cluster start` will fail — free the port or move the conflicting process.

## Supported Platforms

- macOS (x86_64, aarch64)
- Linux (x86_64, aarch64)
- Windows (x86_64)
