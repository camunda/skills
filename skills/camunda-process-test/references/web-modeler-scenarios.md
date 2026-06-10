# Running Web Modeler scenario files in CI/CD

Web Modeler exports test scenarios alongside BPMN/DMN files as part of its Git sync. These files use the same CPT 8.9 instruction grammar as hand-authored `.test.json` scenarios but have a different file envelope. This reference covers how to detect them, how to choose a test cluster, and how to get them running in one pass.

## Detection fingerprint

A Web Modeler scenario file is present when:

- **Location**: alongside BPMN/DMN in the project's resources directory (`src/main/resources/`, not `src/test/`)
- **Filename**: `<Process Name> test scenarios.json` — spaces in the name, no `.test.json` suffix
- **Format**: `processId` and `testCases` at root; no `$schema` field; each test case carries a `metadata` block with `processInstanceId` and `coveredFlowNodes` (the execution trace from a prior Web Modeler run)

```json
{
  "processId": "my-process",
  "testCases": [
    {
      "name": "Happy path",
      "instructions": [ /* standard CPT 8.9 instructions */ ],
      "metadata": {
        "processInstanceId": 1234567890,
        "coveredFlowNodes": [
          { "flowNodeId": "StartEvent_1", "elementType": "bpmn:StartEvent" }
        ]
      }
    }
  ]
}
```

The `metadata` block is informational — it records which elements the scenario covered when it last ran in Web Modeler. CPT ignores it at runtime; it is not an assertion.

**Do not author new CPT unit-test scenarios for a process that already has a WM scenario file.** The two formats serve different purposes: WM scenarios validate real connector and cluster behavior; hand-authored CPT scenarios validate process routing in fast isolation. Run them in separate test classes.

## Step-by-step: get WM scenarios running

### Step 1 — Identify the cluster mode

Before writing any code, decide which cluster will execute the tests. This decision is **persisted in the repo** (see step 2) so that everyone on the team — and CI — uses the same target without relying on undocumented environment variables.

| Mode | When to use | `runtime-mode` value |
|------|-------------|----------------------|
| **Ephemeral** (CPT Testcontainers) | Full isolation; process + connectors under test; no shared infrastructure needed | `MANAGED` |
| **Remote — shared cluster** | Dedicated test/staging environment already exists; team runs against it | `REMOTE` |
| **Remote — same cluster as Web Modeler** | Developer wants to run scenarios against the exact cluster where they were authored | `REMOTE` |

Ask the user which mode to use if it is not already clear from context.

### Step 2 — Create `application-integration.yml`

Create `test/src/test/resources/application-integration.yml` (Spring profile `integration`). This file is committed to the repo and records the cluster choice. Credentials are always supplied via environment variables — never committed.

```yaml
# Cluster mode for Web Modeler integration tests.
# Change runtime-mode to switch modes; do not commit credentials.
#
# cluster-mode: ephemeral          → runtime-mode: MANAGED
# cluster-mode: remote-shared      → runtime-mode: REMOTE
# cluster-mode: remote-wm-cluster  → runtime-mode: REMOTE
camunda:
  process-test:
    runtime-mode: MANAGED   # change to REMOTE for shared/WM cluster
  client:
    zeebe:
      grpc-address: ${ZEEBE_GRPC_ADDRESS:}
    auth:
      client-id: ${CAMUNDA_CLIENT_ID:}
      client-secret: ${CAMUNDA_CLIENT_SECRET:}
      issuer: ${CAMUNDA_OAUTH_URL:}
```

For ephemeral mode the `client` block is unused; it can be left as-is for future flexibility.

### Step 3 — Update `pom.xml`

Two additions are needed: a `<testResource>` block to put the WM scenario file on the classpath, and the `maven-failsafe-plugin` so the integration test class runs on `mvn verify` but not `mvn test`.

```xml
<testResources>
  <!-- existing testResource entries … -->
  <testResource>
    <directory>../src/main/resources</directory>   <!-- adjust to project layout -->
    <targetPath>integration-scenarios</targetPath>
    <includes>
      <include>*test scenarios.json</include>       <!-- glob picks up all WM files -->
    </includes>
  </testResource>
</testResources>

<plugins>
  <!-- existing plugins … -->
  <plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-failsafe-plugin</artifactId>
    <version>3.2.5</version>
    <executions>
      <execution>
        <goals>
          <goal>integration-test</goal>
          <goal>verify</goal>
        </goals>
      </execution>
    </executions>
  </plugin>
</plugins>
```

### Step 4 — Write the integration test class

Name the class `<Process>IntegrationIT.java` (the `IT` suffix is what makes failsafe pick it up). Choose the template that matches the cluster mode from step 1.

#### Ephemeral cluster (Testcontainers + Connectors runtime)

Use this when `runtime-mode: MANAGED`. Include `@TestDeployment` so CPT deploys the BPMN/DMN into the embedded engine.

```java
package io.camunda.tests;

import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaSpringProcessTest;
import io.camunda.process.test.api.TestDeployment;
import io.camunda.process.test.api.testCases.TestCase;
import io.camunda.process.test.api.testCases.TestCaseRunner;
import io.camunda.process.test.api.testCases.TestCaseSource;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.params.ParameterizedTest;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import java.time.Duration;

@SpringBootTest(properties = {
    "spring.profiles.active=integration",
    "io.camunda.process.test.connectors-enabled=true"
})
@CamundaSpringProcessTest
@TestDeployment(resources = {"MyProcess.bpmn", "my-decision.dmn"})
public class MyProcessIntegrationIT {

    @Autowired
    private TestCaseRunner testCaseRunner;

    @BeforeAll
    static void configureTimeout() {
        // Real HTTP calls are slower than embedded engine — bump the assertion timeout.
        CamundaAssert.setAssertionTimeout(Duration.ofSeconds(60));
    }

    @ParameterizedTest
    @TestCaseSource(directory = "/integration-scenarios")
    void shouldRunWebModelerScenario(final TestCase testCase, final String fileName) {
        testCaseRunner.run(testCase);
    }
}
```

Notes:
- `connectors-enabled=true` starts the `camunda/connectors-bundle` container so the HTTP JSON connector and other outbound connectors execute for real.
- The connectors bundle image tag is derived from `camunda.version` in `pom.xml`. Use a GA stable release — RC and SNAPSHOT tags are not published for this image. Set `io.camunda.process.test.connectors-docker-image-version` to override if needed.
- 60 seconds is a safe default timeout for a single external HTTP call. Increase it if the process has multiple sequential connector calls.

#### Remote cluster (shared or WM cluster)

Use this when `runtime-mode: REMOTE`. Drop `@TestDeployment` — the BPMN/DMN is already deployed on the target cluster, and the scenario runs against the live deployment.

```java
package io.camunda.tests;

import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaSpringProcessTest;
import io.camunda.process.test.api.testCases.TestCase;
import io.camunda.process.test.api.testCases.TestCaseRunner;
import io.camunda.process.test.api.testCases.TestCaseSource;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.params.ParameterizedTest;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import java.time.Duration;

@SpringBootTest(properties = {
    "spring.profiles.active=integration"
})
@CamundaSpringProcessTest
// No @TestDeployment — process is already deployed on the target cluster.
public class MyProcessIntegrationIT {

    @Autowired
    private TestCaseRunner testCaseRunner;

    @BeforeAll
    static void configureTimeout() {
        // Remote clusters include network round-trips — use a longer timeout.
        CamundaAssert.setAssertionTimeout(Duration.ofSeconds(120));
    }

    @ParameterizedTest
    @TestCaseSource(directory = "/integration-scenarios")
    void shouldRunWebModelerScenario(final TestCase testCase, final String fileName) {
        testCaseRunner.run(testCase);
    }
}
```

Required environment variables for remote mode (supply in CI secrets or local `.env`):

| Variable | Description |
|----------|-------------|
| `ZEEBE_GRPC_ADDRESS` | gRPC endpoint, e.g. `https://abc.zeebe.camunda.io:443` |
| `CAMUNDA_CLIENT_ID` | OAuth client ID |
| `CAMUNDA_CLIENT_SECRET` | OAuth client secret |
| `CAMUNDA_OAUTH_URL` | Token issuer URL |

### Step 5 — Run

```bash
# Integration tests only (faster feedback loop):
mvn failsafe:integration-test failsafe:verify

# Full suite (unit + integration):
mvn verify
```

`mvn test` alone runs surefire (`*Test.java`) only — it does not run the integration tests.

## Troubleshooting WM scenarios

| Symptom | Cause | Fix |
|---------|-------|-----|
| Element ID in `metadata.coveredFlowNodes` not found in BPMN | BPMN was modified after the scenario was exported from Web Modeler | Re-export the scenario from Web Modeler, or update element IDs manually |
| `ASSERT_PROCESS_INSTANCE IS_COMPLETED` fails but process is running | Assertion timeout too short for real connector calls | Increase `CamundaAssert.setAssertionTimeout` |
| `ContainerFetchException` for `camunda/connectors-bundle:<version>` | RC or SNAPSHOT tag not published on Docker Hub | Pin `camunda.version` to a GA stable release; or set `io.camunda.process.test.connectors-docker-image-version` explicitly |
| Remote mode: `NullPointerException` on `ZEEBE_GRPC_ADDRESS` | Environment variable not set | Set the required env vars (see table above) |
| Remote mode: process not found | BPMN not deployed to target cluster, or wrong cluster credentials | Deploy via Web Modeler or `c8ctl deploy`; verify `ZEEBE_GRPC_ADDRESS` points to the right cluster |
| WM scenario file not discovered by `@TestCaseSource` | File not on classpath, or `<targetPath>` missing from pom.xml | Confirm the `<testResource>` block in pom.xml uses `<targetPath>integration-scenarios</targetPath>` and the glob matches the filename |

## What WM scenarios do and do not assert

Web Modeler generates scenarios that assert `ASSERT_PROCESS_INSTANCE IS_COMPLETED`. They do not assert specific end events or intermediate element reachability. This is intentional — WM prioritizes end-to-end completion over path specificity.

The `metadata.coveredFlowNodes` array records what the scenario covered in its last WM run. It is informational only; CPT does not read or enforce it. If you want path-specific assertions, add `ASSERT_ELEMENT_INSTANCES` instructions to the scenario file, or write a separate hand-authored CPT unit-test scenario in `src/test/resources/scenarios/`.
