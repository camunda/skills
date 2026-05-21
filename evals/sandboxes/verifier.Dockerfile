# Verifier sandbox image — runs untrusted agent-generated code (mvn test).
#
# Used by scenarios with `verifier: "cpt"` or scenarios where the
# agent's own Java is the deliverable (scenario #7). Network egress is
# denied at the compose layer (see compose.yaml); this image only needs
# the toolchain to run `mvn test` offline against a cached .m2.
#
# v1 uses online Maven with a .m2 cache volume. FOLLOWUP-EVAL-07 bakes
# the dep tree and switches to `mvn -o`.

FROM camunda-skills-evals-base:latest

USER root

# The verifier reads agent artifacts mounted read-only at /outputs and
# writes Surefire reports under /workspace/target. The Maven local
# repo lives at /.m2 (volume) so deps don't redownload per scenario.
RUN mkdir -p /outputs /.m2 \
    && chown -R agent:agent /outputs /.m2

USER agent

ENV MAVEN_OPTS="-Dmaven.repo.local=/.m2"
