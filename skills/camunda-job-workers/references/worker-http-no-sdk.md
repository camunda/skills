# Zero-dependency Node.js worker (raw HTTP, no npm packages)

Use when npm is unavailable, the environment is locked down, or you need a minimal self-contained script (e.g. demos, CI scripts, Docker scratch images). Works against any Camunda 8.8+ cluster that exposes the Zeebe REST API.

This pattern polls `POST /v2/jobs/activation` on an interval and completes jobs via `POST /v2/jobs/{key}/completion`. It uses Node.js's built-in `http`/`https` module — no `package.json`, no `node_modules`.

## When to choose this over `@camunda8/orchestration-cluster-api`

Prefer the SDK for production applications — it handles connection errors, back-off, and the full job lifecycle. Use the raw HTTP pattern when:

- npm packages cannot be installed (locked-down CI, air-gapped environments)
- The worker is a one-file script with a known short lifespan (demo, migration script)
- You want zero runtime dependencies

## Local c8run auth

c8run serves the Zeebe REST API at `http://localhost:8080` with HTTP Basic auth, credentials `demo:demo`. For SaaS, swap to an OAuth bearer token.

```javascript
const AUTH = 'Basic ' + Buffer.from('demo:demo').toString('base64');
```

## Minimal polling worker

The complete sample lives in [worker-http-no-sdk.js](worker-http-no-sdk.js) — read it and copy it as
the starting point. It is a template, not a helper to run unmodified: set `BASE_URL`, `AUTH`, and
`JOB_TYPE`, then replace the block marked `--- your business logic here ---`.

Shape of it: a `request()` helper over `http`/`https`, a `poll()` that activates up to five jobs and
completes each one (failing the job on a thrown error), and a self-scheduling `loop()` that awaits
each poll before the next so polls never overlap. Run it with `node worker-http-no-sdk.js`.

## Key API shapes

**Activate** — `POST /v2/jobs/activation`

```json
{
  "type": "your-job-type",
  "maxJobsToActivate": 5,
  "timeout": 30000,
  "worker": "my-worker",
  "fetchVariable": ["varA", "varB"]   // optional — omit to receive all variables
}
```

Response: `{ "jobs": [ { "jobKey": "2251799813830779", "variables": {...}, "retries": 3, ... } ] }` — note `jobKey` is a string (the v2 REST API returns all `*Key` fields as strings, not `int64`).

**Complete** — `POST /v2/jobs/{jobKey}/completion`

```json
{ "variables": { "outputVar": "value" } }
```

**Fail** — `POST /v2/jobs/{jobKey}/failure`

```json
{
  "errorMessage": "reason",
  "retries": 2,
  "retryBackOff": 5000
}
```

**BPMN error** — `POST /v2/jobs/{jobKey}/error`

```json
{
  "errorCode": "MY_ERROR_CODE",
  "errorMessage": "reason"
}
```

## Limitations vs. the SDK

- No connection error recovery or automatic reconnect — a network blip drops the poll silently
- No gRPC streaming — polling adds latency proportional to the poll interval
- No `fetchVariable` type coercion or SDK-level validation
- Manual retry / back-off arithmetic

For production use, migrate to `@camunda8/orchestration-cluster-api` (see [worker-sdk-typescript.md](worker-sdk-typescript.md)).
