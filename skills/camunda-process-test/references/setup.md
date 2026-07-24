# CPT setup

Prerequisites and one-time test-harness scaffold for `camunda-process-test-spring`.

## Prerequisites

- Java 21+
- Maven
- Docker runtime (required because CPT runs Zeebe in a Testcontainers container)

See **camunda-development** for installing these locally.

> Testcontainers pulls the matching Zeebe image automatically on first run (~500MB). Do not pre-pull `camunda/zeebe:latest` — the tag may not match the CPT version on the classpath.

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

Use 8.9+ — the instruction-based `.test.json` format (`CREATE_PROCESS_INSTANCE`, `COMPLETE_JOB`, …) requires it.

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

If the project root has `package.json` but no `pom.xml`, scaffold a sibling `test/` directory holding its own `pom.xml`. The test harness reads BPMN / DMN / form files from the parent project via a `<testResource>` mapping:

```xml
<testResources>
  <testResource>
    <directory>src/test/resources</directory>
    <excludes><exclude>scenarios/**</exclude></excludes>
  </testResource>
  <testResource>
    <directory>../resources</directory>
    <targetPath>processes</targetPath>
    <includes>
      <include>**/*.bpmn</include>
      <include>**/*.dmn</include>
      <include>**/*.form</include>
    </includes>
  </testResource>
</testResources>
```

Confirm the scaffold by running `mvn test-compile` from `test/`.

## Filename hygiene

Spaces in BPMN filenames work in Java strings and `<include>` tags but break shell scripts and glob patterns. Rename spaces to hyphens before adding to `@TestDeployment`.
