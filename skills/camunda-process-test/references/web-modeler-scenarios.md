# Running Web Modeler scenario files

Web Modeler exports test scenarios alongside BPMN/DMN files as part of its Git sync. These files use the same CPT 8.9 instruction grammar as hand-authored `.test.json` scenarios but have a different file envelope. This reference covers how to detect them, how to choose a test cluster, and how to get them running in one pass.

## Detection fingerprint

A Web Modeler scenario file is present when:

- **Location**: alongside BPMN/DMN in the project's resources directory — `src/main/resources/` in a standard Maven module, or `../resources/` relative to the sibling `test/` harness ([setup.md](setup.md#nodejs-project-layout)). Never under `src/test/`
- **Filename**: `<Process Name> test scenarios.json` — spaces in the name, no `.test.json` suffix
- **Format**: `processId` and `testCases` at root; no `$schema` field; each test case carries a `metadata` block with `processInstanceId` and `coveredFlowNodes` (the execution trace from a prior Web Modeler run)

```jsonc
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
| **Ephemeral** (CPT Testcontainers) | Full isolation; process + connectors under test; no shared infrastructure needed | `managed` |
| **Remote — shared cluster** | Dedicated test/staging environment already exists; team runs against it | `remote` |
| **Remote — same cluster as Web Modeler** | Developer wants to run scenarios against the exact cluster where they were authored | `remote` |

Ask the user which mode to use if it is not already clear from context.

### Step 2 — Create `application-integration.yml`

Create `application-integration.yml` (Spring profile `integration`) in the test resources of the module that holds the tests — `src/test/resources/` in a standard Maven project, or `test/src/test/resources/` when the harness is the sibling `test/` module described in [setup.md](setup.md#nodejs-project-layout). This file is committed to the repo and records the cluster choice. Credentials are always supplied via environment variables — never committed.

```yaml
# Cluster mode for Web Modeler integration tests.
# Change runtime-mode to switch modes; do not commit credentials.
#
# cluster-mode: ephemeral          → runtime-mode: managed
# cluster-mode: remote-shared      → runtime-mode: remote
# cluster-mode: remote-wm-cluster  → runtime-mode: remote
camunda:
  process-test:
    runtime-mode: managed   # change to remote for shared/WM cluster
  client:
    # Addresses sit directly under camunda.client, per the Spring Boot Starter
    # properties reference. The camunda.client.zeebe.* nesting is the older
    # Spring Zeebe SDK shape, kept only for backwards compatibility.
    grpc-address: ${CAMUNDA_GRPC_ADDRESS:}
    rest-address: ${CAMUNDA_REST_ADDRESS:}
    auth:
      client-id: ${CAMUNDA_CLIENT_ID:}
      client-secret: ${CAMUNDA_CLIENT_SECRET:}
      issuer-url: ${CAMUNDA_OAUTH_URL:}
```

`rest-address` is not optional for remote mode: the client prefers REST over gRPC by default ([`camunda.client.prefer-rest-over-grpc`](https://docs.camunda.io/docs/apis-tools/camunda-spring-boot-starter/properties-reference/) defaults to `true`), so a remote runtime configured with only a gRPC address has no address for the calls it actually makes.

For ephemeral mode the `client` block is unused; it can be left as-is for future flexibility.

### Step 3 — Update `pom.xml`

Two additions are needed: a `<testResource>` block to put the WM scenario file on the classpath, and the `maven-failsafe-plugin` so the integration test class runs on `mvn verify` but not `mvn test`.

```xml
<!-- Both blocks belong inside <build>. Maven silently ignores testResources
     and plugins declared anywhere else, so the scenarios never reach the
     test classpath and failsafe never runs. -->
<build>
  <testResources>
    <!-- existing testResource entries … -->
    <testResource>
      <!-- Where WM exported the file. Keep exactly one of these two lines:
           the first for a standard Maven module, the second for the sibling
           test/ harness (setup.md#nodejs-project-layout). -->
      <directory>src/main/resources</directory>
      <!-- <directory>../resources</directory> -->
      <targetPath>integration-scenarios</targetPath>
      <includes>
        <!-- ** so scenarios exported into a subfolder are copied too; the space
             before "test" is literal, matching the WM pattern not .test.json -->
        <include>**/* test scenarios.json</include>
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
</build>
```

### Step 4 — Write the integration test class

Name the class `<Process>IntegrationIT.java` (the `IT` suffix is what makes failsafe pick it up). Choose the template that matches the cluster mode from step 1.

#### Ephemeral cluster (Testcontainers + Connectors runtime)

Use this when `runtime-mode: managed`. Include `@TestDeployment` so CPT deploys the BPMN/DMN into the embedded engine.

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
    "camunda.process-test.connectors-enabled=true"
})
@CamundaSpringProcessTest
@TestDeployment(resources = {"processes/MyProcess.bpmn", "processes/my-decision.dmn"})
public class MyProcessIntegrationIT {

    @Autowired
    private TestCaseRunner testCaseRunner;

    @BeforeAll
    static void configureTimeout() {
        // Real HTTP calls are slower than embedded engine — bump the assertion timeout.
        CamundaAssert.setAssertionTimeout(Duration.ofSeconds(60));
    }

    @ParameterizedTest(name = "{0}")
    @TestCaseSource(directory = "/integration-scenarios")
    void shouldRunWebModelerScenario(final TestCase testCase, final String fileName) {
        testCaseRunner.run(testCase);
    }
}
```

Notes:
- `camunda.process-test.connectors-enabled=true` starts the `camunda/connectors-bundle` container so the HTTP JSON connector and other outbound connectors execute for real.
- The connectors bundle image tag defaults to the CPT dependency version on the classpath — whichever property the project pins it with (`camunda-process-test.version` in the setup.md snippet, `camunda.version` in the upstream docs). That version must be one the connectors image was published for; see [Connectors bundle image version](#connectors-bundle-image-version) below.
- 60 seconds is a safe default timeout for a single external HTTP call. Increase it if the process has multiple sequential connector calls.

#### Remote cluster (shared or WM cluster)

Use this when `runtime-mode: remote`. Drop `@TestDeployment` — the BPMN/DMN is already deployed on the target cluster, and the scenario runs against the live deployment.

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

    @ParameterizedTest(name = "{0}")
    @TestCaseSource(directory = "/integration-scenarios")
    void shouldRunWebModelerScenario(final TestCase testCase, final String fileName) {
        testCaseRunner.run(testCase);
    }
}
```

Required environment variables for remote mode (supply in CI secrets or local `.env`):

| Variable | Description |
|----------|-------------|
| `CAMUNDA_GRPC_ADDRESS` | gRPC endpoint, e.g. `https://abc.zeebe.camunda.io:443` |
| `CAMUNDA_REST_ADDRESS` | REST endpoint, e.g. `https://bru-2.zeebe.camunda.io:443/<cluster-id>` |
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

## Connectors bundle image version

If `camunda.process-test.connectors-enabled=true` is set, CPT pulls `camunda/connectors-bundle:<version>`, where `<version>` defaults to the CPT dependency version on the classpath — the one pinned by `camunda-process-test.version` in the `pom.xml` snippet in [setup.md](setup.md#cpt-dependency) (the upstream docs pin the same dependency with a `camunda.version` property). Prefer a GA release for it.

The reason is tag coverage, not tag absence: `camunda/connectors-bundle` does publish `-rc*`, `-alpha*`, and `SNAPSHOT` tags, but not for every version `camunda/camunda` has. Pre-release tags in particular are published per image and pruned independently, so a version that resolves for `camunda/camunda` can have no connectors-bundle counterpart (`8.6.12-rc1` was one such tag). When the derived tag doesn't exist, the test fails at startup with `ContainerFetchException` for `camunda/connectors-bundle:<version>`.

Rather than trusting a list of known-missing tags, check the one you intend to use — pre-release tag coverage changes on both images:

```bash
TAG=8.9.0   # the version you intend to pin
curl -sf "https://hub.docker.com/v2/repositories/camunda/connectors-bundle/tags/${TAG}" >/dev/null \
  && echo "exists" || echo "missing — pin a GA version or override the tag"
```

Set `TAG` before running it. With `TAG` empty the URL collapses to the tag-listing endpoint, which answers `200` for every image and reports "exists" regardless.

So: pin a GA version, or confirm the exact tag exists first. To use a tag that differs from the CPT dependency version, override it:

```
camunda.process-test.connectors-docker-image-version=8.9.0
```

## Troubleshooting WM scenarios

| Symptom | Cause | Fix |
|---------|-------|-----|
| An instruction targets an element ID that no longer exists in the BPMN | BPMN was modified after the scenario was exported from Web Modeler | Re-export the scenario from Web Modeler, or update the element IDs in the scenario file. Stale IDs under `metadata` are not the cause — CPT does not read `metadata` |
| `ASSERT_PROCESS_INSTANCE IS_COMPLETED` fails but process is running | Assertion timeout too short for real connector calls | Increase `CamundaAssert.setAssertionTimeout` |
| `ContainerFetchException` for `camunda/connectors-bundle:<version>` | No connectors-bundle tag for the version CPT derived from the CPT dependency version — common with non-GA versions | Pin that version (`camunda-process-test.version`, see [below](#connectors-bundle-image-version)) to a GA release; or set `camunda.process-test.connectors-docker-image-version` explicitly |
| Remote mode: startup fails resolving the cluster address | A required environment variable is unset, so the client has no address to connect to | Set the required env vars (see table above) |
| Remote mode: process not found | BPMN not deployed to target cluster, or wrong cluster credentials | Deploy via Web Modeler or `c8ctl deploy`; verify `CAMUNDA_GRPC_ADDRESS` / `CAMUNDA_REST_ADDRESS` point at the right cluster |
| WM scenario file not discovered by `@TestCaseSource` | File not on classpath, or `<targetPath>` missing from pom.xml | Confirm the `<testResource>` block in pom.xml uses `<targetPath>integration-scenarios</targetPath>` and the glob matches the filename |

## What WM scenarios do and do not assert

Web Modeler generates scenarios that assert `ASSERT_PROCESS_INSTANCE IS_COMPLETED`. They do not assert specific end events or intermediate element reachability. This is intentional — WM prioritizes end-to-end completion over path specificity.

The `metadata.coveredFlowNodes` array records what the scenario covered in its last WM run. It is informational only; CPT does not read or enforce it. If you want path-specific assertions, add `ASSERT_ELEMENT_INSTANCES` instructions to the scenario file, or write a separate hand-authored CPT unit-test scenario in `src/test/resources/scenarios/`.
