# CPT CI setup patterns

Run CPT suites in CI as a quality gate and publish test artifacts.

## Baseline requirements

- Java toolchain compatible with project build
- Maven cache enabled where possible
- Docker available to the test job (CPT/Testcontainers requirement)
- JUnit XML artifact upload from `**/target/surefire-reports/*.xml` (glob covers multi-module layouts)

## GitHub Actions baseline

```yaml
name: process-tests

on:
  pull_request:
  push:
    branches: [main]

jobs:
  cpt:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '21'
          cache: maven
      - name: Run CPT tests (standard Java layout)
        run: mvn test
      - name: Upload Surefire reports
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: surefire-reports
          path: "**/target/surefire-reports/*.xml"
```

For a Node.js layout, replace the test step with a step that runs from the generated `test/` directory
and sets `NODE_RESOURCE_DIR` to the resource directory declared by the project build:

```yaml
      - name: Run CPT tests (Node.js harness)
        working-directory: test
        env:
          NODE_RESOURCE_DIR: ${{ github.workspace }}/<resource-path-declared-by-project-build>
        run: mvn test
```

## Optional split: process vs integration profile

- Keep the Maven test command on pull requests for fast feedback. For Node.js layouts, run it from
  `test/` with the same `NODE_RESOURCE_DIR` environment setting.
- Run the integration profile (`mvn verify -P integration-test`) on protected branches or scheduled runs,
  using the same working directory and environment setting for Node.js layouts.
- Store required cluster credentials in CI secrets, never in repo files.

## Common CI failure causes

- Docker unavailable on runner
- Missing test resources in `@TestDeployment`
- Branch-specific test data assumptions not mirrored in CI environment

When failures are recurrent, feed them back into [run-and-diagnose.md](run-and-diagnose.md) and harden the suite.
