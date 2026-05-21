# with-c8ctl sandbox image — base + c8ctl pre-installed.
#
# Used by scenarios 1–9. Built FROM base.Dockerfile so the only
# difference is the c8ctl install + initial element-template sync.

FROM camunda-skills-evals-base:latest

USER root

# Install latest c8ctl globally. Plan pins ≥ 3.0.0 (bpmn,
# element-template, feel plugins live there).
RUN npm install -g @camunda8/cli

USER agent

# Warm the element-template cache so scenarios don't pay sync cost on
# every run. Failure is non-fatal — the cache will rebuild on first
# use inside the sandbox if upstream is unreachable at image build time.
RUN c8ctl element-template sync || true
