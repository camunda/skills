# Base sandbox image — Eclipse Temurin 25 (latest LTS), Node 24 (latest LTS).
#
# Used only by the c8ctl-bootstrap scenario, which exercises the
# camunda-c8ctl skill's install steps from a clean container. All other
# scenarios use with-c8ctl.Dockerfile (built FROM this image).
#
# Base image is Eclipse Temurin's official Ubuntu Noble (24.04) tag, so
# JAVA_HOME is set by the upstream image and we don't manage JDK
# packages ourselves. Node and Maven come in via multi-stage COPY from
# their official images — avoids fragile runtime curl|bash installs and
# TLS-interception issues on corporate networks / CI sandboxes.

FROM node:24-bookworm-slim AS node
FROM maven:3.9-eclipse-temurin-21 AS maven

FROM eclipse-temurin:25-jdk-noble

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
        jq \
        unzip \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Node 24 (binaries + global npm) from the official node:24 image.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js  /usr/local/bin/npm \
 && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js  /usr/local/bin/npx

# Maven from the official maven image (Java version of that image is
# irrelevant — we only need the maven binaries).
COPY --from=maven /usr/share/maven /opt/maven
RUN ln -s /opt/maven/bin/mvn /usr/local/bin/mvn

WORKDIR /workspace

# Non-root user for the agent's shell — c8ctl install also runs as this user.
RUN useradd --create-home --shell /bin/bash agent \
    && chown -R agent:agent /workspace
USER agent
