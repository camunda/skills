---
name: camunda-connectors-development
description: |
  Use this skill to build a custom Camunda 8 connector — outbound or inbound — when the OOTB catalog doesn't cover the integration. Two paths: a JSON-only element template on a protocol connector (no Java), or a Java connector via the Connectors SDK with annotation-driven template generation.

  Use for: choosing Path A (JSON-only protocol-connector template) vs Path B (custom Java); element template JSON; `OutboundConnectorProvider` + `@Operation` for outbound; `InboundConnectorExecutable` for webhook / subscription / polling inbound; SPI vs Spring-Bean registration; SaaS / SM / Hybrid hosting; element-template-generator Maven plugin.

  Do not use for: applying an OOTB connector (use camunda-connectors), worker-vs-connector decisions (use camunda-development), or job-worker handlers (use camunda-job-workers).

  **Workflow skill** — pick a path, write the template (and Java if Path B), register, host. Java 17+ on Path B.
---

# Camunda Connectors Development

Build a custom Camunda 8 connector when the OOTB catalog doesn't cover the integration. Two distinct paths share the same element-template surface but differ in whether you write Java.

## Prerequisites

- Camunda 8.8+ cluster reachable for testing (local c8run, SaaS, or Self-Managed — see **camunda-c8ctl**)
- Path A: none beyond the cluster — the JSON template is hand-authored, using `c8ctl element-template get <id>` to fetch the base OOTB template as a starting point
- Path B: Java 17+, Maven 3.8+ (or Gradle equivalent), and a JVM hosting option for the resulting connector JAR — see **camunda-development** for installing the JDK / Maven toolchain locally

## Cross-References

- **camunda-development**: Use first to decide whether building a connector is the right shape at all (vs. an OOTB connector or a job worker)
- **camunda-connectors**: Use for discovering and applying OOTB connectors — the catalog you're extending here
- **camunda-job-workers**: Use when the integration logic belongs in application code rather than a reusable connector (Path C in the decision matrix; workers are outbound-only)
- **camunda-bpmn**: Use for authoring the BPMN element the connector attaches to (service task for outbound, start/intermediate/boundary event or receive task for inbound)
- **camunda-feel**: Use for the FEEL expressions that pre-fill template properties and bind input/output mappings
- **camunda-process-test**: Use for end-to-end tests that drive a process through a custom connector

## When to write a custom connector

Walk **camunda-development** first. The short version of the matrix as it applies here:

- **OOTB connector covers it** → use the OOTB template. Stop.
- **Single API call over a common protocol** (REST, SOAP, GraphQL, Kafka, RabbitMQ, AWS SQS/SNS, …) and Java is acceptable → **Path A**: customise a JSON template on the existing protocol connector. No Java, no extra deployment.
- **Multi-step orchestration, proprietary protocol, non-HTTP I/O, or significant business logic** and you have a Java stack → **Path B**: custom Java connector via the Connectors SDK.
- **Non-Java SDK, or the logic belongs inside your existing application** → write a job worker. Workers cannot serve inbound triggers.

## Outbound vs. inbound

The two directions are not symmetric — an inbound connector is the only way an external event drives a process from outside the engine. Workers cannot replace inbound; the connector framework owns it.

- **Outbound**: process token reaches a service task, the connector calls the external system, the result flows back as variables. Path A and Path B both support outbound.
- **Inbound**: external system fires (HTTP request, message-queue delivery, scheduled poll). The connector correlates the event to a process — starting a new instance (start event) or continuing a waiting instance (intermediate catch, boundary event, message start, receive task). Path B only — Path A's protocol templates layer on outbound protocol connectors; the inbound webhook connector has its own OOTB template you customise directly.

Three inbound flavours, each owned by a different SDK shape:

- **Webhook** — the runtime exposes an HTTP endpoint per deployed process; external systems POST to it.
- **Subscription** — the runtime opens a connection to a message broker and consumes messages (Kafka, RabbitMQ, AWS SQS, …).
- **Polling** — the runtime periodically calls an external system on the process's behalf.

See `references/connector-sdk-inbound.md` for the lifecycle (`activate` / `deactivate`) and the `correlateWithResult` contract that funnels events into the engine.

## Pick a path

| Path | When to pick |
|---|---|
| **Path A — JSON-only template on a protocol connector** ([ref](references/protocol-connector-templates.md)) | Outbound integration that is a single call over a supported protocol (REST/SOAP/GraphQL/Kafka/RabbitMQ/AWS messaging). Domain-friendly UI in Modeler without writing Java. Ships as a single JSON file in the repo. |
| **Path B — Custom Java connector via the SDK** ([refs: [outbound](references/connector-sdk-outbound.md), [inbound](references/connector-sdk-inbound.md)]) | Anything Path A can't reach: multi-step orchestration, proprietary protocols, non-HTTP I/O, inbound triggers (webhook/subscription/polling), or logic that needs reuse across processes as a versioned artefact. Requires Java 17+ and a hosting decision. |

A JSON template is also the natural way to give a job worker a polished Modeler UI when Path A's protocol overlap isn't there and Path B is too heavy — hand-author the template using `references/element-template-json.md` and bind it to the worker's `zeebe:taskDefinition type`. That's still a worker, not a connector.

## Element templates — the shared surface

Both paths produce an element template JSON file. The schema is the same; what differs is how the file gets written:

- **Path A**: fetch the protocol connector's published template with `c8ctl element-template get <id>` as the starting point, then customise — hide infrastructure properties (URL, method, auth) with `"type": "Hidden"`, pre-fill them with FEEL, and expose only the domain-specific inputs.
- **Path B**: annotate the connector class with `@ElementTemplate` and let the Maven plugin generate the JSON during build (`references/element-template-generator.md`), or hand-author it.

### Specialising any OOTB template, not just protocol connectors

The "hide infrastructure, expose only domain inputs" pattern works for *any* OOTB template, not just the generic protocol ones. As long as the customised template still writes the input mappings the underlying job worker expects (the `zeebe:taskDefinition type` and `zeebe:input` shape are the data contract), the worker sees the same payload — only the Modeler UI differs.

Concrete examples in `camunda/connectors`:

- `connectors/openai/element-templates/openai-connector.json` — full OpenAI template; a specialised version could hide the system prompt or model picker and expose only domain inputs.
- `connectors/github/element-templates/github-connector.json` — specialised UI over the underlying job worker.
- `connectors/github/element-templates/github-webhook-connector-receive.json` — the *generic webhook inbound* connector exposed as a GitHub-specific webhook UI.
- `connectors/hugging-face/element-templates/hugging-face-connector.json` — Hugging Face-shaped UI over an underlying REST call.

Use `c8ctl element-template get <id>` to pull the base template, then hide / hardcode / rename properties while preserving the bindings the worker reads.

`references/element-template-json.md` is the schema reference for both — property types, binding types, FEEL/constraints/condition/generatedValue features, and the template variants for each BPMN attachment.

> **Field-ordering rule:** any property used in another property's FEEL `value` must appear earlier in the `properties` array. Out-of-order references silently evaluate to `null`. The same rule applies to Path A customisation and to hand-authored Path B templates.

## Shared facilities (Path A and Path B)

- **Secrets** — element templates and Java code resolve `{{secrets.NAME}}` placeholders at execution time. Never store secrets in the BPMN, the template defaults, or hard-coded strings. The standalone runtime reads from `SECRET_*` environment variables by default (8.9+).
- **Intrinsic functions** — template defaults and FEEL inputs can call intrinsic functions like `getText`, `base64`, and `createLink` to transform values before the connector receives them.
- **Camunda Documents** — connectors that produce or consume binary content (PDFs, images) handle Camunda Documents natively; workers must wire that plumbing themselves.
- **Result variable / result expression / error expression** — both paths surface the standard *Output mapping* group (`resultVariable`, `resultExpression`) and the *Error handling* group (`errorExpression`) via element template headers. See `references/element-template-json.md` for the binding shapes.

## Registration and hosting

Path B has a hosting decision that Path A doesn't — the JAR has to run somewhere. Four options, covered in `references/registration-and-hosting.md`:

- **SaaS managed runtime** — Camunda runs the standard connectors; custom JARs aren't supported on the managed runtime, so Path B on SaaS requires Hybrid mode (below).
- **Self-Managed standalone** — the `camunda/connectors:X.Y.Z` Docker image with custom connector JARs mounted into its app directory.
- **Self-Managed embedded** — Spring Boot application with the `spring-boot-starter-camunda-connectors` starter; your application hosts both connectors and your own business code.
- **Hybrid** — the standalone runtime runs in your environment but connects to a SaaS cluster. Required when SaaS is the engine but the connector needs to run inside your perimeter (private network access, on-prem dependencies, custom JARs).

**SPI vs. Spring Bean registration is independent of the hosting choice but constrains it.** SPI registration writes a `META-INF/services/...` file (default behaviour of the Maven plugin) and works in the standalone runtime. Spring Bean registration (`@Component` on the connector class) needs the embedded Spring Boot runtime and requires `<writeMetaInfFileGeneration>false</writeMetaInfFileGeneration>` on the Maven plugin to suppress the SPI file — both mechanisms registering the same class causes duplicate discovery.

## Hybrid templates

When Path B will run via the standalone runtime against a SaaS cluster (Hybrid hosting), the Maven plugin's `<generateHybridTemplates>true</generateHybridTemplates>` flag emits a parallel `*-hybrid.json` template per connector. The hybrid template flips the connector's task type to a job-worker style binding the SaaS engine can pick up and route to the standalone runtime. Without it, deploying the standard template to SaaS produces a runtime that can never receive jobs.

## Common pitfalls

- **Inventing template IDs or property names from training memory** — verify with `c8ctl element-template search "<keyword>"` and `c8ctl element-template get-properties <id>` against the live OOTB catalog before naming any ID, group, or property in code or docs.
- **Forgetting `<writeMetaInfFileGeneration>false</writeMetaInfFileGeneration>` when using Spring Bean registration** — the SPI file and `@Component` register the same class twice; the runtime instantiates two instances and the second silently shadows the first.
- **Field-ordering bugs** — a property whose FEEL `value` references a sibling declared *after* it evaluates to `null` at runtime. The Modeler doesn't flag this; the connector just gets an empty input.
- **Skipping Hybrid templates when running standalone against SaaS** — the standard template's task type isn't routable to a standalone runtime from SaaS. Set `<generateHybridTemplates>true</generateHybridTemplates>` and deploy the `-hybrid` variant.
- **Path A on a non-supported protocol** — Path A is only as broad as the protocol-connector catalog (REST, SOAP, GraphQL, Kafka, RabbitMQ, AWS messaging). A "custom binary protocol over TCP" template has nothing to layer on; go to Path B.
- **Treating the inbound webhook as a job worker** — inbound connectors are activated at process-definition deploy and deactivated when the deployment is removed; there is no per-instance job to poll for. The lifecycle is `activate(InboundConnectorContext)` / `deactivate()`, not handler-per-job.

## References

For detail, read from `references/`:

- [protocol-connector-templates.md](references/protocol-connector-templates.md) — Path A walkthrough: fetching the base template via c8ctl, hiding URL/method/auth, FEEL pre-fill, custom groups, a REST Countries worked example, and a brief link to template-generator tools
- [connector-sdk-outbound.md](references/connector-sdk-outbound.md) — `OutboundConnectorProvider` + `@Operation` (modern), `OutboundConnectorFunction` (legacy), `@Variable` / `@Header`, `ConnectorException`, Jakarta Validation
- [connector-sdk-inbound.md](references/connector-sdk-inbound.md) — `InboundConnectorExecutable`, three flavours, lifecycle, `correlateWithResult` / `CorrelationResult`
- [element-template-json.md](references/element-template-json.md) — schema reference: top-level fields, property types, binding types, property features, template variants per BPMN attachment
- [element-template-generator.md](references/element-template-generator.md) — Maven plugin configuration, `@ElementTemplate` annotation, `generateHybridTemplates`, `versionHistoryEnabled`, `writeMetaInfFileGeneration`
- [registration-and-hosting.md](references/registration-and-hosting.md) — SPI vs Spring Bean registration; SaaS / SM standalone / SM embedded / Hybrid hosting models
