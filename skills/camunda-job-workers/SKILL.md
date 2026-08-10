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
- Toolchain for the chosen SDK — OpenJDK 17+ and Maven/Gradle for Java and Spring; Node.js 18+ for TypeScript. SDK-specific version constraints (e.g. Spring Boot 4 vs 3, browser support) are in each SDK's reference. See **camunda-development** for installing these locally.

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

The choice depends on whether the failure is a **transient infrastructure problem**, a **modelled business outcome**, or an **unexpected programming error**:

1. **Transient failure → fail with retries and back-off.** Network timeout, downstream 5xx, broker unreachable. The handler decrements retries and asks the engine to redeliver after a back-off. Reaching zero retries raises an incident.

2. **Business outcome → BPMN error.** The handler succeeded in *identifying* a failure modelled in the BPMN — payment declined, inventory empty, license rejected. Throw a BPMN error with a code that an error boundary event (or error end event in a subprocess) catches. The job is **not** retried — the engine takes the error path.

3. **Programming error → unhandled exception.** A NullPointerException, an unhandled promise rejection, a type error. SDKs fall back to *fail-with-zero-back-off* — the engine redelivers immediately, burns retries, and raises an incident. **Never use unhandled exceptions as a control-flow signal**: the zero back-off thrashes the cluster, and a future SDK change could redefine the default.

The SDK-specific call signatures (`CamundaError.jobError` / `CamundaError.bpmnError` for Spring, `newFailCommand` / `newThrowErrorCommand` for the Java client, `job.fail` / `job.error` for TypeScript) are in the per-SDK references.

## Auto-complete vs. explicit complete

The Camunda Spring Boot Starter's `@JobWorker` auto-completes by default: the handler's return value is serialised as the job's output variables. Set `autoComplete = false` when the handler needs to call `complete` itself (conditional variables, asynchronous response, ownership transfer).

The Java client and TypeScript SDK **do not** auto-complete — the handler must call `complete`, `fail`, or `error` on every code path. Missing a terminal call leaks the job's lease until activation timeout.

## Pick an SDK

| SDK | When to pick |
|---|---|
| **Camunda Spring Boot Starter** — `camunda-spring-boot-starter` ([ref](references/worker-sdk-spring.md)) | New Java applications. Annotation-driven (`@JobWorker`), auto-complete, config via `application.yaml`. The default Java path. |
| **Java client** — `camunda-client-java` ([ref](references/worker-sdk-java.md)) | Standalone JVM applications, non-Spring frameworks, libraries embedding Zeebe access. Lower-level builder API. Replaces the deprecated Zeebe Java Client (removed in 8.10). |
| **TypeScript** — `@camunda8/orchestration-cluster-api` ([ref](references/worker-sdk-typescript.md)) | Node.js workers, browser-hosted clients, 8.9+ projects. Fall back to `@camunda8/sdk` (Node-only) only when gRPC streaming, sub-8.8 targets, or migration friction explicitly require it. |

### Spring Boot 4 vs. 3 — high-stakes routing

> The default Camunda Spring Boot Starter (`camunda-spring-boot-starter`) is bundled with and requires Spring Boot 4.0.x.

Applications still on Spring Boot 3.5.x use **`camunda-spring-boot-3-starter`** as a migration bridge — Spring's OSS support for the 3.5.x line ends **June 2026**. Don't mix the two starters on one classpath: the SB4 starter won't start on a Spring Boot 3 app, and the SB3 starter pulls conflicting transitive deps into a Spring Boot 4 app.

All starter modules require OpenJDK 17+.

## Common pitfalls

- **Forgetting to complete / fail / error a job** (Java client, TypeScript). The lease times out and the engine redelivers. Handlers must hit exactly one terminal call on every code path. Spring's `autoComplete = true` covers happy-path returns; failure paths still need an explicit signal.
- **Treating unhandled exceptions as BPMN errors.** An unhandled throw is a programming error, not a modelled outcome. SDKs fail the job with `retries - 1` and `retryBackoff = 0` — the engine redelivers immediately, burns retries, and raises an incident.
- **Storing "already processed" state in the worker process.** Crashes and scale-out erase it. Idempotency belongs in the downstream system or in process variables that survive redelivery.
- **Polling and request-timeout misalignment.** The activation request timeout must be shorter than the gateway / load-balancer cutoff, otherwise the worker tears the connection down and reconnects in a loop. SDK defaults are sensible — change them deliberately.

## References

For SDK-specific detail, read from `references/`:
- [worker-sdk-java.md](references/worker-sdk-java.md) — `camunda-client-java`: client bootstrap, `JobWorkerBuilder`, command builders, streaming, multi-tenancy, OAuth config
- [worker-sdk-spring.md](references/worker-sdk-spring.md) — Camunda Spring Boot Starter: `@JobWorker` parameter reference, `@Variable` / `@VariablesAsType`, `CamundaError`, configuration property tree, Spring Boot 4 vs 3 starter selection
- [worker-sdk-typescript.md](references/worker-sdk-typescript.md) — `@camunda8/orchestration-cluster-api`: `createJobWorker` / `createThreadedJobWorker`, job-handler return shapes, when to fall back to `@camunda8/sdk`
