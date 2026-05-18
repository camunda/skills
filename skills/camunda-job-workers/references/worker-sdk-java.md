# Java client — `camunda-client-java`

Plain Java client for Camunda 8.8+, no Spring. The right SDK when the worker process is a standalone JVM application, a non-Spring framework, or a library that needs to embed Zeebe access without bringing Spring transitively.

## Dependency

```xml
<dependency>
  <groupId>io.camunda</groupId>
  <artifactId>camunda-client-java</artifactId>
  <version>${camunda.version}</version>
</dependency>
```

The artifact replaces the **Zeebe Java Client** (`io.camunda:zeebe-client-java`) as of 8.8. The Zeebe client is deprecated; existing code must migrate before 8.10, when it is removed.

Java 17+ required.

## Client bootstrap

```java
try (CamundaClient client = CamundaClient.newClientBuilder()
        .grpcAddress(URI.create("http://localhost:26500"))
        .restAddress(URI.create("http://localhost:8080"))
        .usePlaintext()
        .build()) {

  // workers and commands go here

  Thread.currentThread().join();   // keep the main thread alive while workers run
}
```

Authentication, multi-tenancy, OAuth flags follow the standard builder pattern (`.credentialsProvider(...)`, `.defaultTenantId(...)`). See the [c8ctl docs](https://docs.camunda.io/docs/apis-tools/c8ctl/getting-started/) for the same env-var shape — the client reads the same `ZEEBE_*` / `CAMUNDA_*` variables as `c8ctl`.

## `newWorker()` — the worker builder

```java
JobWorker worker = client.newWorker()
  .jobType("process-order")
  .handler(new OrderHandler())                      // JobHandler — see below
  .timeout(Duration.ofMinutes(1))                   // activation lease
  .pollInterval(Duration.ofMillis(100))             // polling cadence when streaming is off
  .maxJobsActive(32)                                // concurrent leases
  .streamEnabled(true)                              // long-lived stream for low-latency delivery
  .fetchVariables("orderId", "amount")              // ship only these variables
  .name("order-worker")                             // identifier for cluster-side audit
  .tenantIds(List.of("tenant-a"))                   // restrict to tenants
  .open();
// ...
worker.close();                                     // graceful shutdown drains in-flight jobs
```

`JobWorker` implements `AutoCloseable`. Close it explicitly when the application shuts down.

## Handler interface — `JobHandler`

```java
public class OrderHandler implements JobHandler {
  @Override
  public void handle(final JobClient jobClient, final ActivatedJob job) {
    var orderId = (String) job.getVariablesAsMap().get("orderId");
    // ...
    jobClient.newCompleteCommand(job.getKey())
      .variables(Map.of("paymentRef", ref))
      .send().join();
  }
}
```

`job.getVariablesAsType(OrderVars.class)` deserialises the variable map into a POJO via Jackson.

`job.getKey()`, `job.getRetries()`, `job.getCustomHeaders()`, `job.getProcessInstanceKey()`, `job.getElementId()` are the most commonly used metadata accessors.

## Command builders

Three terminal operations on every job. The handler is responsible for hitting exactly one of them on every code path — there is no auto-complete.

### `newCompleteCommand` — success

```java
jobClient.newCompleteCommand(job.getKey())
  .variables(Map.of("paymentRef", ref))   // merged into the process scope
  .send().join();
```

### `newFailCommand` — transient failure

```java
jobClient.newFailCommand(job.getKey())
  .retries(job.getRetries() - 1)
  .retryBackoff(Duration.ofSeconds(10))
  .errorMessage("payment-gateway-timeout")
  .variables(Map.of("attempt", attemptNumber))
  .send().join();
```

Reaching `retries = 0` raises an incident. The engine redelivers after the back-off otherwise.

### `newThrowErrorCommand` — BPMN error

```java
jobClient.newThrowErrorCommand(job.getKey())
  .errorCode("AMOUNT_EXCEEDED")
  .errorMessage("Amount exceeds limit")
  .variables(Map.of("attemptedAmount", amount))
  .send().join();
```

The engine routes the token to the matching error boundary event (or error end event in a subprocess). The job is not retried.

## Streaming vs polling

`streamEnabled(true)` opens a long-lived gRPC unidirectional stream — the engine pushes activated jobs to the worker without a polling round-trip. Lower latency, fewer wasted requests. Polling is the fall-back when streaming is unavailable (mixed-version clusters, network constraints).

Streaming has a graceful fall-back: when the stream drops, the client polls until the stream reopens.

## Lifecycle and shutdown

`JobWorker.close()` stops activating new jobs but lets in-flight handlers run to completion. Wrap the worker in a try-with-resources block or register a JVM shutdown hook to ensure clean exit. Crashing without `close()` leaks the in-flight job leases — the engine reassigns them after the activation timeout, but you may see duplicate processing on the next start.

## Multi-tenancy

`.defaultTenantId(...)` on the client builder sets the tenant for every command unless overridden per-command. `.tenantIds(List.of(...))` on the worker builder restricts which tenants the worker activates jobs from. Without an explicit tenant, the client uses `<default>`.

## Where to look next

- Annotation-driven workers in Spring Boot: `worker-sdk-spring.md`
- TypeScript equivalents: `worker-sdk-typescript.md`
- BPMN element wiring (`zeebe:taskDefinition`): see **camunda-bpmn**
