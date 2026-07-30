#!/usr/bin/env bash
#
# camunda-static-analysis.sh
# -------------------------------------------------------------------------
# Standalone static-analysis runner for the camunda/camunda monorepo.
#
# Runs two analyzers, on demand, against one or more Maven modules:
#   * SpotBugs     - via the repo's `-Pspotbugs` profile (effort=Max, Low
#                    threshold) with the project's include/exclude filters.
#   * SonarQube    - via the standalone SonarScanner CLI (`sonar-scanner`).
#
# This script ships INSIDE the camunda-branch-code-review skill and runs
# AGAINST a separate camunda/camunda checkout - it is a review tool, not part
# of the project build. Point it at a checkout with --repo or the CAMUNDA_REPO
# env var (defaults to the current git repo). The SpotBugs include filters
# (spotbugs-review-include.xml, spotbugs-all-include.xml) live next to it in
# this scripts/ directory and are resolved relative to the script.
#
# -------------------------------------------------------------------------
# Requirements
#   * The camunda/camunda checkout (Maven wrapper `./mvnw`).
#   * SonarScanner CLI on PATH (`sonar-scanner`) - only for the sonar step.
#       brew install sonar-scanner
#   * A reachable SonarQube/SonarCloud server for the sonar step:
#       SONAR_HOST_URL   (default: http://localhost:9000)
#       SONAR_TOKEN      (required for sonar; user/analysis token)
#       SONAR_ORG        (optional; required for SonarCloud)
#
# -------------------------------------------------------------------------
# Usage
#   camunda-static-analysis.sh [options] [<module>...]
#
#   <module>...   One or more Maven module paths relative to the repo root
#                 (e.g. zeebe/engine service). If omitted, modules are
#                 auto-detected from your uncommitted git changes.
#
# Options
#   -a, --analyzer <list>  Comma list of: spotbugs,sonar (default: both)
#   -p, --profile <name>   SpotBugs rule set: repo|review|all (default: repo)
#                            repo   - CORRECTNESS+MT_CORRECTNESS, fails like CI
#                            review - curated high-signal set (catches vacuous
#                                     instanceof, useless/dead code, == on
#                                     Strings, security, ...); prints findings
#                            all    - every category (noisy; use --changed-only)
#       --changed-only     Report only findings in changed Java files
#       --changed-base <r> Diff base ref for --changed-only (implies it)
#   -r, --repo <path>      Path to the camunda checkout (default: cwd's repo)
#   -k, --key <projectKey> Sonar project key (default: camunda-local)
#   -i, --install-deps     Build/install module deps first (install -am -Dquickly)
#   -o, --offline          Run Maven offline (-o)
#   -h, --help             Show this help.
#
# Examples
#   camunda-static-analysis.sh zeebe/engine
#   camunda-static-analysis.sh -a spotbugs service search/search-client
#   camunda-static-analysis.sh -a spotbugs -p review optimize/backend   # PR review
#   camunda-static-analysis.sh -a spotbugs -p review --changed-only      # changed code
#   camunda-static-analysis.sh -a spotbugs -p all --changed-base origin/main zeebe/engine
#   SONAR_TOKEN=xxx camunda-static-analysis.sh -a sonar -k zeebe-engine zeebe/engine
#   camunda-static-analysis.sh -i            # analyze changed modules, build deps
#   camunda-static-analysis.sh -i -a spotbugs optimize/backend  # Optimize submodule
#
# Note on Optimize: target a submodule (optimize/backend|util|upgrade), not
# `optimize`. The script auto-enables the `include-optimize` profile. If you
# changed an upstream module (e.g. optimize-commons), pass -i so its JAR is
# reinstalled - otherwise compilation resolves against a stale dependency.
# -------------------------------------------------------------------------

set -uo pipefail

# Directory of this script (filters live next to it). Capture before any cd.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Defaults -----------------------------------------------------------
ANALYZERS="spotbugs,sonar"
REPO="${CAMUNDA_REPO:-}"
PROJECT_KEY="camunda-local"
INSTALL_DEPS=0
OFFLINE=""
SB_PROFILE="repo"          # repo | review | all
CHANGED_ONLY=0
CHANGED_BASE=""            # git ref; empty = uncommitted working-tree changes
MODULES=()
SONAR_HOST_URL="${SONAR_HOST_URL:-http://localhost:9000}"
SONAR_TOKEN="${SONAR_TOKEN:-}"
SONAR_ORG="${SONAR_ORG:-}"

# --- Colors -------------------------------------------------------------
if [[ -t 1 ]]; then
  RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
  RED=""; GREEN=""; YELLOW=""; BOLD=""; RESET=""
fi
log()  { printf '%s\n' "$*"; }
info() { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$*"; }
warn() { printf '%s[warn]%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf '%s[error]%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }
usage() { sed -n '2,66p' "$0" | sed 's/^# \{0,1\}//'; }

# --- Parse args ---------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -a|--analyzer)     ANALYZERS="$2"; shift 2 ;;
    -r|--repo)         REPO="$2"; shift 2 ;;
    -k|--key)          PROJECT_KEY="$2"; shift 2 ;;
    -p|--profile)      SB_PROFILE="$2"; shift 2 ;;
    --changed-only)    CHANGED_ONLY=1; shift ;;
    --changed-base)    CHANGED_BASE="$2"; CHANGED_ONLY=1; shift 2 ;;
    -i|--install-deps) INSTALL_DEPS=1; shift ;;
    -o|--offline)      OFFLINE="-o"; shift ;;
    -h|--help)         usage; exit 0 ;;
    --)                shift; while [[ $# -gt 0 ]]; do MODULES+=("$1"); shift; done ;;
    -*)                die "Unknown option: $1 (use -h for help)" ;;
    *)                 MODULES+=("$1"); shift ;;
  esac
done

has() { [[ ",$ANALYZERS," == *",$1,"* ]]; }

# --- Resolve SpotBugs profile -> include filter -------------------------
# repo   : use the repo's own filter (CORRECTNESS + MT_CORRECTNESS), run
#          spotbugs:check (fails on findings) - matches CI exactly.
# review : curated high-signal filter (adds BC_VACUOUS_INSTANCEOF, useless
#          code, self-compares, == on Strings, security...).
# all    : every category (noisy; pair with --changed-only).
SB_INCLUDE=""
case "$SB_PROFILE" in
  repo)   ;;
  review) SB_INCLUDE="$SELF_DIR/spotbugs-review-include.xml" ;;
  all)    SB_INCLUDE="$SELF_DIR/spotbugs-all-include.xml" ;;
  *)      die "Unknown --profile '$SB_PROFILE' (expected: repo|review|all)" ;;
esac
[[ -n "$SB_INCLUDE" && ! -f "$SB_INCLUDE" ]] && die "Missing filter file: $SB_INCLUDE"

# --- Locate repo --------------------------------------------------------
if [[ -z "$REPO" ]]; then
  REPO="$(git rev-parse --show-toplevel 2>/dev/null)" \
    || die "Not inside a git repo and --repo/CAMUNDA_REPO not set."
fi
[[ -f "$REPO/pom.xml" ]] || die "Repo has no pom.xml: $REPO"
cd "$REPO"
MVN="./mvnw"; [[ -x "$MVN" ]] || MVN="mvn"
info "Repo: ${BOLD}${REPO}${RESET}"

# --- Auto-detect modules from git changes -------------------------------
find_module_for_path() {
  local p="$1" candidate=""
  p="$(dirname "$p")"
  while [[ "$p" != "." && -n "$p" ]]; do
    [[ -f "$p/pom.xml" ]] && candidate="$p"
    p="$(dirname "$p")"
  done
  [[ -n "$candidate" ]] && printf '%s\n' "$candidate"
}

if [[ ${#MODULES[@]} -eq 0 ]]; then
  info "No modules given - detecting from uncommitted git changes..."
  mapfile -t CHANGED < <( { git diff --name-only -- '*.java'; \
                            git diff --cached --name-only -- '*.java'; \
                            git ls-files --others --exclude-standard -- '*.java'; } | sort -u )
  declare -A SEEN=()
  for f in "${CHANGED[@]}"; do
    [[ -z "$f" || ! -e "$f" ]] && continue
    m="$(find_module_for_path "$f")"
    [[ -n "$m" && -z "${SEEN[$m]:-}" ]] && { SEEN[$m]=1; MODULES+=("$m"); }
  done
  [[ ${#MODULES[@]} -eq 0 ]] && die "No changed Java modules detected. Pass module path(s) explicitly."
fi

for m in "${MODULES[@]}"; do
  [[ -f "$m/pom.xml" ]] || die "Not a Maven module (no pom.xml): $m"
done
PL="$(IFS=,; echo "${MODULES[*]}")"
info "Modules:   ${BOLD}${PL}${RESET}"
info "Analyzers: ${ANALYZERS}"
has spotbugs && info "SpotBugs profile: ${BOLD}${SB_PROFILE}${RESET}$( [[ "$CHANGED_ONLY" -eq 1 ]] && echo " (changed files only)")"

# Build the set of changed Java source files for --changed-only reporting.
# Match on the package-relative source path (e.g. io/camunda/.../Foo.java) so
# same-named files in different modules don't collide in a monorepo; keep a
# basename set as a fallback for SpotBugs entries that lack a sourcepath.
declare -A CHANGED_SET=()
declare -A CHANGED_BASENAMES=()
if [[ "$CHANGED_ONLY" -eq 1 ]]; then
  if [[ -n "$CHANGED_BASE" ]]; then
    mapfile -t _cf < <(git diff --name-only "$CHANGED_BASE" -- '*.java')
  else
    mapfile -t _cf < <( { git diff --name-only -- '*.java'; \
                          git diff --cached --name-only -- '*.java'; \
                          git ls-files --others --exclude-standard -- '*.java'; } | sort -u )
  fi
  for f in "${_cf[@]}"; do
    [[ -z "$f" ]] && continue
    rel="$f"
    case "$f" in
      */src/main/java/*) rel="${f#*/src/main/java/}" ;;
      */src/test/java/*) rel="${f#*/src/test/java/}" ;;
      src/main/java/*)   rel="${f#src/main/java/}" ;;
      src/test/java/*)   rel="${f#src/test/java/}" ;;
    esac
    CHANGED_SET["$rel"]=1
    CHANGED_BASENAMES["$(basename "$f")"]=1
  done
  info "Changed Java files: ${#CHANGED_BASENAMES[@]}"
fi

# Optimize lives behind the `include-optimize` profile, which is auto-disabled
# by -Dquickly. If any target is an Optimize module, force the profile on (it
# overrides the activation condition) so `-pl optimize/...` resolves in the
# reactor even with -Dquickly.
OPT_PROFILE=""
for m in "${MODULES[@]}"; do
  if [[ "$m" == optimize || "$m" == optimize/* ]]; then
    OPT_PROFILE="-P include-optimize"
    info "Detected Optimize module(s) - enabling ${BOLD}include-optimize${RESET} profile."
    break
  fi
done

# --- Optionally install dependencies ------------------------------------
if [[ "$INSTALL_DEPS" -eq 1 ]]; then
  info "Installing module dependencies (quickly)..."
  $MVN $OFFLINE $OPT_PROFILE install -pl "$PL" -am -Dquickly -T1C \
    || die "Dependency install failed; cannot analyze."
fi

declare -A RESULT=()
run_step() {
  local name="$1"; shift
  info "Running ${BOLD}${name}${RESET} ..."
  if "$@"; then RESULT[$name]="PASS"; else RESULT[$name]="FAIL"; fi
}

# --- SpotBugs -----------------------------------------------------------
# The -Pspotbugs profile wires the repo's exclude filters and the
# zeebe-build-tools dependency. Report is written to <m>/target/spotbugsXml.xml.
#
#   repo   -> spotbugs:check with the repo include filter (fails on findings,
#             matches CI).
#   review/all -> override the include filter, run the non-failing
#             spotbugs:spotbugs goal, then parse + print findings ourselves
#             (optionally scoped to changed files).
print_spotbugs_findings() {
  command -v python3 >/dev/null 2>&1 \
    || die "python3 is required to parse SpotBugs findings but was not found on PATH."
  CHANGED_ONLY="$CHANGED_ONLY" \
  CHANGED_LIST="$(printf '%s\n' "${!CHANGED_SET[@]}")" \
  CHANGED_BASENAMES="$(printf '%s\n' "${!CHANGED_BASENAMES[@]}")" \
  python3 - "$@" <<'PY'
import os, sys, glob
import xml.etree.ElementTree as ET

changed_only = os.environ.get("CHANGED_ONLY") == "1"
changed = {l for l in os.environ.get("CHANGED_LIST", "").splitlines() if l}
changed_basenames = {l for l in os.environ.get("CHANGED_BASENAMES", "").splitlines() if l}
RED, YEL, GRN, BOLD, RST = "\033[31m", "\033[33m", "\033[32m", "\033[1m", "\033[0m"
prio = {"1": f"{RED}HIGH{RST}", "2": f"{YEL}MED {RST}", "3": f"{GRN}LOW {RST}"}

total = 0
for module in sys.argv[1:]:
    xml = os.path.join(module, "target", "spotbugsXml.xml")
    if not os.path.isfile(xml):
        continue
    root = ET.parse(xml).getroot()
    for b in root.iter("BugInstance"):
        sl = b.find("SourceLine")
        # Prefer the package-relative sourcepath (unique across modules); fall
        # back to the bare sourcefile only when sourcepath is unavailable.
        sp = sl.get("sourcepath") if sl is not None else None
        src = sl.get("sourcefile") if sl is not None else None
        if changed_only:
            if sp is not None:
                if sp not in changed:
                    continue
            elif src is None or src not in changed_basenames:
                continue
        cls = next((c.get("classname", "") for c in b.findall("Class")), "")
        line = sl.get("start") if sl is not None else "?"
        loc = sp or src or "?"
        msg = b.findtext("LongMessage") or b.findtext("ShortMessage") or ""
        p = prio.get(b.get("priority", "2"), "    ")
        print(f"  [{p}] {BOLD}{b.get('type')}{RST} ({b.get('category')})")
        print(f"        {loc}:{line}  {cls}")
        print(f"        {msg}")
        total += 1

print()
if total:
    print(f"{RED}{BOLD}SpotBugs: {total} finding(s).{RST}")
else:
    scope = " in changed files" if changed_only else ""
    print(f"{GRN}SpotBugs: no findings{scope}.{RST}")
sys.exit(1 if total else 0)
PY
}

if has spotbugs; then
  if [[ "$SB_PROFILE" == "repo" ]]; then
    run_step "spotbugs" \
      $MVN $OFFLINE -Pspotbugs $OPT_PROFILE test-compile spotbugs:check -pl "$PL" -DskipTests
  else
    info "Running ${BOLD}spotbugs${RESET} (profile=${SB_PROFILE}) ..."
    if $MVN $OFFLINE -Pspotbugs $OPT_PROFILE test-compile spotbugs:spotbugs \
         -pl "$PL" -DskipTests -Dspotbugs.include="$SB_INCLUDE"; then
      echo
      info "SpotBugs findings (${SB_PROFILE}):"
      if print_spotbugs_findings "${MODULES[@]}"; then
        RESULT["spotbugs"]="PASS"
      else
        RESULT["spotbugs"]="FAIL"
      fi
    else
      RESULT["spotbugs"]="FAIL"
    fi
  fi
fi

# --- SonarQube (standalone SonarScanner CLI) ----------------------------
# Compiles classes (needed for sonar.java.binaries) then runs sonar-scanner
# per module. Requires a reachable SonarQube server + token.
if has sonar; then
  if ! command -v sonar-scanner >/dev/null 2>&1; then
    warn "sonar-scanner not found on PATH - skipping sonar (brew install sonar-scanner)."
    RESULT["sonar"]="SKIP"
  elif [[ -z "$SONAR_TOKEN" ]]; then
    warn "SONAR_TOKEN not set - skipping sonar."
    RESULT["sonar"]="SKIP"
  else
    info "Compiling modules for Sonar (sonar.java.binaries)..."
    if ! $MVN $OFFLINE $OPT_PROFILE test-compile -pl "$PL" -Dquickly; then
      RESULT["sonar"]="FAIL"
    else
      sonar_ok=1
      for m in "${MODULES[@]}"; do
        key="${PROJECT_KEY}"
        [[ ${#MODULES[@]} -gt 1 ]] && key="${PROJECT_KEY}-$(echo "$m" | tr '/' '-')"
        info "Sonar scan: ${BOLD}${m}${RESET} (key=${key})"
        org_arg=(); [[ -n "$SONAR_ORG" ]] && org_arg=(-Dsonar.organization="$SONAR_ORG")
        ( cd "$m" && sonar-scanner \
            -Dsonar.host.url="$SONAR_HOST_URL" \
            -Dsonar.token="$SONAR_TOKEN" \
            -Dsonar.projectKey="$key" \
            -Dsonar.projectName="$key" \
            -Dsonar.sources=src/main/java \
            -Dsonar.tests=src/test/java \
            -Dsonar.java.binaries=target/classes \
            -Dsonar.java.test.binaries=target/test-classes \
            -Dsonar.java.source=21 \
            "${org_arg[@]}" ) || sonar_ok=0
      done
      [[ "$sonar_ok" -eq 1 ]] && RESULT["sonar"]="PASS" || RESULT["sonar"]="FAIL"
    fi
  fi
fi

# --- Summary ------------------------------------------------------------
echo
info "${BOLD}Static analysis summary${RESET}"
fail=0
for name in spotbugs sonar; do
  status="${RESULT[$name]:-}"
  [[ -z "$status" ]] && continue
  case "$status" in
    PASS) printf '  %s%-10s PASS%s\n' "$GREEN" "$name" "$RESET" ;;
    SKIP) printf '  %s%-10s SKIP%s\n' "$YELLOW" "$name" "$RESET" ;;
    *)    printf '  %s%-10s FAIL%s\n' "$RED" "$name" "$RESET"; fail=1 ;;
  esac
done

if has spotbugs; then
  echo
  log "SpotBugs reports:"
  for m in "${MODULES[@]}"; do log "  $m/target/spotbugsXml.xml"; done
fi
if has sonar && [[ "${RESULT[sonar]:-}" == "PASS" ]]; then
  log "Sonar results: ${SONAR_HOST_URL}/dashboard?id=${PROJECT_KEY}"
fi

[[ "$fail" -eq 1 ]] && { echo; warn "One or more analyzers reported issues."; exit 1; }
echo
info "${GREEN}Done.${RESET}"
