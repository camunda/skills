# Connectors SDK — outbound (Path B)

Build a custom outbound connector in Java. The SDK provides input binding, secrets resolution, output mapping, and BPMN-error semantics; the auto-generated element template gives users a Modeler UI. Java 17+.

## Dependencies

```xml
<dependency>
  <groupId>io.camunda.connector</groupId>
  <artifactId>connector-core</artifactId>
  <version>${version.connectors}</version>
</dependency>

<!-- enables Jakarta Validation on @Variable / property bindings -->
<dependency>
  <groupId>io.camunda.connector</groupId>
  <artifactId>connector-validation</artifactId>
  <version>${version.connectors}</version>
</dependency>

<!-- annotations for @ElementTemplate-driven template generation -->
<dependency>
  <groupId>io.camunda.connector</groupId>
  <artifactId>element-template-generator-annotations</artifactId>
  <version>${version.connectors}</version>
</dependency>
```

`${version.connectors}` should match the runtime image / starter you intend to deploy against. Pin it explicitly — connectors and the engine version together to support new binding types and template features.

## Modern pattern — `OutboundConnectorProvider` + `@Operation`

One class can declare multiple operations. The connector type identifies the class; the operation identifies which method to call. Element template generation produces one template per `@Operation`.

```java
@OutboundConnector(
    name = "Star Wars API",
    type = "io.example.connector.swapi:1",
    inputVariables = { "resource", "index" }
)
@ElementTemplate(
    id = "io.example.connector.swapi.v1",
    name = "Star Wars API",
    version = 1,
    documentationRef = "https://swapi.dev",
    icon = "swapi.svg"
)
public class SwapiConnector implements OutboundConnectorProvider {

  private final HttpClient http = HttpClient.newHttpClient();

  @Operation(id = "lookup")
  public Person lookup(
      @Variable @NotEmpty String resource,
      @Variable @NotEmpty String index
  ) throws ConnectorException {
    var uri = URI.create("https://swapi.dev/api/" + resource + "/" + index);
    var request = HttpRequest.newBuilder(uri).GET().build();
    try {
      var response = http.send(request, BodyHandlers.ofString());
      if (response.statusCode() == 404) {
        throw new ConnectorException("NOT_FOUND", "No " + resource + "/" + index);
      }
      if (response.statusCode() >= 400) {
        throw new ConnectorException("SWAPI_ERROR", "Status " + response.statusCode());
      }
      return new ObjectMapper().readValue(response.body(), Person.class);
    } catch (IOException | InterruptedException e) {
      throw new ConnectorException("SWAPI_UNREACHABLE", e.getMessage(), e);
    }
  }

  public record Person(String name, String birthYear, String gender) {}
}
```

The return value is serialised and merged into the process scope per the element template's *Output mapping* group.

### `@Variable` and `@Header`

- **`@Variable`** binds a process variable into the parameter. Add `@Variable(name = "...")` if the parameter name and the variable name differ. Complex types (records, POJOs) auto-bind by property name and accept Jakarta Validation annotations on their fields.
- **`@Header`** binds a static task header declared via `zeebe:taskHeader` (typically pre-filled by the template — protocol selection, output mode, retry policy).

```java
@Operation(id = "send")
public SendResult send(
    @Variable @Valid Message message,
    @Variable @NotEmpty String channelId,
    @Header("priority") String priority
) { ... }

public record Message(@NotBlank String subject, @NotBlank String body) {}
```

Validation failures throw before the method body runs, surfacing as a `ConnectorException` with code `VALIDATION_FAILED`.

### `ConnectorException`

`ConnectorException(code, message)` is the typed channel that the element template's `errorExpression` taps into. Users wire `errorExpression` to map specific codes to BPMN errors:

```feel
if error.code = "NOT_FOUND"   then bpmnError("NOT_FOUND", error.message) else
if error.code = "SWAPI_ERROR" then bpmnError("UPSTREAM",  error.message) else
null
```

Returning `null` from `errorExpression` lets the engine fall through to incident-raising. Codes used should be stable — they're part of the connector's contract with process modellers.

## Legacy pattern — `OutboundConnectorFunction`

Older connectors and the historical `connector-template-outbound` GitHub-template scaffolds use a single-method interface. Still supported; prefer the modern pattern for new code, but recognise this shape in brownfield repos.

```java
@OutboundConnector(
    name = "Star Wars API",
    type = "io.example.connector.swapi:1",
    inputVariables = { "resource", "index" }
)
@ElementTemplate(id = "io.example.connector.swapi.v1", name = "Star Wars API", version = 1)
public class SwapiFunction implements OutboundConnectorFunction {

  @Override
  public Object execute(OutboundConnectorContext context) throws Exception {
    var request = context.bindVariables(SwapiRequest.class);
    var uri = URI.create("https://swapi.dev/api/" + request.resource() + "/" + request.index());
    // ...
    return new Person(...);
  }

  public record SwapiRequest(@NotEmpty String resource, @NotEmpty String index) {}
}
```

`context.bindVariables(...)` deserialises the variable map into a record/POJO and applies Jakarta Validation. `context.getJobContext().getCustomHeaders()` reads `zeebe:taskHeader` values.

The legacy pattern hosts only one operation per class. Multi-operation connectors must split classes (or migrate to `OutboundConnectorProvider`).

### SPI file — legacy vs. modern

The SPI file path differs between the two patterns:

- Modern: `META-INF/services/io.camunda.connector.api.outbound.OutboundConnectorProvider`
- Legacy: `META-INF/services/io.camunda.connector.api.outbound.OutboundConnectorFunction`

Each file lists fully-qualified class names, one per line. The `element-template-generator-maven-plugin` writes the file automatically; set `<writeMetaInfFileGeneration>false</writeMetaInfFileGeneration>` when using Spring Bean registration instead (see `registration-and-hosting.md`).

## Secrets

The SDK resolves `{{secrets.NAME}}` placeholders during `bindVariables` / parameter binding — the connector code never sees raw placeholder strings. The standalone runtime (8.9+) reads secret values from environment variables prefixed `SECRET_` (configurable via `CAMUNDA_CONNECTOR_SECRET_PROVIDER_*` env vars). Document secret names in the connector's README so operators know what to set.

```java
@Operation(id = "send")
public SendResult send(@Variable @NotEmpty String apiKey, ...) {
  // apiKey holds the resolved secret value, never "{{secrets.MY_KEY}}"
}
```

## Camunda Documents

For payloads that produce or consume binary content, accept / return `CamundaDocument` (or its reference type, depending on SDK version) instead of byte arrays. The runtime handles upload, download, and reference passing. Plain Java byte arrays force the operator to pre-stage data via custom variables — a much rougher seam.

## Jakarta Validation

Connector parameter binding flows through Hibernate Validator (via the optional `connector-validation` dependency). Standard annotations:

- `@NotNull`, `@NotEmpty`, `@NotBlank` — field presence
- `@Pattern(regexp = "...")` — string shape
- `@Min`, `@Max`, `@Size` — numeric / collection bounds
- `@Valid` — recurse into nested records / POJOs

Combine on records to validate the entire input atomically:

```java
public record SendRequest(
    @NotBlank @Email String recipient,
    @NotBlank @Size(max = 256) String subject,
    @NotNull @Valid Body body
) {}
```

## Where to look next

- Element template generation from `@ElementTemplate`: `element-template-generator.md`
- Element template schema reference (property types, bindings): `element-template-json.md`
- Inbound counterpart (`InboundConnectorExecutable`): `connector-sdk-inbound.md`
- Registering the connector (SPI vs Spring Bean) and choosing a hosting model: `registration-and-hosting.md`
