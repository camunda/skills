# Profile and Credential Management

Reference for using already-configured c8ctl profiles — switching, inspection, resolution order, tenants.

Profile setup (OAuth flags, credentials) is a one-time human task — see the [c8ctl docs](https://docs.camunda.io/docs/apis-tools/c8ctl/getting-started/). This reference covers how to use already-configured profiles.

## Profile Types

c8ctl supports two profile types:

1. **c8ctl profiles** — managed directly with `c8ctl add/use/remove profile` commands. Stored in c8ctl's data directory.
2. **Camunda Modeler profiles** — automatically imported from Camunda Desktop Modeler. Read-only. Always prefixed with `modeler:`.

## c8ctl Profile Commands

For creating profiles with `c8ctl add profile`, see the [c8ctl docs](https://docs.camunda.io/docs/apis-tools/c8ctl/getting-started/). Commands for using configured profiles:

```bash
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

## URL Construction

c8ctl handles the `/v2` REST suffix automatically:

- **Self-Managed (localhost)**: c8ctl appends `/v2` to the URL (e.g., `http://localhost:8080/v2`)
- **Cloud**: c8ctl uses the cluster URL as-is (e.g., `https://abc123.region.zeebe.camunda.io`)

Any port number is supported.

## Default Local Profile

c8ctl ships with a built-in `local` profile pointing at `http://localhost:8080/v2` with no authentication — use `--profile=local` directly, no setup needed.

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

Always use item 1 (`--profile=<name>` explicit per command) on cluster-touching work — do not rely on the active profile, it may point at production or staging from a previous session. See `SKILL.md § Safety` for the full rule.

The `CAMUNDA_*` environment variables (e.g., `CAMUNDA_BASE_URL`, `CAMUNDA_CLIENT_ID`, `CAMUNDA_CLIENT_SECRET`) are documented in the [c8ctl docs](https://docs.camunda.io/docs/apis-tools/c8ctl/getting-started/). Useful for CI/CD where storing a profile on disk isn't ideal — but the actual values stay out of agent transcripts and out of this skill.

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
