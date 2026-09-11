# CPT setup

Prerequisites and one-time test-harness scaffold for `camunda-process-test-spring`.

## Prerequisites

- Java 21+
- Maven
- Docker runtime (required because CPT runs Zeebe in a Testcontainers container)

See **camunda-development** for installing these locally.

> Testcontainers pulls the matching Zeebe image automatically on first run (~500MB). Do not pre-pull `camunda/zeebe:latest` — the tag may not match the CPT version on the classpath.

## Readiness preflight (first run)

Run this quick check before scaffolding:

```bash
# Java runtime
java -version

# Maven (prefer wrapper when present)
./mvnw -version 2>/dev/null || mvn -version

# Docker runtime
docker info --format '{{.ServerVersion}}'
```

If Docker is not running, start your runtime (Docker Desktop, OrbStack, or Rancher Desktop) and re-run `docker info --format '{{.ServerVersion}}'`.

If Java or Maven resolves in an interactive shell but fails in non-interactive runs, check tool-manager shims (`asdf`/`mise`) and set the project toolchain explicitly (for example via `.tool-versions`) before running CPT.

## CPT dependency

Required entry in the project (or test harness) `pom.xml`:

```xml
<properties>
  <java.version>21</java.version>
  <camunda-process-test.version>8.9.0</camunda-process-test.version>
</properties>

<dependencies>
  <dependency>
    <groupId>io.camunda</groupId>
    <artifactId>camunda-process-test-spring</artifactId>
    <version>${camunda-process-test.version}</version>
    <scope>test</scope>
  </dependency>
  <dependency>
    <groupId>org.junit.jupiter</groupId>
    <artifactId>junit-jupiter</artifactId>
    <scope>test</scope>
  </dependency>
</dependencies>
```

The dependency and `@TestCaseSource` scaffold above are for the 8.9+ instruction-based workflow. For
an 8.8 project, pin a compatible 8.8.x release and use the Java fallback tests described in
[authoring.md](authoring.md#java-fallback).

Use 8.9+ for the instruction-based `.test.json` format (`CREATE_PROCESS_INSTANCE`, `COMPLETE_JOB`, …).
Java fallback-only suites can use a compatible 8.8.x release.

### Spring Boot 4.x pin (CPT 8.9.x only)

CPT 8.9.x ships against Spring Boot 4.x. If the project already imports `spring-boot-dependencies` (e.g. via a parent BOM), pin the version explicitly or omit the BOM:

```xml
<properties>
  <spring-boot.version>4.0.5</spring-boot.version>
</properties>
```

The mismatch surfaces as `NoClassDefFoundError` on `AdditionalPathsMapper` or `HealthEndpointConfiguration` when the Spring `ApplicationContext` starts — it looks like a code problem but is purely a dependency-resolution issue. CPT 8.8.x ran against Spring Boot 3.x; do not carry a 3.x pin forward when upgrading.

## Scaffold layout

```
src/
  main/resources/
    processes/                        # BPMN, DMN, .form lives here
  test/
    java/io/camunda/tests/
      ProcessTest.java                # JUnit runner
      TestApplication.java            # @SpringBootApplication for tests
    resources/
      scenarios/
        <processId>.test.json         # one file per process
```

### `ProcessTest.java`

```java
package io.camunda.tests;

import io.camunda.process.test.api.CamundaSpringProcessTest;
import io.camunda.process.test.api.TestDeployment;
import io.camunda.process.test.api.testCases.TestCase;
import io.camunda.process.test.api.testCases.TestCaseRunner;
import io.camunda.process.test.api.testCases.TestCaseSource;
import org.junit.jupiter.params.ParameterizedTest;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest
@CamundaSpringProcessTest
@TestDeployment(resources = {
    "processes/expense-approval.bpmn",
    "processes/approval-routing.dmn",
    "processes/manager-review.form"
})
public class ProcessTest {

    @Autowired
    private TestCaseRunner testCaseRunner;

    @ParameterizedTest(name = "{0}")
    @TestCaseSource(directory = "/scenarios")
    void shouldPass(final TestCase testCase, final String fileName) {
        testCaseRunner.run(testCase);
    }
}
```

Notes:

- `@TestDeployment` paths are **classpath-relative**. Do **not** prefix with `classpath:` — CPT adds it internally; the prefix causes `FileNotFoundException`.
- Every BPMN, DMN, and form file referenced by the process under test must be listed. A missing `.form` produces a `FORM_NOT_FOUND` incident at runtime.
- `@TestCaseSource(directory = "/scenarios")` is classpath-relative — leading slash, regardless of the Java package.

### `TestApplication.java`

```java
package io.camunda.tests;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class TestApplication {
    public static void main(String[] args) {
        SpringApplication.run(TestApplication.class, args);
    }
}
```

Required so `@SpringBootTest` has an application context to load.

## Node.js project layout

If the project root has `package.json` but no `pom.xml`, scaffold a sibling `test/` directory holding its own `pom.xml`. First resolve the BPMN / DMN / form resource directory declared by the Node.js project's build configuration. Set that resolved absolute path, or a path relative to `test/`, as `NODE_RESOURCE_DIR`; do not assume a `resources/` directory:

```xml
<testResources>
  <testResource>
    <directory>src/test/resources</directory>
  </testResource>
  <testResource>
    <directory>${env.NODE_RESOURCE_DIR}</directory>
    <targetPath>processes</targetPath>
    <includes>
      <include>**/*.bpmn</include>
      <include>**/*.dmn</include>
      <include>**/*.form</include>
    </includes>
  </testResource>
</testResources>
```

Run the commands below from the generated `test/` directory, which contains the `pom.xml`. Set
`NODE_RESOURCE_DIR` to the resolved directory before running Maven. Maven reads the environment
property independently of the shell:

```sh
export NODE_RESOURCE_DIR=/absolute/path/from-the-project-build
```

```powershell
$env:NODE_RESOURCE_DIR = "C:\path\from-the-project-build"
```

Then run every Maven invocation, including `test` and any retry, from `test/`:

```text
mvn test-compile
mvn test
```

Do not replace `NODE_RESOURCE_DIR` with `../resources` unless that is the directory the project build declares.

## Filename hygiene

Spaces in BPMN filenames work in Java strings and `<include>` tags but break shell scripts and glob patterns. Rename spaces to hyphens before adding to `@TestDeployment`.
