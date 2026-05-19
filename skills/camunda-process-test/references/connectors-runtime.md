# Connectors runtime in CPT

CPT can spin up the Camunda Connectors runtime alongside Zeebe in the same Testcontainers stack. This lets process tests exercise real outbound/inbound connector behavior (HTTP, Slack, Kafka, AWS, …) instead of mocking the underlying job worker. It is off by default.

## When to enable it

Turn it on when **the connector itself is part of the unit under test** — REST templates with non-trivial `resultExpression`, inbound HTTP webhooks, Kafka subscriptions, custom connector templates whose JSON-shape behavior needs verification.

Leave it off when:

- The connector is a stable production component and the test cares about the process routing, not the connector call.
- The connector calls an LLM, paid third-party API, or any system that costs money or rate-limits in CI.
- The connector requires secrets the test environment can't provide (production API keys, customer credentials).
- The test runs in CI on every commit — the Connectors container adds ~200MB image pull and ~10s startup per cold run.

When skipping the runtime, replace the connector with `context.mockJobWorker(jobType)` (Java) or `MOCK_JOB_WORKER_COMPLETE_JOB` *(8.9+ JSON)* — same result, no container.

## Enabling

### Spring (`@CamundaSpringProcessTest`)

```java
@SpringBootTest(properties = {
    "io.camunda.process.test.connectors-enabled=true",
    "io.camunda.process.test.connectors-secrets.BASE_URL=http://host.testcontainers.internal:9999"
})
@CamundaSpringProcessTest
public class MyConnectorTest { /* … */ }
```

`connectors-secrets.<KEY>=<VALUE>` entries are injected as connector secrets the same way the platform-side `CAMUNDA_CONNECTOR_SECRETS_*` env vars are. Reference them in the BPMN with `{{secrets.KEY}}`.

### Plain JUnit (`CamundaProcessTestExtension`)

```java
@RegisterExtension
private static final CamundaProcessTestExtension EXTENSION =
    new CamundaProcessTestExtension()
        .withConnectorsEnabled(true)
        .withConnectorsSecret("BASE_URL", "http://host.testcontainers.internal:9999");
```

## Accessing the runtime address

```java
processTestContext.getConnectorsAddress();   // URI of the in-test Connectors runtime
```

The address is dynamic — Testcontainers picks a free host port per run. Use it as the target for inbound HTTP webhooks the test triggers:

```java
final HttpPost req = new HttpPost(processTestContext.getConnectorsAddress() + "/inbound/<inbound-id>");
```

`<inbound-id>` is the inbound connector's ID from the BPMN element template.

## WireMock pattern — stubbing the upstream side

Real outbound connectors should not call the public internet from tests. Pair the Connectors runtime with WireMock running on a fixed host port; point the connector at `http://host.testcontainers.internal:<port>` via a secret so the BPMN itself stays environment-agnostic.

```java
@WireMockTest(httpPort = 9999)
@SpringBootTest(properties = {
    "io.camunda.process.test.connectors-enabled=true",
    "io.camunda.process.test.connectors-secrets.BASE_URL=http://host.testcontainers.internal:9999"
})
@CamundaSpringProcessTest
public class MyConnectorTest {

    @BeforeAll
    static void exposeHostPorts() {
        Testcontainers.exposeHostPorts(9999);   // make 9999 reachable from the Connectors container
    }

    @Test
    void outboundHttpCall(@Autowired CamundaClient client) {
        stubFor(get(urlEqualTo("/api/status"))
            .willReturn(aResponse().withStatus(200).withBody("{\"health\":\"UP\"}")));

        // … create a process instance whose REST connector calls {{secrets.BASE_URL}}/api/status …

        verify(getRequestedFor(urlEqualTo("/api/status")));
    }
}
```

`Testcontainers.exposeHostPorts(9999)` is required — without it the Connectors container running inside Docker cannot reach the host's WireMock port.

## Inbound connectors

Inbound connectors (HTTP webhook, polling) wake up the process from outside. To trigger one from a test:

1. Deploy the BPMN with the inbound connector configured (its element template carries an inbound ID — typically a UUID).
2. After `CamundaSpringProcessTest` starts, POST to `processTestContext.getConnectorsAddress() + "/inbound/<inbound-id>"` with the payload the production trigger would send.
3. Assert against the resulting process instance (`CamundaAssert.assertThatProcessInstance(...)` or list instances via the injected `CamundaClient`).

Inbound startup is asynchronous — the connector may need a beat to register its subscription. Wrap the first POST in `Awaitility.await().atMost(Duration.ofSeconds(30))…` if it occasionally returns 404 on the first attempt.

## Anti-patterns

- **Hard-coded URLs in the BPMN that point at `localhost:<fixed port>`.** Wrong twice: localhost from inside the Connectors container is the container, not the test host; and the fixed port can collide in CI. Use a `{{secrets.…}}` reference plus `host.testcontainers.internal` for host-bound services.
- **Real third-party endpoints in CI.** Costs money, flakes on rate limits, and embeds external availability into your test signal.
- **Asserting `hasVariable("health", "UP")` to verify the connector itself works.** That tests the upstream stub, not your process — make the assertion about the BPMN element being completed, not the data it produced (see SKILL.md § Scope boundaries).
