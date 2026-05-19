# Local dev environment prerequisites

What tools each Camunda 8 workflow expects on the host, how to verify they're working, and the cross-cutting gotchas. This file deliberately does **not** prescribe an installation path — package managers and version managers are OS- and stack-specific, and the right choice depends on what else lives on the machine.

## Prerequisite matrix

| Workflow | Tools | Where the current minimum lives |
|----------|-------|---------------------------------|
| Use c8ctl (BPMN lint, deploy, FEEL eval, connector templates, …) | Node.js | **camunda-c8ctl** |
| Run a local cluster via `c8ctl cluster start` (c8run) | JRE | **camunda-c8ctl** |
| Implement Java / Spring Boot job workers | JDK, Maven (or Gradle) | **camunda-job-workers** |
| Build a custom Java connector (Connectors SDK) | JDK, Maven (or Gradle) | **camunda-connectors-development** |
| Implement TypeScript job workers | Node.js | **camunda-job-workers** |
| Run Camunda Process Test (CPT) | JDK, Maven, Docker runtime | **camunda-process-test** |

A single machine usually needs the union of the rows for the workflows in scope — Java versions stack (install the highest required JDK and the lower-bound rows are satisfied), Node.js does not.

## Verification one-liners

Run these from any shell — they don't depend on the install path:

```bash
node -v                                  # c8ctl, TypeScript SDK
java -version                            # workers, connectors, CPT, c8run
mvn -v                                   # workers, connectors, CPT
docker info --format '{{.ServerVersion}}'  # CPT (must print a version, not error)
```

The Docker check is more than `docker info` — see "Docker daemon vs. CLI" below.

## How people install these

Common paths, named so they're recognisable, not prescribed:

- **Version managers** keep multiple JDKs / Node versions side by side and pin per-project via a checked-in file. [asdf](https://asdf-vm.com), [mise](https://mise.jdx.dev), and [SDKMAN!](https://sdkman.io) cover JDK + Maven; [nvm](https://github.com/nvm-sh/nvm) and [fnm](https://github.com/Schniz/fnm) cover Node.js. SDKMAN! is JVM-focused; the others span more runtimes.
- **OS package managers** — Homebrew on macOS, `apt`/`dnf` on Linux, `choco`/`winget` on Windows. Fine for a one-off install; less convenient when the project needs a different version than the system.
- **Vendor installers** — Temurin / Oracle JDK installers, Node.js installer from nodejs.org, Docker Desktop / OrbStack / Rancher Desktop for the container runtime.

Pick whichever fits the existing setup. The skill's job is to know what's needed and how to verify it, not to dictate how it got there.

When a verification one-liner reports a missing or wrong-version tool, **surface the gap to the user and discuss the install path** — don't install it autonomously. The right choice depends on what else lives on the machine (existing version manager, shared toolchain, project-pinned versions), which only the user can answer.

## Cross-cutting gotchas

### `JAVA_HOME` vs. `PATH`

Maven, Gradle, and many JVM tools resolve the JDK via `JAVA_HOME`, not the `java` binary on `PATH`. If `java -version` reports JDK 21 but `mvn -v` reports JDK 17, the two are pointing at different installs — fix `JAVA_HOME` (or the version-manager shim) before debugging build errors. Version managers handle this automatically when activated; ad-hoc installs often don't.

### Docker daemon vs. CLI

`docker` is a client binary. `docker info` exits 0 as long as the client is installed — even when the daemon is stopped — because it still prints the Client section. The reliable daemon check is:

```bash
docker info --format '{{.ServerVersion}}'
```

This only prints a version when the daemon is reachable. CPT, which uses Testcontainers, needs the daemon, not just the CLI — see **camunda-process-test**.

### Testcontainers expects the daemon already running

Testcontainers connects to whichever runtime is currently up (Docker Desktop, OrbStack, Rancher Desktop, Colima, …) — it doesn't start one for you. Start the runtime first, then run the test.

### Don't pre-pull `camunda/zeebe:latest`

Testcontainers fetches the Zeebe image matching the CPT version on the test classpath on first run. Pre-pulling `camunda/zeebe:latest` wastes bandwidth and ships a tag that may not match the CPT version — see **camunda-process-test**.
