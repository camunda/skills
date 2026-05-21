# Base sandbox image — Eclipse Temurin 25 (latest LTS), Node 24 (latest LTS).
#
# Used only by the c8ctl-bootstrap scenario, which exercises the
# camunda-c8ctl skill's install steps from a clean container. All other
# scenarios use with-c8ctl.Dockerfile (built FROM this image).
#
# Base image is Eclipse Temurin's official Ubuntu Noble (24.04) tag, so
# JAVA_HOME is set by the upstream image and we don't manage JDK
# packages ourselves.

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

# Node 24 (latest LTS) via NodeSource.
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Maven (the Temurin image ships JDK only).
ARG MAVEN_VERSION=3.9.9
RUN curl -fsSL "https://dlcdn.apache.org/maven/maven-3/${MAVEN_VERSION}/binaries/apache-maven-${MAVEN_VERSION}-bin.tar.gz" \
        | tar -xz -C /opt \
    && ln -s "/opt/apache-maven-${MAVEN_VERSION}/bin/mvn" /usr/local/bin/mvn

WORKDIR /workspace

# Non-root user for the agent's shell — c8ctl install also runs as this user.
RUN useradd --create-home --shell /bin/bash agent \
    && chown -R agent:agent /workspace
USER agent
