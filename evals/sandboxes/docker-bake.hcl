# Build definition for the three eval sandbox images, shared by the local
# `make eval-images` target and CI. Run from the evals/ directory:
#
#   docker buildx bake -f sandboxes/docker-bake.hcl --load
#
# with-c8ctl and verifier are FROM base; the `contexts` wiring builds base once
# and feeds it in-process, so no base image needs to exist in a registry or the
# local store first. Loading into the docker daemon is a caller concern (--load
# locally, load: true in CI), not declared here. CI adds layer caching with
# --set <target>.cache-from/to=type=gha (see .github/workflows/eval.yml).

# provenance=false keeps each build a single-platform image manifest (no
# attestation manifest list), so `docker save | docker load` round-trips
# cleanly when CI ships the images to the matrix jobs as an artifact.

target "base" {
  context    = "sandboxes"
  dockerfile = "base.Dockerfile"
  tags       = ["camunda-skills-evals-base:latest"]
  provenance = false
}

target "with-c8ctl" {
  context    = "sandboxes"
  dockerfile = "with-c8ctl.Dockerfile"
  contexts   = { evals-base = "target:base" }
  tags       = ["camunda-skills-evals-with-c8ctl:latest"]
  provenance = false
}

# Context is the evals/ root so the Dockerfile can bind-mount scenarios/*/
# cpt-verifier/pom.xml to pre-warm Maven (see verifier.Dockerfile).
target "verifier" {
  context    = "."
  dockerfile = "sandboxes/verifier.Dockerfile"
  contexts   = { evals-base = "target:base" }
  tags       = ["camunda-skills-evals-verifier:latest"]
  provenance = false
}

group "default" {
  targets = ["base", "with-c8ctl", "verifier"]
}
