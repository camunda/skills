# Verifier sandbox image — runs agent-produced artifacts under `mvn test`.
#
# Maven local cache is pre-warmed at image build time against every CPT
# verifier pom in the repo. At runtime, `mvn test` resolves from the
# baked /.m2 — no Maven Central hits, no transient TLS flakes, and CPT
# can run in airgapped / network-denied sandboxes.
#
# Built with build context = evals/ (see the eval-images Make target),
# so the RUN below can bind-mount src/scenarios in place without
# COPYing it into a layer.

FROM camunda-skills-evals-base:latest

USER root

# /agent-workspace: agent BPMN mounted read-only at run time.
# /verifier-workspace: Surefire reports.
# /.m2: pre-warmed Maven local repo.
RUN mkdir -p /agent-workspace /.m2 /verifier-workspace \
    && chown -R agent:agent /agent-workspace /.m2 /verifier-workspace

USER agent

ENV MAVEN_OPTS="-Dmaven.repo.local=/.m2"

# Pre-warm: bind-mount the scenarios tree read-only during this RUN and
# resolve every CPT verifier pom into /.m2. No files leak into the
# image — only the populated Maven cache. New scenarios with their own
# cpt-verifier/pom.xml are picked up automatically.
RUN --mount=type=bind,source=src/scenarios,target=/scenarios,ro \
    find /scenarios -path '*/cpt-verifier/pom.xml' -print0 | \
        xargs -0 -I{} mvn -B -q -f {} dependency:go-offline
