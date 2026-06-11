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

```javascript
const http = require('http');

const BASE_URL = 'http://localhost:8080';
const AUTH = 'Basic ' + Buffer.from('demo:demo').toString('base64');
const JOB_TYPE = 'your-job-type';          // must match zeebe:taskDefinition type in BPMN

async function request(method, path, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(BASE_URL + path);
    const opts = {
      hostname: url.hostname,
      port: url.port || 80,
      path: url.pathname,
      method,
      headers: {
        'Authorization': AUTH,
        'Content-Type': 'application/json',
      },
    };
    const req = http.request(opts, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch { resolve(data); }
      });
    });
    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

async function poll() {
  const activation = await request('POST', '/v2/jobs/activation', {
    type: JOB_TYPE,
    maxJobsToActivate: 5,
    timeout: 30000,                        // ms — engine's lease; handler must complete within this window
    worker: 'my-worker',
  });

  const jobs = activation.jobs ?? [];
  for (const job of jobs) {
    try {
      // --- your business logic here ---
      const result = { processedAt: new Date().toISOString() };

      await request('POST', `/v2/jobs/${job.jobKey}/completion`, {
        variables: result,
      });
    } catch (err) {
      // Fail the job — engine will redeliver after retries
      await request('POST', `/v2/jobs/${job.jobKey}/failure`, {
        errorMessage: err.message,
        retries: (job.retries ?? 1) - 1,
        retryBackOff: 5000,
      });
    }
  }
}

console.log(`Worker polling for ${JOB_TYPE}...`);
setInterval(poll, 1000);
poll();
```

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
