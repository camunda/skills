# Registration and hosting

Two orthogonal decisions every Path B connector has to make:

1. **Registration** — how does the connector runtime *find* your connector class? SPI file or Spring Bean.
2. **Hosting** — where does the runtime run? SaaS, Self-Managed standalone, Self-Managed embedded, or Hybrid.

The two interact: Spring Bean registration only works inside an embedded Spring Boot runtime; SPI works in both standalone and embedded.

## Registration: SPI vs. Spring Bean

### SPI (default)

The Java ServiceLoader pattern. A file at `META-INF/services/<interface>` lists the implementing class names, one per line:

```
META-INF/services/io.camunda.connector.api.outbound.OutboundConnectorProvider
```
```
io.example.connector.countries.CountryLookupConnector
```

The element-template-generator Maven plugin writes this file automatically (`<writeMetaInfFileGeneration>true</writeMetaInfFileGeneration>`, default). The connector requires only `connector-core` and (optionally) `connector-validation` on its compile classpath.

SPI is the right choice for:

- Connectors shipped as standalone JARs for the **Self-Managed standalone** runtime.
- Connectors deployed in **Hybrid** mode.
- Anything you want to keep small (no Spring transitives in the JAR).

### Spring Bean

The connector class is a `@Component` (or any Spring bean) inside an application built on `connector-runtime-spring`. Discovery is via Spring's component scan, not via the SPI file.

```java
@Component
@OutboundConnector(name = "...", type = "...", inputVariables = {...})
@ElementTemplate(id = "...", name = "...", version = 1)
public class CountryLookupConnector implements OutboundConnectorProvider { ... }
```

Required dependencies:

```xml
<dependency>
  <groupId>io.camunda.connector</groupId>
  <artifactId>connector-runtime-spring</artifactId>
  <version>${version.connectors}</version>
</dependency>
<dependency>
  <groupId>io.camunda.connector</groupId>
  <artifactId>connector-runtime-core</artifactId>
  <version>${version.connectors}</version>
</dependency>
<!-- plus the standard Spring Boot starters the host application needs -->
```

**Always disable SPI file generation when registering as a Spring Bean.** Both mechanisms registering the same class causes the runtime to instantiate two distinct instances of the connector — they share class but not state, and the second silently shadows the first for routing purposes. Set:

```xml
<configuration>
  <connectors>
    <connector>
      <connectorClass>io.example.connector.countries.CountryLookupConnector</connectorClass>
      <writeMetaInfFileGeneration>false</writeMetaInfFileGeneration>
      ...
    </connector>
  </connectors>
</configuration>
```

Spring Bean is the right choice for:

- Connectors shipped as part of an **embedded** Spring Boot application where workers and connectors coexist.
- Connectors that need to take advantage of Spring DI (inject services, configuration properties, observability hooks).

## Hosting

Four runtime environments. Path B can target any of them.

### SaaS managed runtime

Camunda runs the standard OOTB connectors on SaaS. **Custom connectors are not supported on the managed runtime** — there is no mechanism to upload a custom JAR to SaaS. Path B on a SaaS engine requires Hybrid mode.

Path A protocol-template customisations work fine on SaaS because they layer on OOTB protocol connectors that the SaaS runtime already hosts.

### Self-Managed standalone

The `camunda/connectors:X.Y.Z` Docker image. Runs separately from the Zeebe broker; pulls jobs over the standard client API.

Mount the connector JAR into `/opt/app/`:

```bash
docker run --rm --name=connectors -d \
  -v $PWD/countries-connector.jar:/opt/app/countries-connector.jar \
  -e CAMUNDA_CLIENT_MODE=self-managed \
  -e CAMUNDA_CLIENT_GRPC_ADDRESS=http://localhost:26500 \
  -e CAMUNDA_CLIENT_REST_ADDRESS=http://localhost:8080 \
  -e CAMUNDA_CLIENT_AUTH_METHOD=none \
  camunda/connectors:X.Y.Z
```

A single mount path (`/opt/app/`) handles both outbound and inbound JARs. Drop multiple JARs into the same path to host several custom connectors in one runtime.

Auth and cluster wiring use the same `CAMUNDA_CLIENT_*` env vars as `c8ctl` and the Java client (`CAMUNDA_CLIENT_AUTH_METHOD` = `none` | `basic` | `oidc`; OIDC pulls `CAMUNDA_CLIENT_AUTH_CLIENTID` + `CAMUNDA_CLIENT_AUTH_CLIENTSECRET` + `CAMUNDA_CLIENT_AUTH_TOKENURL`).

Secrets: the 8.9+ runtime reads from environment variables prefixed `SECRET_` by default. `{{secrets.MY_KEY}}` in a template defaults to `$SECRET_MY_KEY` at runtime. The prefix is configurable via `CAMUNDA_CONNECTOR_SECRET_PROVIDER_*` env vars.

Use SPI registration. The standalone runtime is not a Spring Boot application that scans your beans.

#### Local development: standalone JAR with custom connectors

When developing a custom connector locally, you need to run the standalone connector runtime JAR with your connector loaded into `-Dloader.path=./custom_connectors`. This is distinct from c8run's bundled runtime, which runs OOTB connectors only and does not load JARs from a custom directory.

**The env-var override trap:** `ZEEBE_ADDRESS`, `CAMUNDA_CLIENT_ID`, and `CAMUNDA_CLIENT_SECRET` take precedence over any properties file. If those are set in your shell (common if you also use SaaS), the runtime will connect to the SaaS cluster even when you pass a local config file. Local jobs will never be picked up and no error is shown.

Always start the local runtime with those vars explicitly unset:

```bash
env -u ZEEBE_ADDRESS -u CAMUNDA_CLIENT_ID -u CAMUNDA_CLIENT_SECRET \
  -u ZEEBE_CLIENT_ID -u ZEEBE_CLIENT_SECRET \
  nohup java \
    -Dloader.path=./custom_connectors \
    -jar connector-runtime-bundle-<version>-with-dependencies.jar \
    --spring.config.additional-location=./connectors-application.properties \
  > ./log/connectors.log 2>&1 &
```

`connectors-application.properties` must declare all four of these for a local c8run cluster:

```properties
server.port=8086
camunda.client.grpc-address=http://localhost:26500
camunda.client.rest-address=http://localhost:8080
camunda.client.auth.enabled=false
```

**Verify the connector runtime is connected to the local cluster, not SaaS**, via the actuator health endpoint:

```bash
curl -s http://localhost:8086/actuator/health | python3 -c "
import json, sys
d = json.load(sys.stdin)
zc = d.get('components', {}).get('zeebeClient', {})
brokers = zc.get('details', {}).get('numBrokers', 0)
print(f'status={d[\"status\"]} | zeebeClient={zc.get(\"status\")} | numBrokers={brokers}')
"
```

`numBrokers: 1` = local Zeebe. `numBrokers: 3` = connected to SaaS cluster — stop the process and restart with the cloud env vars unset.

### Self-Managed embedded

A Spring Boot application that hosts both connectors and your own business code. The starter provides the connector runtime and registers SPI- and bean-discovered connectors against the cluster.

```xml
<dependency>
  <groupId>io.camunda.connector</groupId>
  <artifactId>spring-boot-starter-camunda-connectors</artifactId>
  <version>${version.connectors}</version>
</dependency>
```

Spring Bean or SPI registration both work in this mode (don't combine the two for the same class). Cluster wiring is via the standard `camunda.client.*` Spring properties — same shape the Camunda Spring Boot Starter uses for job workers.

### Hybrid

The standalone Docker runtime running in your environment, connected to a SaaS cluster. Required when:

- The engine has to be SaaS (managed) but the connector needs to reach a system inside your network perimeter (private API, on-prem database, internal queue).
- You want SaaS's managed engine but Path B connectors that aren't part of the OOTB catalog.

Run the same `camunda/connectors:X.Y.Z` image as Self-Managed standalone, but point it at the SaaS cluster:

```bash
docker run ... \
  -e CAMUNDA_CLIENT_MODE=saas \
  -e CAMUNDA_CLIENT_CLOUD_CLUSTERID=<cluster-id> \
  -e CAMUNDA_CLIENT_CLOUD_REGION=<region> \
  -e CAMUNDA_CLIENT_AUTH_CLIENTID=<saas-client-id> \
  -e CAMUNDA_CLIENT_AUTH_CLIENTSECRET=<saas-client-secret> \
  camunda/connectors:X.Y.Z
```

**Deploy the `-hybrid.json` template variant**, not the standard one. The hybrid template rewrites the connector binding so the SaaS engine routes jobs to your standalone runtime rather than looking for the connector internally. Generated via `<generateHybridTemplates>true</generateHybridTemplates>` (see `element-template-generator.md`).

**Inbound caveat for Hybrid**: webhook inbound connectors expose an HTTP endpoint on the runtime hosting them. In Hybrid, that's your standalone runtime — the external caller must be able to reach *your* address, not SaaS's. Plan DNS/firewall accordingly. Subscription and polling inbound flavours don't have this caveat because the runtime initiates the connections outbound.

## Matrix

| Hosting | Registration | Maven plugin flags |
|---|---|---|
| SaaS managed | n/a (custom unsupported — use Hybrid) | n/a |
| SM standalone | SPI | `<generateHybridTemplates>` may be `false` |
| SM embedded | SPI **or** Spring Bean (not both) | Spring Bean needs `<writeMetaInfFileGeneration>false</writeMetaInfFileGeneration>` |
| Hybrid (standalone runtime → SaaS) | SPI | `<generateHybridTemplates>true</generateHybridTemplates>`, deploy the `-hybrid.json` variant |

## Configuring secrets

Element templates and Java code reference secrets via `{{secrets.NAME}}`. The runtime resolves them at execution time.

- **Standalone / Hybrid (8.9+)**: environment variables with the `SECRET_` prefix. `{{secrets.MY_KEY}}` resolves to `$SECRET_MY_KEY`. The prefix is configurable (`CAMUNDA_CONNECTOR_SECRET_PROVIDER_ENVIRONMENT_PREFIX`); also pluggable for vault providers.
- **Embedded**: Spring application configures secret providers via `camunda.connector.secret-providers.*` properties.
- **SaaS**: secret values are managed via the SaaS console; templates reference the same `{{secrets.NAME}}` shape.

Never put secret material in template defaults, BPMN attributes, or hard-coded Java strings — the `{{secrets.NAME}}` placeholder is the only safe path.

## Picking a combination

- **Most common for an organisation already running Self-Managed**: SM standalone + SPI registration. Smallest connector JARs, no Spring transitives, one runtime image hosts many connectors.
- **Java-team-internal connector inside an existing Spring Boot job-worker app**: SM embedded + Spring Bean registration. The connector lives in the same codebase as the workers; CI ships one artefact.
- **SaaS engine, custom connector for an internal system**: Hybrid + SPI registration + `generateHybridTemplates=true`. The runtime runs inside your perimeter; the engine doesn't.
- **OOTB-only deployment**: no Path B at all — see **camunda-connectors**.

## Where to look next

- Maven plugin flags (`writeMetaInfFileGeneration`, `generateHybridTemplates`, `versionHistoryEnabled`): `element-template-generator.md`
- Outbound connector class shape: `connector-sdk-outbound.md`
- Inbound connector class shape (`activate`/`deactivate` lifecycle and the three flavours): `connector-sdk-inbound.md`
- Element template schema (for the hybrid-template differences in `zeebe:taskDefinition`/`zeebe:property`): `element-template-json.md`
