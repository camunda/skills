---
name: camunda-development
description: |
  Use this skill to choose the right Camunda 8 development surface (OOTB connector, custom connector template, custom Java connector, or job worker) before writing any integration code.

  Use for: orienting between out-of-the-box connectors, JSON-only templates on protocol connectors, custom Java connectors via the Connectors SDK, and job workers (Java / Spring / TypeScript); understanding the trade-offs (language reach, secrets handling, intrinsic functions, Camunda Documents, inbound support, low-level Zeebe APIs); deciding whether a piece of integration logic belongs in a reusable connector or in your application as a worker.

  Do not use for: actually building a worker (use camunda-job-workers), building a custom connector (use camunda-connectors-development), or configuring an already-published OOTB connector (use camunda-connectors).

  **Utility skill** — decision matrix only. Read this first, then jump into the focused build skill it points you to.
---

# Camunda Development

Decide between out-of-the-box connectors, custom connector templates, custom Java connectors via the Connectors SDK, and job workers before writing any integration code for Camunda 8.8+. This skill is a thin orientation layer — every path it identifies has its own focused build skill.

## Cross-References

- **camunda-connectors**: Use for browsing and applying an existing OOTB connector template
- **camunda-connectors-development**: Use for building a custom connector (JSON-only template on a protocol connector, or a Java connector via the Connectors SDK; covers both outbound and inbound)
- **camunda-job-workers**: Use for implementing a job worker in Java, Spring Boot, or TypeScript
- **camunda-bpmn**: Use for the BPMN element (service task, message event, …) that hosts the connector or worker job
- **camunda-process-test**: Use for testing the resulting process

## Decision matrix

Walk the questions top-down. Stop at the first one whose answer is yes.

1. **Does an out-of-the-box (OOTB) connector cover the integration?**
   Search the local catalog with `c8ctl element-template search "<keyword>"` (see **camunda-connectors**). If a template matches the target system, use it as-is. **Stop.**

2. **Is the integration a single API call over a common protocol** (REST, SOAP, GraphQL, Kafka, RabbitMQ, AWS SQS/SNS, …), **and do you want a reusable, modeller-friendly building block?**
   → **Path A — JSON-only template on a protocol connector.** No Java, no separate runtime. Customise the protocol connector's published template: pre-fill the URL with FEEL, hide method / base URL / auth, expose only the domain-specific properties. See **camunda-connectors-development**.

3. **Is the logic more than a single API call** (proprietary protocol, multi-step orchestration with state, non-HTTP I/O, custom inbound trigger) **and is the team on Java?**
   → **Path B — Custom Java connector via the Connectors SDK.** Annotation-driven, auto-generated element template, built-in secrets / intrinsic functions / Camunda Documents. Works for outbound *and* inbound. See **camunda-connectors-development**.

4. **Otherwise — non-Java stack, or the logic already lives in your application, or you need low-level Zeebe APIs (job streaming, custom activation).**
   → **Path C — Job worker.** Implement the handler in your app using one of the official SDKs (Java, Spring Boot, TypeScript covered here; other SDKs follow the same pattern). If you also want a modeller UI for the worker, hand-author an element template JSON. See **camunda-job-workers**.

## Comparison: job worker vs. connector (SDK)

| Aspect | Job worker | Connector (SDK) |
|---|---|---|
| Language | Any official SDK (Java, Spring Boot, TypeScript, …) | Java only |
| Delivery | Tied to the application that runs it | Library, deployable into any Connector Runtime |
| Reusability across environments | Hard — re-wire per project | Easy — same JAR, drop into any runtime |
| Focus | Full Zeebe client (activate, complete, fail, retries) | Pure business logic; runtime handles Zeebe wiring |
| Secrets | Roll your own (env vars, secret manager) | Built-in `{{secrets.NAME}}` resolution |
| Low-level Zeebe APIs | Yes | No |
| Modeller UI for the task | Optional — hand-authored element template JSON | Standardised — generated from `@ElementTemplate` |
| Element template auto-generation | None — author JSON by hand | Maven plugin generates it from annotations |
| Intrinsic functions (`getText`, `base64`, …) | No | Yes |
| Camunda Documents handling | Manual | Built-in |
| Inbound triggers | No (outbound jobs only) | Yes (Webhook / Subscription / Polling) |

The table is the why behind the matrix: connectors trade language reach for reusability and a richer surface; workers trade that surface for language choice and direct Zeebe access.

## Worked example — applying the matrix

> *"Notify Slack when an order is approved. The team is on Node.js."*

1. **OOTB connector?** `c8ctl element-template search "slack"` returns `io.camunda.connectors.Slack.v1`. The bot-message operation covers a one-off notification with no custom UI requirement. → **Use it.** Stop here.

> *"Submit a job to our internal HTTP pricing API. The team is on Java. We want a reusable connector with only `customerId`, `productSku`, and `quantity` exposed in Modeler."*

1. OOTB? No matching template.
2. **Single API call over a protocol, Java team, reusable building block?** Yes — REST. → **Path A.** Take the published HTTP REST connector template, pre-fill the URL with a FEEL expression that builds the request URL from `customerId`, hide the method / base URL / auth fields, expose only the three domain properties. JSON-only; nothing to deploy as a runtime. See **camunda-connectors-development**.

> *"Periodically pull invoices from an SFTP server and start a process per file. Team is on Java."*

1. OOTB? No SFTP-pull start-event connector that fits.
2. Single API call over a common protocol? No — SFTP, custom poll cadence, inbound trigger.
3. **Complex integration, Java team?** Yes. → **Path B**, with the **Polling** inbound flavour. Build it with the Connectors SDK. See **camunda-connectors-development**.

> *"Score a customer record using the team's existing Node.js scoring service."*

1. OOTB? No.
2. Single API call over a protocol, Java team? Team is on Node.js — fails on language. (You *could* still wrap a Java REST template around the scoring service, but the logic already lives in the Node.js app and there is no Java team to maintain a connector.)
3. Java team? No. → **Path C**, job worker. Wire the existing Node.js service to handle a `score-customer` job via the TypeScript SDK. See **camunda-job-workers**.

## Mixing in one project

Workers and connectors are a **per-task** choice, not a per-project one. A single Spring Boot application can host job workers (via the Camunda Spring Boot Starter) and an embedded connector runtime (via `spring-boot-starter-camunda-connectors`) side by side — the Connectors SDK itself builds on the Spring Boot Starter. Pick the right shape for each integration; you do not need to commit the whole project to one path.

## Inbound is a connector concern

Inbound triggers — events flowing *into* a process from an external system — are implemented only via the Connectors SDK. There is no job-worker path for inbound: job workers exclusively handle outbound jobs the engine has already activated.

The SDK supports three inbound flavours, and the choice drives which BPMN element types your element template applies to (message-start event, intermediate catch event, boundary event, …):

- **Webhook** — the runtime hosts an HTTP listener; the external system calls in.
- **Subscription** — the runtime opens a long-lived connection to a message broker (Kafka, RabbitMQ, AMQP, …) and consumes events.
- **Polling** — the runtime polls an external endpoint on a schedule.

If the integration is inbound, paths A and B in the decision matrix are the only options; path C does not apply. See **camunda-connectors-development**.
