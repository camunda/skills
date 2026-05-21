# Base sandbox image — no c8ctl.
#
# Used only by scenario 00-c8ctl-bootstrap, which exercises the
# camunda-c8ctl skill's install steps from a clean container.
# All other scenarios use with-c8ctl.Dockerfile (built FROM this image).

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
        jq \
        openjdk-21-jdk-headless \
        unzip \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Node 22 via NodeSource — matches the version pinned in CI.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Maven (separate from openjdk so users can swap JDK without losing it).
ARG MAVEN_VERSION=3.9.9
RUN curl -fsSL "https://dlcdn.apache.org/maven/maven-3/${MAVEN_VERSION}/binaries/apache-maven-${MAVEN_VERSION}-bin.tar.gz" \
        | tar -xz -C /opt \
    && ln -s "/opt/apache-maven-${MAVEN_VERSION}/bin/mvn" /usr/local/bin/mvn

ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64

WORKDIR /workspace

# Non-root user for the agent's shell — c8ctl install also runs as this user.
RUN useradd --create-home --shell /bin/bash agent \
    && chown -R agent:agent /workspace
USER agent
