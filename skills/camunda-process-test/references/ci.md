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
      - name: Run CPT tests
        run: mvn test
      - name: Upload Surefire reports
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: surefire-reports
          path: "**/target/surefire-reports/*.xml"
```

## Optional split: process vs integration profile

- Keep `mvn test` on pull requests for fast feedback.
- Run integration profile jobs (`mvn verify -P integration-test`) on protected branches or scheduled runs.
- Store required cluster credentials in CI secrets, never in repo files.

## Common CI failure causes

- Docker unavailable on runner
- Missing test resources in `@TestDeployment`
- Branch-specific test data assumptions not mirrored in CI environment

When failures are recurrent, feed them back into [run-and-diagnose.md](run-and-diagnose.md) and harden the suite.
