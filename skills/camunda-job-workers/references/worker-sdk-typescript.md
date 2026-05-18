# TypeScript SDK — `@camunda8/orchestration-cluster-api`

REST-only TypeScript client for Camunda 8.9+. Runs in Node.js and in browsers. The default TypeScript path for new applications.

The full-featured **`@camunda8/sdk`** (gRPC + REST, bundles every Camunda 8 client) is still maintained but should only be reached for in three cases:

- The application needs gRPC streaming for job workers (lower latency than REST polling).
- The application targets Camunda 8.7 or earlier — the focused client is 8.9-first.
- The application depends on earlier Operate query APIs that the focused client does not expose, or is mid-migration and cannot adopt the focused client's config shape yet.

Browsers cannot use `@camunda8/sdk` (Node-only) regardless.

## Install

```bash
npm install @camunda8/orchestration-cluster-api
```

```typescript
import { CamundaRestApi } from "@camunda8/orchestration-cluster-api";

const client = new CamundaRestApi({
  baseUrl: "http://localhost:8080",
  // OAuth or basic auth options if applicable
});
```

The client reads the same `CAMUNDA_*` environment variables as `c8ctl` and the Java client — `CAMUNDA_OAUTH_URL`, `CAMUNDA_CLIENT_ID`, `CAMUNDA_CLIENT_SECRET`, `CAMUNDA_TOKEN_AUDIENCE` — when the constructor options are omitted.

## `createJobWorker` — polling-based worker

```typescript
const worker = client.createJobWorker({
  jobType: "process-order",
  maxParallelJobs: 10,
  jobTimeoutMs: 60_000,
  pollIntervalMs: 100,
  fetchVariables: ["orderId", "amount"],
  jobHandler: async (job) => {
    if (job.variables.amount > MAX) {
      return job.error({
        errorCode: "AMOUNT_EXCEEDED",
        errorMessage: `Amount ${job.variables.amount} exceeds limit`,
      });
    }
    try {
      const ref = await paymentGateway.charge(job.variables.orderId, job.variables.amount);
      return job.complete({ paymentRef: ref });
    } catch (e) {
      return job.fail({
        errorMessage: "payment-gateway-timeout",
        retries: job.retries - 1,
        retryBackOff: 10_000,
      });
    }
  },
});

// shutdown
await worker.close();
```

Runs in Node and in browsers. Browsers cannot use `createThreadedJobWorker`.

### Handler return — terminal calls

A handler must return one of:

- `job.complete(variables?)` — success; variables are merged into the process scope
- `job.fail({ errorMessage, retries, retryBackOff, variables? })` — transient failure; engine redelivers after `retryBackOff` ms; reaching `retries = 0` raises an incident
- `job.error({ errorCode, errorMessage, variables? })` — BPMN error; engine routes to the matching error boundary event; no retry

Unhandled exceptions (an `await` that throws, an unhandled promise rejection) fall through to the default `fail` behaviour: `retries -= 1`, `retryBackOff = 0`. Use that as the bug-detection net, not as a control-flow signal.

## `createThreadedJobWorker` — CPU-bound, Node-only

When the handler is genuinely CPU-bound (PDF rendering, image transforms, large JSON shape conversion), the single-threaded event loop becomes the bottleneck. `createThreadedJobWorker` offloads handlers to a worker-thread pool.

```typescript
// main.ts
const worker = client.createThreadedJobWorker({
  jobType: "render-invoice",
  maxParallelJobs: 4,
  jobTimeoutMs: 120_000,
  handlerModule: "./render-invoice-handler.ts",   // separate module — runs in worker thread
  threadPoolSize: 4,
});

// render-invoice-handler.ts
export default async function handler(job) {
  const pdf = await renderInvoicePdf(job.variables);     // blocks CPU
  return job.complete({ pdfDocumentId: pdf.id });
}
```

The handler module is loaded once per worker thread and called per job. No shared state between threads — pass everything you need via `job.variables` / `job.customHeaders`.

Node-only. Browsers must use `createJobWorker`.

## Choosing between the two

| Aspect | `createJobWorker` | `createThreadedJobWorker` |
|---|---|---|
| Execution | Main event loop | Worker-thread pool |
| Best for | I/O-bound (HTTP, DB, message queues) | CPU-bound (rendering, encoding, hashing) |
| Handler | Inline function in main module | Separate module file |
| Platforms | Node *and* browsers | Node only |
| Extra options | — | `handlerModule`, `threadPoolSize` |

Default to `createJobWorker`. Switch to the threaded variant only after measuring an event-loop bottleneck.

## When to fall back to `@camunda8/sdk`

```bash
npm install @camunda8/sdk
```

```typescript
import { Camunda8 } from "@camunda8/sdk";

const c8 = new Camunda8();
const zbc = c8.getZeebeGrpcApiClient();             // gRPC client
const worker = zbc.createWorker({ ... });           // legacy gRPC worker
```

Use this path only when the focused client cannot do the job (gRPC streaming, sub-8.8 target, Operate v1 queries). Document the reason in the codebase — future maintainers will otherwise migrate it back.

## Wiring to BPMN

`jobType` must exactly match the BPMN element's `<zeebe:taskDefinition type="..."/>`. The engine activates the worker when an instance reaches the task. Apply the task type via **camunda-bpmn**.
