# with-c8ctl sandbox image — base + c8ctl pre-installed.
#
# Used by scenarios 1–9. Built FROM base.Dockerfile so the only
# difference is the c8ctl install + initial element-template sync.

# `evals-base` is a Buildx named context wired to the base target in
# sandboxes/docker-bake.hcl (the only supported build path). Resolves on the
# container driver too, unlike a `FROM <local-image-tag>:latest`.
FROM evals-base

# Install latest c8ctl globally — as the agent, into its npm prefix (see
# base.Dockerfile), so the agent can upgrade it like any user-installed CLI.
# Plan pins ≥ 3.0.0 (bpmn, element-template, feel plugins live there).
RUN npm install -g @camunda8/cli

# Warm the element-template cache so scenarios don't pay sync cost on
# every run. Failure is non-fatal — the cache will rebuild on first
# use inside the sandbox if upstream is unreachable at image build time.
RUN c8ctl element-template sync || true

# GitHub Copilot CLI for the model-comparison agent (core/copilot_cli.py), so
# samples don't each spend part of their time limit installing it. Last layer,
# keyed on the version: CI passes the current npm version, so the layer cache
# refreshes when Copilot releases and only this layer rebuilds. Images without
# it (e.g. base) fall back to installing at run time.
ARG COPILOT_CLI_VERSION=latest
RUN npm install -g --no-fund --no-audit "@github/copilot@${COPILOT_CLI_VERSION}" \
    && copilot --version
