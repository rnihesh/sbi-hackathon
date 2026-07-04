#!/usr/bin/env bash
#
# prod-smoke.sh - non-LLM production smoke checks for Sarathi.
#
# Curl-based liveness checks against the deployed frontend and API. Every check
# is a plain HTTP request: no chat messages are ever sent, so this costs ZERO
# LLM spend and is safe to run against production as often as you like. The one
# POST (create chat session) writes nothing for an anonymous caller - it just
# mints a conversation id - so it leaves no junk behind either.
#
# Usage:
#   bash scripts/prod-smoke.sh
#
# Override the targets for staging / local:
#   SARATHI_FE_URL=http://localhost:3000 \
#   SARATHI_API_URL=http://localhost:8000 \
#   bash scripts/prod-smoke.sh
#
# Exit code is 0 only if every check passes, so it doubles as a CI gate.

set -u

FE_URL="${SARATHI_FE_URL:-https://sarathi.niheshr.com}"
API_URL="${SARATHI_API_URL:-https://sarathi-api.niheshr.com}"
TIMEOUT="${SARATHI_SMOKE_TIMEOUT:-15}"

# Colors only when stdout is a terminal.
if [ -t 1 ]; then
  GREEN=$'\033[32m'; RED=$'\033[31m'; DIM=$'\033[2m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
  GREEN=''; RED=''; DIM=''; BOLD=''; RESET=''
fi

pass_count=0
fail_count=0

# check <name> <method> <url> <expected-codes...>
# expected-codes is a space-separated list; the actual code must match one.
check() {
  local name="$1" method="$2" url="$3"
  shift 3
  local expected="$*"

  local args=(-s -o /dev/null -w '%{http_code}' -m "$TIMEOUT")
  if [ "$method" = "POST" ]; then
    # Minimal valid empty JSON body; no message field, so no agent/LLM runs.
    args+=(-X POST -H 'Content-Type: application/json' -d '{}')
  fi

  local code
  code=$(curl "${args[@]}" "$url" 2>/dev/null || echo "000")

  local ok="no"
  local want
  for want in $expected; do
    if [ "$code" = "$want" ]; then ok="yes"; break; fi
  done

  if [ "$ok" = "yes" ]; then
    pass_count=$((pass_count + 1))
    printf "  %sPASS%s  %-3s  %-28s %s%s %s%s\n" \
      "$GREEN" "$RESET" "$code" "$name" "$DIM" "$method" "$url" "$RESET"
  else
    fail_count=$((fail_count + 1))
    printf "  %sFAIL%s  %-3s  %-28s %s%s %s (wanted %s)%s\n" \
      "$RED" "$RESET" "$code" "$name" "$DIM" "$method" "$url" "$expected" "$RESET"
  fi
}

printf "%sSarathi prod smoke%s  %s(no LLM cost)%s\n" "$BOLD" "$RESET" "$DIM" "$RESET"
printf "  frontend  %s\n" "$FE_URL"
printf "  api       %s\n\n" "$API_URL"

printf "%sFrontend%s\n" "$BOLD" "$RESET"
check "landing"        GET "$FE_URL/"                     200
check "manifest"       GET "$FE_URL/manifest.webmanifest" 200
check "og-image"       GET "$FE_URL/opengraph-image"      200
check "terms"          GET "$FE_URL/terms"                200
check "policy"         GET "$FE_URL/policy"               200

printf "\n%sAPI%s\n" "$BOLD" "$RESET"
check "healthz"        GET  "$API_URL/healthz"                    200
check "api docs"       GET  "$API_URL/docs"                       200
check "openapi schema" GET  "$API_URL/openapi.json"               200
# Console health is staff-gated: an unauthenticated caller must be rejected.
check "console auth-gate" GET "$API_URL/api/v1/console/health"    401 403
# Session create is allowed anonymously and sends no message, so no LLM spend.
check "chat session"   POST "$API_URL/api/v1/chat/sessions"       200

printf "\n"
total=$((pass_count + fail_count))
if [ "$fail_count" -eq 0 ]; then
  printf "%s%d/%d checks passed.%s\n" "$GREEN" "$pass_count" "$total" "$RESET"
  exit 0
else
  printf "%s%d/%d checks passed, %d failed.%s\n" \
    "$RED" "$pass_count" "$total" "$fail_count" "$RESET"
  exit 1
fi
