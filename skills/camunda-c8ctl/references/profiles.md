# Profile and Credential Management

Reference for connecting c8ctl to a cluster — profiles, credentials, tenants.

## Profile Types

c8ctl supports two profile types:

1. **c8ctl profiles** — managed directly with `c8ctl add/use/remove profile` commands. Stored in c8ctl's data directory.
2. **Camunda Modeler profiles** — automatically imported from Camunda Desktop Modeler. Read-only. Always prefixed with `modeler:`.

## c8ctl Profile Commands

```bash
# Add a profile
c8ctl add profile <name> [flags]

# List all profiles (both c8ctl and Modeler)
c8ctl list profiles

# Set the active profile
c8ctl use profile <name>

# Show the current active profile
c8ctl which profile

# Remove a c8ctl profile (Modeler profiles are read-only)
c8ctl remove profile <name>
c8ctl rm profile <name>          # alias

# Per-command override (active profile unchanged)
c8ctl list pi --profile=staging
```

## Profile Flags

| Flag | Description | Example |
|------|-------------|---------|
| `--baseUrl` | Cluster base URL (Zeebe REST endpoint, not the dashboard URL) | `https://camunda.example.com` |
| `--clientId` | OAuth client ID | `your-client-id` |
| `--clientSecret` | OAuth client secret | `your-client-secret` |
| `--audience` | OAuth audience (when the cluster needs an explicit audience) | `camunda-api` |
| `--oAuthUrl` | OAuth token endpoint (when not auto-discoverable) | `https://auth.example.com/oauth/token` |
| `--defaultTenantId` | Default tenant for this profile | `dev-tenant` |

## URL Construction

c8ctl handles the `/v2` REST suffix automatically:

- **Self-Managed (localhost)**: c8ctl appends `/v2` to the URL (e.g., `http://localhost:8080/v2`)
- **Cloud**: c8ctl uses the cluster URL as-is (e.g., `https://abc123.region.zeebe.camunda.io`)

Any port number is supported.

## Profile Examples

### Minimal local profile

```bash
c8ctl add profile local
# Defaults to http://localhost:8080/v2 with no authentication
```

### OAuth-secured Self-Managed cluster

```bash
c8ctl add profile prod \
  --baseUrl=https://camunda.example.com \
  --clientId=your-client-id \
  --clientSecret=your-client-secret
```

### Explicit OAuth audience and endpoint

```bash
c8ctl add profile prod \
  --baseUrl=https://camunda.example.com \
  --clientId=your-client-id \
  --clientSecret=your-client-secret \
  --audience=camunda-api \
  --oAuthUrl=https://auth.example.com/oauth/token
```

### Profile with default tenant

```bash
c8ctl add profile dev \
  --baseUrl=https://dev.example.com \
  --clientId=dev-client \
  --clientSecret=dev-secret \
  --defaultTenantId=dev-tenant
```

## Camunda Modeler Integration

c8ctl automatically reads profiles from Camunda Desktop Modeler's `profiles.json`. These profiles are:

- **Read-only** — cannot be modified or deleted via c8ctl
- **Prefixed** — always displayed with `modeler:` prefix (e.g., `modeler:Local Dev`)
- **Dynamic** — loaded fresh on each command execution (no caching)

### Profile File Locations

| Platform | Path |
|----------|------|
| Linux | `~/.config/camunda-modeler/profiles.json` |
| macOS | `~/Library/Application Support/camunda-modeler/profiles.json` |
| Windows | `%APPDATA%\camunda-modeler\profiles.json` |

### Using Modeler Profiles

```bash
# List shows Modeler profiles with the `modeler:` prefix
c8ctl list profiles

# Use by display name
c8ctl use profile "modeler:Local Dev"

# Use by cluster ID
c8ctl use profile modeler:abc123-def456

# One-off command with a Modeler profile
c8ctl list pi --profile="modeler:Cloud Cluster"
```

## Credential Resolution Order

When c8ctl runs a command, it resolves credentials in this order (first match wins):

1. **`--profile` flag** — one-off override for a single command
2. **Active profile** — set with `c8ctl use profile <name>`
3. **Environment variables** — standard `CAMUNDA_*` variables
4. **Localhost fallback** — `http://localhost:8080/v2` with no auth

### Environment Variables

```bash
export CAMUNDA_BASE_URL=https://camunda.example.com
export CAMUNDA_CLIENT_ID=your-client-id
export CAMUNDA_CLIENT_SECRET=your-client-secret
c8ctl list pi
```

Useful when running c8ctl in CI/CD where storing a profile on disk isn't ideal.

## Tenant Resolution

For multi-tenant clusters, the active tenant resolves in this order:

1. **Active tenant** — set with `c8ctl use tenant <id>`
2. **Default tenant** from the active profile (`--defaultTenantId` flag at profile creation)
3. **`CAMUNDA_DEFAULT_TENANT_ID`** environment variable
4. **`<default>`** tenant (the built-in default)

```bash
# Set the active tenant for the session
c8ctl use tenant my-tenant-id
c8ctl list pi          # uses my-tenant-id

# Per-command tenant override
c8ctl list pi --tenantId=other-tenant
```

## Switching Profiles in Practice

A typical multi-cluster workflow:

```bash
# Day starts: switch to dev
c8ctl use profile dev
c8ctl watch                    # auto-redeploys to dev as you save

# Need to peek at staging
c8ctl list inc --profile=staging --state=ACTIVE

# Promote a fix to prod
c8ctl deploy ./hotfix.bpmn --profile=prod

# End of day: where am I?
c8ctl which profile            # confirms current active
```

## Troubleshooting

- **OAuth fails with "audience not allowed"** — your cluster requires an explicit audience. Add `--audience=<expected-audience>` to the profile.
- **OAuth fails with "unable to discover token endpoint"** — auto-discovery via `.well-known` is unreachable or disabled. Add `--oAuthUrl=<endpoint>` to the profile.
- **`401 Unauthorized` against SaaS** — verify the `--baseUrl` is the *Zeebe REST endpoint* (e.g., `https://abc.bru-2.zeebe.camunda.io`), not the dashboard URL.
- **Modeler profiles missing from `c8ctl list profiles`** — check that Camunda Desktop Modeler is installed and that the `profiles.json` exists at the platform path above. Modeler must have been opened at least once with a configured connection.
