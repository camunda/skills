# Connectors SDK — inbound (Path B)

Inbound connectors push external events *into* the process engine. Three flavours by trigger source: webhook (HTTP), subscription (message queue), polling (periodic call). All share the `InboundConnectorExecutable` interface and the same `correlateWithResult` contract.

Inbound is connector-only — workers cannot serve inbound. Java 17+.

## Element-attachment variants

An inbound connector ships as a *family* of templates, one per BPMN element the connector can attach to. The connector class is the same; the templates differ only in element-type metadata and binding shape.

| Variant | BPMN element | Effect |
|---|---|---|
| **Start event** | `bpmn:StartEvent` (none-start) | Creates a new process instance per event |
| **Message start event** | `bpmn:StartEvent` (with `bpmn:MessageEventDefinition`) | Creates a new instance, deduplicates by message ID |
| **Intermediate catch event** | `bpmn:IntermediateCatchEvent` | Correlates to a waiting instance via correlation key |
| **Boundary event** | `bpmn:BoundaryEvent` | Interrupting / non-interrupting event attached to an activity |
| **Receive task** | `bpmn:ReceiveTask` | Correlates to a waiting receive task via correlation key |

The `appliesTo` and `elementType` fields in each template select which variant Modeler offers. A polling inbound connector that supports both *intermediate catch* and *receive task* ships two templates with different IDs (e.g. `*.intermediate.v1` and `*.receive.v1`) pointing at the same Java class.

## Dependencies

```xml
<dependency>
  <groupId>io.camunda.connector</groupId>
  <artifactId>connector-core</artifactId>
  <version>${version.connectors}</version>
</dependency>

<dependency>
  <groupId>io.camunda.connector</groupId>
  <artifactId>element-template-generator-annotations</artifactId>
  <version>${version.connectors}</version>
</dependency>
```

For webhook inbound connectors that ride on the built-in webhook framework, add:

```xml
<dependency>
  <groupId>io.camunda.connector</groupId>
  <artifactId>connector-webhook</artifactId>
  <version>${version.connectors}</version>
</dependency>
```

## `InboundConnectorExecutable`

Every inbound connector implements this interface. The runtime calls `activate` once per process-definition deployment that uses the connector and `deactivate` when the deployment is removed or the runtime shuts down. Both methods may be called from arbitrary threads.

```java
@InboundConnector(
    name = "Currency rate watcher",
    type = "io.example.connector.fxrates:1"
)
@ElementTemplate(
    id = "io.example.connector.fxrates.v1",
    name = "Currency rate watcher",
    version = 1,
    inbound = @ElementTemplate.ConnectorElementType(
        appliesTo = {"bpmn:StartEvent"},
        elementType = "bpmn:StartEvent"
    )
)
public class FxRateWatcherExecutable implements InboundConnectorExecutable {

  private ScheduledExecutorService scheduler;
  private InboundConnectorContext context;

  @Override
  public void activate(InboundConnectorContext context) {
    this.context = context;
    var config = context.bindProperties(Config.class);
    scheduler = Executors.newSingleThreadScheduledExecutor();
    scheduler.scheduleAtFixedRate(this::poll, 0, config.pollIntervalSeconds(), TimeUnit.SECONDS);
  }

  @Override
  public void deactivate() {
    if (scheduler != null) {
      scheduler.shutdownNow();
      scheduler = null;
    }
  }

  private void poll() {
    FxRate rate = ...; // fetch the latest rate from the external provider
    var result = context.correlateWithResult(rate);
    if (result instanceof CorrelationResult.Failure failure) {
      context.log(Activity.level(Severity.WARNING)
          .tag("correlation").message("failed: " + failure));
    }
  }

  public record Config(int pollIntervalSeconds, String baseCurrency, String quoteCurrency) {}
}
```

### Lifecycle

- **`activate(InboundConnectorContext)`** — runtime invokes after the process definition referencing the connector is deployed. The connector should start its subscription (webhook listener registration, message-broker consumer, polling thread). Throw to signal activation failure; the runtime logs and the connector stays inactive.
- **`deactivate()`** — runtime invokes when the deployment is removed, the runtime stops, or the connector is re-activated with new configuration. Release all resources. The runtime may call `activate` again immediately (config rotation), so deactivation should leave nothing behind that prevents re-startup.

### `InboundConnectorContext`

Threading-safe helper the connector receives in `activate`. Common surface:

- `bindProperties(Class<T>)` — deserialise the inbound element template properties into a record/POJO. Jakarta Validation applies.
- `correlateWithResult(Object payload)` — push an event to the engine. Returns a `CorrelationResult` describing what the engine did.
- `correlate(Object payload)` — fire-and-forget variant where you don't need the result.
- `cancel(Throwable)` — signal that the connector has hit an unrecoverable error; the runtime deactivates it.
- `log(Activity)` — emit a structured log line surfaced in Operate's connector activity view.
- `getDefinition()` — metadata about the deployment that activated the connector (process definition key, element ID, tenant).

## `correlateWithResult` and `CorrelationResult`

```java
CorrelationResult result = context.correlateWithResult(event);

switch (result) {
  case CorrelationResult.Success success -> {
    // engine accepted the event; success.activatedElement() tells you which element
  }
  case CorrelationResult.Failure failure -> {
    switch (failure.handlingStrategy()) {
      case Pause pause -> /* runtime will retry after pause.duration() */ ;
      case ForwardErrorToUpstream f -> /* propagate back to the source system */ ;
      case Discard d -> /* event was malformed; drop it */ ;
    }
  }
}
```

The handling strategy is determined by the kind of failure (no waiting instance, correlation key mismatch, activation condition false). Webhook flavours typically respond with the strategy's HTTP semantics; polling and subscription flavours respect it as part of the consumer loop (pause = back off, forward = ack with error, discard = ack and move on).

## The three flavours

### Webhook

The runtime exposes an HTTP endpoint per deployed process definition. External systems POST to it; the connector parses the request, validates the signature/auth, and `correlateWithResult`s the payload.

The `connector-webhook` library provides a webhook executable scaffold — your connector extends or composes it rather than implementing the HTTP listening loop yourself. The element template carries the path segment (typically a deployment-scoped suffix to a runtime base URL), the authentication scheme (HMAC, JWT, none), and the response shape.

Inbound webhook templates are the *only* shape where the URL is published by the runtime, not configured by the modeller — the runtime mints the path from deployment metadata.

### Subscription

The runtime opens a connection to a message broker on `activate` and consumes messages until `deactivate`. Examples: Kafka consumer, RabbitMQ subscriber, AWS SQS receiver.

```java
@Override
public void activate(InboundConnectorContext context) {
  var config = context.bindProperties(KafkaConfig.class);
  consumer = new KafkaConsumer<>(toKafkaProps(config));
  consumer.subscribe(List.of(config.topic()));
  pollThread = Thread.ofVirtual().start(this::consumeLoop);
}

private void consumeLoop() {
  while (!Thread.currentThread().isInterrupted()) {
    var records = consumer.poll(Duration.ofSeconds(1));
    for (var record : records) {
      var result = context.correlateWithResult(record.value());
      handleResult(record, result);
    }
  }
}
```

Acknowledgement strategy (commit on every event vs. on success vs. on batch) is exposed via the template's *Subscription* group when supported by the connector — see the `<features><ACKNOWLEDGEMENT_STRATEGY_SELECTION>` Maven plugin flag for templates that should surface this control.

### Polling

The runtime schedules the connector to call an external system on a cadence. Use a `ScheduledExecutorService`, `Thread.ofVirtual().scheduleAtFixedRate` (8.10+), or a similar scheduler. Each tick fetches, transforms, and `correlateWithResult`s.

Polling connectors typically also offer deduplication via `INBOUND_DEDUPLICATION` (Maven plugin feature flag) — the runtime tracks payload IDs and suppresses duplicate correlations.

## Inbound element template — binding differences

Inbound templates differ from outbound on two key bindings:

- **Connector type binding**: `zeebe:property` with `name: "inbound.type"` instead of `zeebe:taskDefinition`.
- **Property values**: typically bound via `zeebe:property` with `name: "<key>"` instead of `zeebe:input`.

```json
{
  "type": "Hidden",
  "value": "io.example.connector.fxrates:1",
  "binding": { "type": "zeebe:property", "name": "inbound.type" }
},
{
  "id": "pollIntervalSeconds",
  "label": "Poll interval (seconds)",
  "type": "String",
  "feel": "optional",
  "binding": { "type": "zeebe:property", "name": "pollIntervalSeconds" }
}
```

For message-correlated variants (intermediate catch, receive task, message start), the template also needs message-correlation properties:

- `bpmn:Message#property` for the message name
- `bpmn:Message#zeebe:subscription#property` for the correlation-key expression

Schema-level detail is in `element-template-json.md`.

## SPI registration

```
META-INF/services/io.camunda.connector.api.inbound.InboundConnectorExecutable
```

One class name per line. The Maven plugin writes this file automatically when `writeMetaInfFileGeneration` is left at its default (`true`).

## Hybrid hosting and inbound

When the runtime hosting the inbound connector runs *outside* the Camunda cluster (Hybrid mode — standalone runtime against SaaS), the external system pointing at the webhook must reach the standalone runtime's network address, not the SaaS cluster's. Plan the public DNS / firewall accordingly. Subscription and polling flavours don't have this caveat — the runtime initiates the connections outbound.

## Where to look next

- Outbound counterpart (`OutboundConnectorProvider`, `@Operation`): `connector-sdk-outbound.md`
- Element template schema for inbound variants: `element-template-json.md`
- Auto-generating inbound templates from `@ElementTemplate`: `element-template-generator.md`
- Picking SPI vs Spring Bean registration and a hosting model: `registration-and-hosting.md`
