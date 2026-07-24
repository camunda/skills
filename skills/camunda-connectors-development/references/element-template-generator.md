# Element-template generator (Maven plugin)

The `element-template-generator-maven-plugin` reads `@ElementTemplate`-annotated classes and emits one or more element template JSON files at build time. Saves writing the template by hand and keeps the Java code and the JSON in lock-step.

Path B only. Path A templates are hand-edited JSON.

## Annotation dependency

```xml
<dependency>
  <groupId>io.camunda.connector</groupId>
  <artifactId>element-template-generator-annotations</artifactId>
  <version>${version.connectors}</version>
</dependency>
```

Provides `@ElementTemplate`, `@PropertyGroup`, `@TemplateProperty`, and the supporting types referenced from the connector class.

## `@ElementTemplate` on the connector class

```java
@OutboundConnector(name = "Country lookup", type = "io.example.connector.countries:1",
    inputVariables = { "lookupBy", "query" })
@ElementTemplate(
    id = "io.example.connector.countries.v1",
    name = "Country lookup",
    version = 1,
    description = "Look up country reference data via the REST Countries API",
    documentationRef = "https://restcountries.com",
    icon = "countries.svg",
    inputDataClass = LookupRequest.class,
    propertyGroups = {
      @PropertyGroup(id = "lookup", label = "Country lookup"),
      @PropertyGroup(id = "output", label = "Output mapping")
    }
)
public class CountryLookupConnector implements OutboundConnectorProvider { ... }
```

The `inputDataClass` points to the record/POJO whose `@TemplateProperty`-annotated fields drive the template's `properties` array. Inbound connectors add an `inbound = @ElementTemplate.ConnectorElementType(...)` clause per element variant; multi-element connectors declare one variant per BPMN attachment.

`@TemplateProperty` on the input class:

```java
public record LookupRequest(
    @TemplateProperty(
        id = "lookupBy",
        label = "Lookup by",
        group = "lookup",
        type = TemplateProperty.PropertyType.Dropdown,
        choices = {
            @TemplateProperty.PropertyChoice(label = "Name",            value = "name"),
            @TemplateProperty.PropertyChoice(label = "Capital",         value = "capital"),
            @TemplateProperty.PropertyChoice(label = "ISO 3166-1 code", value = "alpha"),
            @TemplateProperty.PropertyChoice(label = "Currency",        value = "currency")
        }
    )
    @NotEmpty String lookupBy,

    @TemplateProperty(id = "query", label = "Query value", group = "lookup",
                      feel = TemplateProperty.FeelMode.optional)
    @NotEmpty String query
) {}
```

The annotation surface mirrors the element template JSON schema — see `element-template-json.md` for the underlying fields.

## Plugin configuration — SPI shape (default)

```xml
<plugin>
  <groupId>io.camunda.connector</groupId>
  <artifactId>element-template-generator-maven-plugin</artifactId>
  <version>${version.connectors}</version>
  <configuration>
    <connectors>
      <connector>
        <connectorClass>io.example.connector.countries.CountryLookupConnector</connectorClass>
        <files>
          <file>
            <templateId>io.example.connector.countries.v1</templateId>
            <templateFileName>countries-outbound-connector.json</templateFileName>
          </file>
        </files>
        <generateHybridTemplates>true</generateHybridTemplates>
      </connector>
    </connectors>
    <versionHistoryEnabled>true</versionHistoryEnabled>
  </configuration>
</plugin>
```

Run `mvn package` (or `mvn process-classes` to skip tests) and the templates land in `target/generated-resources/element-templates/`.

### Multiple connector classes

```xml
<connectors>
  <connector>
    <connectorClass>io.example.connector.countries.CountryLookupConnector</connectorClass>
    <files>
      <file>
        <templateId>io.example.connector.countries.v1</templateId>
        <templateFileName>countries-outbound-connector.json</templateFileName>
      </file>
    </files>
    <generateHybridTemplates>true</generateHybridTemplates>
  </connector>
  <connector>
    <connectorClass>io.example.connector.fxrates.FxRateWatcherExecutable</connectorClass>
    <files>
      <file>
        <templateId>io.example.connector.fxrates.intermediate.v1</templateId>
        <templateFileName>fxrates-inbound-intermediate.json</templateFileName>
      </file>
      <file>
        <templateId>io.example.connector.fxrates.receive.v1</templateId>
        <templateFileName>fxrates-inbound-receive.json</templateFileName>
      </file>
    </files>
    <generateHybridTemplates>false</generateHybridTemplates>
  </connector>
</connectors>
```

One `<connector>` per Java class. Multiple `<file>` entries on the same connector emit different template variants from the same `@ElementTemplate` — typically used for inbound connectors that support both intermediate catch and receive task.

## Configuration fields

### Per-connector

- **`<connectorClass>`** — fully-qualified class name of the `OutboundConnectorProvider` / `OutboundConnectorFunction` / `InboundConnectorExecutable`.
- **`<files>`** — one or more `<file>` blocks; each declares `<templateId>` (must match `@ElementTemplate.id` or a per-variant id) and `<templateFileName>` (output JSON name).
- **`<generateHybridTemplates>`** — `true` to additionally emit `*-hybrid.json` for each `<file>`. Hybrid templates rewrite the connector binding to a form a SaaS engine can route to a standalone runtime. Set `false` on inbound polling/webhook variants where Hybrid mode isn't supported by the connector.
- **`<writeMetaInfFileGeneration>`** — `true` (default) writes `META-INF/services/...` for SPI registration. **Set to `false` when registering the connector as a Spring Bean** (`@Component`) inside `connector-runtime-spring`; otherwise the bean and the SPI both register the class and you get duplicate instances.
- **`<features>`** — per-feature toggles surfaced as additional template properties. Common keys: `ACKNOWLEDGEMENT_STRATEGY_SELECTION` (subscription connectors), `INBOUND_DEDUPLICATION` (inbound polling/webhook).

### Top-level

- **`<versionHistoryEnabled>`** — `true` writes a versioned copy of each template alongside the current one (e.g. `countries-outbound-connector.json` plus `countries-outbound-connector-v1.json`). Lets older process versions stay pinned to their template version after the connector ships a new one.
- **`<includeDependencies>`** — `groupId:artifactId` pairs whose classpath should be scanned for additional `@ElementTemplate` classes. Used when the connector inherits template structure from a base module (e.g. webhook connectors riding on `connector-webhook`).

## Hybrid templates

`<generateHybridTemplates>true</generateHybridTemplates>` emits a parallel `*-hybrid.json` for each output. The hybrid variant flips the connector's `zeebe:taskDefinition.type` (or `zeebe:property name="inbound.type"` for inbound) to a job-worker-style binding the SaaS engine can route to a standalone runtime running outside SaaS.

Without the hybrid template, deploying the standard template to SaaS and trying to drive it from a self-hosted runtime produces a runtime that can never receive jobs — the SaaS engine looks for the connector internally and finds nothing.

Drop the flag (or set it to `false`) when:

- The connector will only run on SaaS managed runtime (impossible for custom connectors — SaaS managed only runs the OOTB set), or
- The connector will only run on Self-Managed (no Hybrid use case), or
- The connector flavour doesn't support Hybrid (inbound polling and webhook flavours often don't, because the external system has to reach the standalone runtime's network).

## Auto-generated SPI files

When `<writeMetaInfFileGeneration>` is left `true`, the plugin writes:

- `target/classes/META-INF/services/io.camunda.connector.api.outbound.OutboundConnectorProvider` (modern outbound)
- `target/classes/META-INF/services/io.camunda.connector.api.outbound.OutboundConnectorFunction` (legacy outbound)
- `target/classes/META-INF/services/io.camunda.connector.api.inbound.InboundConnectorExecutable` (inbound)

Each lists fully-qualified class names. Don't hand-write these unless you've disabled the plugin's generation — they'll drift.

## Output layout

After `mvn package`:

```
target/
├── classes/
│   └── META-INF/services/...           (SPI files, if writeMetaInfFileGeneration=true)
└── generated-resources/element-templates/
    ├── countries-outbound-connector.json
    ├── countries-outbound-connector-hybrid.json   (if generateHybridTemplates=true)
    └── countries-outbound-connector-v1.json       (if versionHistoryEnabled=true)
```

Commit the generated templates to your repo (or copy them into Modeler's resources directory) so process developers can pick them up without running the build first. Treat them as build artefacts checked in for convenience — re-run the plugin and re-commit on every annotation change.

## Where to look next

- `@ElementTemplate` annotation surface and JSON schema parity: `element-template-json.md`
- Outbound connector class shape: `connector-sdk-outbound.md`
- Inbound connector class shape: `connector-sdk-inbound.md`
- Pairing the plugin with Spring Bean registration (`writeMetaInfFileGeneration=false`): `registration-and-hosting.md`
