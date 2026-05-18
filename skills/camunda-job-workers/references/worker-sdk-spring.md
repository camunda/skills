# Camunda Spring Boot Starter — `@JobWorker` reference

Annotation-driven workers for Spring Boot applications on Camunda 8.8+. Drop-in dependency, no manual client lifecycle.

## Dependency

```xml
<dependency>
  <groupId>io.camunda</groupId>
  <artifactId>camunda-spring-boot-starter</artifactId>
  <version>${camunda.version}</version>
</dependency>
```

`camunda-spring-boot-starter` is bundled with and requires Spring Boot 4.0.x. If the application is still on Spring Boot 3.5.x, use `camunda-spring-boot-3-starter` instead — same coordinate prefix, same surface, different transitive Spring Boot version. Spring's OSS support for Spring Boot 3.5.x ends June 2026.

Do not mix the two starters on one classpath.

The starter replaces the deprecated **Spring Zeebe SDK** (`spring-zeebe-starter` / `io.camunda.spring:spring-boot-starter-camunda-sdk`); existing applications should migrate.

## `@JobWorker` parameters

```java
@JobWorker(
  type = "process-order",        // job type; defaults to the method name if omitted
  name = "order-worker",         // worker identifier surfaced in cluster operations
  autoComplete = true,           // call complete with the method's return value; default true
  fetchVariables = {"orderId","amount"},  // engine ships only these variables with the job
  fetchAllVariables = false,     // override — ship every variable in the instance scope
  timeout = 60_000,              // activation lease in milliseconds
  maxJobsActive = 32,            // engine-side cap on concurrent leases for this worker
  pollInterval = 100,            // ms between polling requests when no jobs are streamed
  requestTimeout = 10_000,       // ms the activation request waits for the engine
  streamEnabled = true,          // long-lived stream for low-latency delivery
  tenantIds = {"tenant-a"},      // restrict to specific tenants
  retryBackoff = 5_000,          // default ms back-off when failing without an explicit value
  enabled = true                 // toggle the worker without removing the annotation
)
public Map<String, Object> processOrder(@Variable String orderId, @Variable BigDecimal amount) {
  // ...
}
```

All parameters are optional; sensible defaults apply. `maxJobsActive` defaults to 64.

## Handler-method shape

The method body is the handler. Parameter binding is annotation-driven:

- **`@Variable("name")`** — bind one process variable to a parameter. If the JSON name and the Java parameter name match, the value is optional.
- **`@VariablesAsType ProcessVars vars`** — deserialise the entire variable map into a POJO (Jackson).
- **`@CustomHeaders Map<String,String> headers`** — read static `zeebe:taskHeaders` declared on the task.
- **`ActivatedJob job` / `JobClient jobClient`** — escape hatches for the raw types when `autoComplete = false`.

Return type:
- `void` — auto-completes with no variables.
- `Map<String, Object>` or a serialisable POJO — auto-completes with that as the variable payload.
- `CompleteJobCommandStep1` — manually built command. Pair with `autoComplete = false`.

## Signalling failure — `CamundaError`

Three terminal paths, picked by what the failure means:

```java
// 1. BPMN error — modelled business outcome. Engine takes the error boundary path.
throw CamundaError.bpmnError("AMOUNT_EXCEEDED", "Amount exceeds limit");

// 2. Job failure — transient. Engine redelivers after retryBackoff; raises an incident at 0.
throw CamundaError.jobError(
  "payment-gateway-timeout",          // errorMessage
  Map.of("attempt", attemptNumber),   // optional variables to set on the job
  job.getRetries() - 1,               // remaining retries (default: job.getRetries() - 1)
  Duration.ofSeconds(10),             // retryBackoff (default: configured value)
  e                                   // cause (optional)
);

// 3. Unhandled exception — default fall-back. retries -= 1, retryBackoff = 0. Programming-error semantics.
//    Don't reach for this deliberately.
throw new RuntimeException("unexpected");
```

`jobError` accepts a `Function<Integer, Duration>` for `retryBackoff` to compute the back-off from the remaining-retries count (exponential back-off, jitter, etc.).

## Configuration tree (`camunda.client.*`)

```yaml
camunda:
  client:
    mode: self-managed          # saas | self-managed
    auth:
      method: none              # none | basic | oidc
      client-id: ...
      client-secret: ...
    zeebe:
      grpc-address: http://localhost:26500
      rest-address: http://localhost:8080
    tenant-ids: [default]       # multi-tenancy
    worker:
      defaults:                 # apply to every @JobWorker unless overridden
        timeout: 30000
        max-jobs-active: 32
      override:                 # per-job-type overrides
        process-order:
          max-jobs-active: 8
```

`camunda.client.worker.defaults.<property>` sets the floor for all workers; `camunda.client.worker.override.<jobType>.<property>` wins over both the default and the annotation value.

## Profile activation

Spring profiles compose naturally with `@JobWorker`:

```java
@Component
@Profile("payments")
class PaymentWorker {
  @JobWorker(type = "charge-card")
  public void charge(...) { ... }
}
```

Workers in inactive profiles are not registered against the engine, so a single application can host a different set of workers per profile / per deployment.

## Wiring to a BPMN service task

The handler's `type` must match the BPMN element's `<zeebe:taskDefinition type="..."/>` exactly. Apply the task type via `camunda-bpmn`; the engine activates the matching worker once a process instance reaches the task.

## Multi-tenancy

`tenantIds` on the annotation restricts which tenants the worker activates jobs from. Without it, the worker picks up jobs from every tenant the client is authorised against. Combine with `camunda.client.tenant-ids` for the global default.
