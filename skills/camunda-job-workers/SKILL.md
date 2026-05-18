---
name: camunda-job-workers
description: |
  Use this skill to implement Camunda 8 job workers in Java, Camunda Spring Boot, or TypeScript — handler code that activates jobs from a service task, runs business logic, and completes, fails, or throws a BPMN error.

  Use for: choosing between camunda-client-java, the Camunda Spring Boot Starter, and `@camunda8/orchestration-cluster-api`; wiring a `@JobWorker` method or `createJobWorker(...)` call to a BPMN `zeebe:taskDefinition type`; signalling complete / fail / BPMN error; idempotency, retries, back-off, auto-complete; Spring Boot 4 vs 3 starter on Camunda 8.9+.

  Do not use for: deciding worker-vs-connector (use camunda-development), authoring the BPMN task (use camunda-bpmn), configuring an OOTB connector (use camunda-connectors), or building a custom connector (use camunda-connectors-development).

  **Workflow skill** — pick an SDK, declare a handler against a `zeebe:taskDefinition type`, handle complete / fail / BPMN-error cases. Java, Spring, and TypeScript on Camunda 8.8+.
---

# Camunda Job Workers

Implement job workers for Camunda 8.8+ in Java, Camunda Spring Boot, or TypeScript. A job worker is the handler that the Zeebe engine hands an activated job to — it runs business logic, then signals success, failure, or a BPMN error back to the engine.

## Prerequisites

- Camunda 8.8+ cluster reachable from the worker process (local c8run, SaaS, or Self-Managed — see **camunda-c8ctl**)
- A BPMN process with at least one element that has `<zeebe:taskDefinition type="..."/>` matching the worker's job type (see **camunda-bpmn**)
- Toolchain for the chosen SDK:
  - **Java**: OpenJDK 17+, Maven (or Gradle)
  - **Camunda Spring Boot Starter**: OpenJDK 17+ and either Spring Boot 4.0.x (default starter) or Spring Boot 3.5.x (fallback starter — see "Spring Boot version" below)
  - **TypeScript**: Node.js 18+ (Node-only worker runtimes can use both `createJobWorker` and `createThreadedJobWorker`; browsers are limited to `createJobWorker`)

## Cross-References

- **camunda-development**: Use first to decide whether a worker is the right shape at all (vs. an OOTB connector, a JSON-only protocol-connector template, or a custom Java connector via the SDK)
- **camunda-connectors-development**: Use when the integration is closer to a reusable Java connector than to application-bound worker code, or when the integration needs inbound triggers (workers are outbound-only)
- **camunda-bpmn**: Use for the service-task / receive-task element and its `zeebe:taskDefinition`, plus the boundary events that catch the worker's BPMN errors
- **camunda-feel**: Use for FEEL in `zeebe:taskHeaders` and for the gateway conditions that consume the worker's output variables
- **camunda-process-mgmt**: Use for deploying the process, starting instances against the running worker, and inspecting jobs / incidents from the cluster side
- **camunda-process-test**: Use for end-to-end tests that drive worker handlers through an embedded Zeebe engine

## When to write a job worker

Walk **camunda-development** first. The short version of the matrix as it applies here:

- **Non-Java stack** (TypeScript, plus any other official SDK in scope for a future release): worker is the path. Connectors are Java-only.
- **Java stack, logic already lives in the app**: worker keeps the logic in the codebase that owns it.
- **Java stack, reusable across processes / projects / clusters**: prefer a custom connector via **camunda-connectors-development**.
- **Inbound triggers** (an external system pushes events *into* a process): always a connector — workers exclusively pull activated jobs from the engine.

## Job lifecycle

A worker's contract with the engine has four states:

1. **Activate** — the worker requests jobs of a given `type` (polling) or receives them on a streamed connection. Each activation has a **timeout** (the lease the engine grants before it will hand the same job to another worker if the first doesn't respond) and a **fetch-variables** list (which process variables the engine ships with the job).
2. **Handle** — the worker runs the handler code with the activated `job` (variables, headers, retries remaining, key).
3. **Complete** — the worker calls `complete` (or returns a value with `autoComplete=true`). The engine merges the worker's output variables into the process scope and advances the token. Variables propagate from the job's scope up to the enclosing scopes per BPMN rules.
4. **Fail** — the worker either calls `fail` explicitly with a remaining-retries count and an optional back-off, or throws. If retries reach zero, the engine raises an **incident** and the instance pauses until an operator resolves it (see **camunda-process-mgmt**).

**Activation timeout vs. retries are independent.** A timeout means the engine reassigns the job without decrementing retries; a `fail` with retries left means the same job will be redelivered after the back-off. Long-running handlers should extend the timeout via `UpdateJobTimeout` rather than racing the lease.

## Idempotency — handle every job at least twice

The engine's at-least-once delivery guarantees that a handler may run more than once for the same `job.key`. Activation timeouts, network blips, and retries after a failed `complete` call all cause redelivery. **Handlers must be idempotent.**

Two patterns work well:

- **Idempotency token in your downstream system.** Use `job.key` (or a deterministic value derived from process variables) as a request id / Idempotency-Key header / database unique constraint. A retry of the same job hits the same key and is suppressed.
- **Check-before-write.** Query the downstream system for the side effect's marker before applying it. Cheap when the system supports it; not always available.

Storing local "has this job ran?" state in the worker process is not idempotency — the process can crash, scale out, or be replaced.

## Failure modes — three distinct paths

The choice depends on whether the failure is a **transient infrastructure problem**, a **business outcome modelled in the BPMN**, or an **unexpected programming error**.

1. **`fail` with retries and back-off (transient).** Network timeout, downstream 5xx, broker unreachable. The handler computes a remaining-retries count (typically `job.retries - 1`) and a back-off duration, and the engine redelivers after the back-off. In the Camunda Spring Boot Starter, this is `throw CamundaError.jobError(message, variables, retries, retryBackoff, cause)`. In the Java client, this is the `newFailCommand(...).retries(...).retryBackoff(...).send()` builder. In TypeScript, this is `job.fail({ errorMessage, retries, retryBackOff })`. Reaching zero retries raises an incident.

2. **BPMN error (modelled business outcome).** The handler succeeded in identifying that something the business expects can fail — a payment was declined, an inventory check came back empty, a license validation rejected the input. The handler throws a BPMN error with a code that an error boundary event (or error end event in a subprocess) catches in the model. The job is **not retried** — the engine takes the error path. In the Camunda Spring Boot Starter: `throw CamundaError.bpmnError("ERROR_CODE", "human-readable explanation")`. In the Java client: `client.newThrowErrorCommand(job.getKey()).errorCode(...).errorMessage(...).send()`. In TypeScript: `job.error({ errorCode, errorMessage })`.

3. **Unhandled exception (programming error).** The handler threw something the SDK didn't expect — NullPointerException, unhandled promise rejection, type error. The SDK falls back to the default behaviour: `fail` with `retries = job.retries - 1` and `retryBackoff = 0`. The engine redelivers immediately; if the bug is deterministic the job burns through its retries and raises an incident. **Never use unhandled exceptions as a control-flow signal** — the zero back-off thrashes the cluster, and a future SDK change could redefine the default.

## Auto-complete vs. explicit complete

The Camunda Spring Boot Starter's `@JobWorker` defaults to `autoComplete = true`: the handler returns a value (a `Map<String, Object>` or a POJO that gets serialised to variables) and the framework calls `complete` with that value. Set `autoComplete = false` when the handler needs to call `complete` itself — e.g. to merge variables conditionally, to send the response asynchronously, or to hand the `ActivatedJob` to another component that owns completion.

The Java client and the TypeScript SDK do not auto-complete — the handler is responsible for calling `complete`, `fail`, or `error` on every code path. Forgetting to call one of those leaks the job's lease: it eventually times out and the engine redelivers it.

## Quick start — Camunda Spring Boot Starter

The Spring starter is the most common path for new Java workers. Drop the dependency, annotate a method, run.

```xml
<dependency>
  <groupId>io.camunda</groupId>
  <artifactId>camunda-spring-boot-starter</artifactId>
  <version>${camunda.version}</version>
</dependency>
```

```java
@SpringBootApplication
public class App {
  public static void main(String[] args) { SpringApplication.run(App.class, args); }
}

@Component
class OrderWorker {
  @JobWorker(type = "process-order")
  public Map<String, Object> processOrder(@Variable String orderId, @Variable BigDecimal amount) {
    if (amount.compareTo(MAX) > 0) {
      throw CamundaError.bpmnError("AMOUNT_EXCEEDED", "Amount " + amount + " exceeds limit");
    }
    var ref = paymentGateway.charge(orderId, amount);  // throws JobError on transient HTTP failure
    return Map.of("paymentRef", ref);                  // autoComplete writes this back as a variable
  }
}
```

`application.yaml`:

```yaml
camunda:
  client:
    mode: self-managed            # or saas, depending on cluster
    zeebe:
      grpc-address: ${CAMUNDA_GRPC_ADDRESS}
      rest-address: ${CAMUNDA_REST_ADDRESS}
```

Run the app — the starter activates jobs of type `process-order` as soon as a process instance reaches a service task with `<zeebe:taskDefinition type="process-order"/>`. For the SDK details (all annotation parameters, profile activation, environment-specific config, exception types), read `references/worker-sdk-spring.md`.

## Spring Boot version — pick the right starter on 8.9+

> The default Camunda Spring Boot Starter (`camunda-spring-boot-starter`) is bundled with and requires Spring Boot 4.0.x.

Applications on Spring Boot 4 use `camunda-spring-boot-starter` directly. Applications that cannot upgrade yet use **`camunda-spring-boot-3-starter`** instead — bundled with Spring Boot 3.5.x. Spring's OSS support for the 3.5.x line ends **June 2026**, so treat the SB3 starter as a migration bridge, not a long-lived target.

All starter modules require OpenJDK 17+.

## Java client — `camunda-client-java`

The plain Java client (no Spring) is the right choice when the worker process is not a Spring application, or when you need the lower-level `JobWorkerBuilder` API directly. As of Camunda 8.8 the artifact is **`camunda-client-java`** — it replaces the Zeebe Java Client. The Zeebe client will be **removed in 8.10**; existing code should migrate.

```xml
<dependency>
  <groupId>io.camunda</groupId>
  <artifactId>camunda-client-java</artifactId>
  <version>${camunda.version}</version>
</dependency>
```

```java
try (var client = CamundaClient.newClientBuilder().build()) {
  client.newWorker()
    .jobType("process-order")
    .handler((jobClient, job) -> {
      // run logic, then:
      jobClient.newCompleteCommand(job.getKey())
        .variables(Map.of("paymentRef", ref))
        .send().join();
    })
    .timeout(Duration.ofMinutes(1))
    .open();
  Thread.currentThread().join();   // keep the worker alive
}
```

Full client API (command builders, streaming, multi-tenancy, OAuth configuration), see `references/worker-sdk-java.md`.

## TypeScript — `@camunda8/orchestration-cluster-api`

The TypeScript path uses two packages. Pick the focused client by default; fall back to the bundled SDK only for narrow cases:

- **`@camunda8/orchestration-cluster-api`** (recommended) — REST-only client targeting Camunda 8.9+, runs in Node *and* browsers (browsers limited to `createJobWorker`; `createThreadedJobWorker` is Node-only).
- **`@camunda8/sdk`** (fallback) — bundles all clients, supports gRPC and REST, Node-only. Use it when: you need gRPC streaming, you target Camunda 8.7 or earlier, you depend on earlier Operate query APIs, or you are migrating an existing app and aren't ready to update environment configuration.

```typescript
import { CamundaRestApi } from "@camunda8/orchestration-cluster-api";

const client = new CamundaRestApi();
const worker = client.createJobWorker({
  jobType: "process-order",
  maxParallelJobs: 10,
  jobTimeoutMs: 60_000,
  jobHandler: async (job) => {
    if (job.variables.amount > MAX) {
      return job.error({ errorCode: "AMOUNT_EXCEEDED", errorMessage: `Amount ${job.variables.amount} exceeds limit` });
    }
    const ref = await paymentGateway.charge(job.variables.orderId, job.variables.amount);
    return job.complete({ paymentRef: ref });
  },
});
```

For CPU-bound handlers in Node, swap `createJobWorker` for `createThreadedJobWorker` (moves the handler to a worker-thread pool). Full reference: `references/worker-sdk-typescript.md`.

## Common pitfalls

- **Forgetting to complete / fail / error a job** (Java client, TypeScript). The lease times out and the engine redelivers. Handlers must hit exactly one terminal call on every code path. Spring's `autoComplete = true` covers happy-path returns; the failure paths still need `throw CamundaError.bpmnError(...)` / `CamundaError.jobError(...)` to signal the engine.
- **Treating unhandled exceptions as BPMN errors.** An unhandled throw is a programming error, not a modelled outcome. The SDK fails the job with `retries - 1` and `retryBackoff = 0` — the engine redelivers immediately, burns retries, and raises an incident. Use `CamundaError.bpmnError(...)` (or the SDK equivalent) when the failure is a business outcome, and `CamundaError.jobError(...)` (or `fail`) with a sensible back-off when it's transient infrastructure.
- **Storing "already processed" state in the worker process.** Crashes and scale-out erase it. Idempotency belongs in the downstream system or in process variables that survive redelivery.
- **Polling and request-timeout misalignment.** The activation request timeout must be shorter than the gateway / load-balancer cutoff, otherwise the worker tears the connection down and reconnects in a loop. The SDK defaults are sensible — change them deliberately.
- **Mixing `camunda-spring-boot-starter` and `camunda-spring-boot-3-starter`** on the same classpath. Pick one. The default SB4 starter on a Spring Boot 3 application will not start; the SB3 starter on a Spring Boot 4 application brings in conflicting transitive deps.
- **Picking `@camunda8/sdk` for new 8.9+ TypeScript projects by default.** Reach for `@camunda8/orchestration-cluster-api` first; only fall back to the bundled SDK when gRPC, sub-8.8 compatibility, or migration friction explicitly requires it.

## References

For SDK-specific detail, read from `references/`:
- [worker-sdk-java.md](references/worker-sdk-java.md) — `camunda-client-java`: client bootstrap, `JobWorkerBuilder`, command builders, streaming, multi-tenancy, OAuth config
- [worker-sdk-spring.md](references/worker-sdk-spring.md) — Camunda Spring Boot Starter: `@JobWorker` parameter reference, `@Variable` / `@VariablesAsType`, `CamundaError`, configuration property tree, Spring Boot 4 vs 3 starter selection
- [worker-sdk-typescript.md](references/worker-sdk-typescript.md) — `@camunda8/orchestration-cluster-api`: `createJobWorker` / `createThreadedJobWorker`, job-handler return shapes, when to fall back to `@camunda8/sdk`
