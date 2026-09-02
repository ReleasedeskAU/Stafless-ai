#!/usr/bin/env bash
# First-time StaffLess AI setup without the web UI (Community / MIT).
# Engine source: this Stafless-ai fork of onyx-foss. ONYX_* names and API
# paths stay as that software ships.
#
# Host OS: Ubuntu 24.04 LTS. This script is HTTP-only (curl/jq); it has no
# 22.04-specific packages or paths. Same apt names as 22.04:
#   sudo apt install --yes curl jq
# Run HOST-SETUP.md first (Docker CE + iptables-nft + vm.max_map_count), then
# build the foss backend image (CHECKLIST.md) before compose.
#
# Sequence confirmed from this tree (same MIT routers as main Community):
#   terraform-provider-onyx/examples/bootstrap/mint_api_key.sh  (register + login)
#   backend/onyx/server/manage/llm/api.py                       (PUT /admin/llm/provider)
#   backend/onyx/server/manage/embedding/api.py                 (PUT /admin/embedding/embedding-provider)
#   backend/onyx/server/manage/search_settings.py               (POST /search-settings/set-new-search-settings)
#   backend/onyx/server/pat/api.py                              (POST /user/pats)
#
# Does NOT call POST /admin/api-key. On Hub/main images that route is
# Business-tier (PATH_PREFIX_MIN_TIER in backend/ee). Foss still mounts the
# MIT router in onyx.server.api_key.api; do not use it — Community auth for
# ReleaseDesk Everywhere is an unrestricted PAT.
#
# Usage (after compose is healthy), from deployment/docker_compose:
#   ONYX_SERVER_URL=http://localhost:3000 \
#   ONYX_ADMIN_EMAIL=admin@example.com \
#   ONYX_ADMIN_PASSWORD='...' \
#   OPENAI_API_KEY='sk-...' \
#   ../releasedesk-overlay/setup-onyx.sh
#
# Requires: curl, jq. Prints the PAT once to stdout; store it in ReleaseDesk
# Everywhere secrets, not in git.
set -euo pipefail

server_url="${ONYX_SERVER_URL:-http://localhost:3000}"
email="${ONYX_ADMIN_EMAIL:-}"
password="${ONYX_ADMIN_PASSWORD:-}"
openai_key="${OPENAI_API_KEY:-}"
pat_name="${ONYX_PAT_NAME:-release-desk}"
# Chat model names must exist on the OpenAI account. Override if needed.
default_model="${ONYX_DEFAULT_MODEL:-gpt-4o-mini}"
embed_model="${ONYX_EMBED_MODEL:-text-embedding-3-small}"
embed_dim="${ONYX_EMBED_DIM:-1536}"

if [ -z "$email" ] || [ -z "$password" ] || [ -z "$openai_key" ]; then
  echo "set ONYX_ADMIN_EMAIL, ONYX_ADMIN_PASSWORD, and OPENAI_API_KEY" >&2
  echo "admin credentials are required rather than defaulted: the first register becomes admin" >&2
  exit 1
fi

for tool in curl jq; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "$tool is required" >&2
    exit 1
  }
done

base="${server_url%/}"
cookie_jar="$(mktemp)"
body="$(mktemp)"
trap 'rm -f "$cookie_jar" "$body"' EXIT

json_header() {
  curl -sS -o "$body" -w '%{http_code}' -b "$cookie_jar" -c "$cookie_jar" \
    -H 'Content-Type: application/json' "$@"
}

# --- 1–2. First admin + session cookie (same as mint_api_key.sh) ---------------
register_code="$(curl -sS -o "$body" -w '%{http_code}' \
  -X POST "${base}/auth/register" \
  -H 'Content-Type: application/json' \
  -d "$(jq -cn --arg e "$email" --arg p "$password" \
    '{email: $e, username: $e, password: $p}')" || echo 000)"

case "$register_code" in
  2*|400) ;;
  *)
    echo "register answered HTTP ${register_code}" >&2
    head -c 500 "$body" >&2
    echo >&2
    exit 1
    ;;
esac

if ! curl -fsS -X POST "${base}/auth/login" \
  -c "$cookie_jar" \
  --data-urlencode "username=${email}" \
  --data-urlencode "password=${password}" \
  >/dev/null; then
  echo "login as ${email} failed at ${base}" >&2
  exit 1
fi

# --- 3. OpenAI chat provider ---------------------------------------------------
# LLMProviderUpsertRequest: field is "provider", not Terraform's provider_type.
llm_payload="$(jq -cn --arg k "$openai_key" --arg m "$default_model" \
  '{
    name: "openai",
    provider: "openai",
    api_key: $k,
    api_key_changed: true,
    is_public: true,
    model_configurations: [
      {name: "gpt-4o", is_visible: true},
      {name: $m, is_visible: true}
    ]
  }')"

code="$(json_header -X PUT "${base}/admin/llm/provider?is_creation=true" -d "$llm_payload")"
if [ "$code" != "200" ]; then
  # Idempotent re-run: update existing provider by id.
  list_code="$(json_header "${base}/admin/llm/provider")"
  if [ "$list_code" != "200" ]; then
    echo "creating LLM provider failed HTTP ${code}; listing providers failed HTTP ${list_code}" >&2
    head -c 500 "$body" >&2
    echo >&2
    exit 1
  fi
  provider_id="$(jq -r '[.providers[]? | select(.provider == "openai" or .name == "openai")][0].id // empty' "$body")"
  if [ -z "$provider_id" ]; then
    echo "creating LLM provider failed HTTP ${code} and no existing openai provider found" >&2
    head -c 500 "$body" >&2
    echo >&2
    exit 1
  fi
  code="$(json_header -X PUT "${base}/admin/llm/provider?is_creation=false" \
    -d "$(jq -cn --argjson id "$provider_id" --argjson p "$llm_payload" '$p + {id: $id}')")"
  if [ "$code" != "200" ]; then
    echo "updating LLM provider failed HTTP ${code}" >&2
    head -c 500 "$body" >&2
    echo >&2
    exit 1
  fi
fi

provider_id="$(jq -r '.id // empty' "$body")"
if [ -z "$provider_id" ]; then
  echo "LLM provider response missing id" >&2
  exit 1
fi

# --- 4. Deployment-wide default model ------------------------------------------
code="$(json_header -X POST "${base}/admin/llm/default" \
  -d "$(jq -cn --argjson id "$provider_id" --arg m "$default_model" \
    '{provider_id: $id, model_name: $m}')")"
if [ "$code" != "200" ] && [ "$code" != "204" ]; then
  echo "setting default LLM failed HTTP ${code}" >&2
  head -c 500 "$body" >&2
  echo >&2
  exit 1
fi

# --- 5. Cloud embedding credentials --------------------------------------------
code="$(json_header -X PUT "${base}/admin/embedding/embedding-provider" \
  -d "$(jq -cn --arg k "$openai_key" \
    '{provider_type: "openai", api_key: $k}')")"
if [ "$code" != "200" ]; then
  echo "upserting embedding provider failed HTTP ${code}" >&2
  head -c 500 "$body" >&2
  echo >&2
  exit 1
fi

# --- 6. Switch search settings off local nomic → OpenAI embeddings -------------
# UI values: web/src/lib/indexing/index.ts (text-embedding-3-small, dim 1536, normalize false).
# SearchSettingsCreationRequest requires index_name (str | None). The UI sends
# null and the server fills danswer_chunk_{clean_model_name(model)} — see
# search_settings.py and embedding_configs.py. Do not delete the field (422).
# Do not reuse the current nomic index_name. Send the same computed name the
# server would generate (hyphens/slashes/dots → underscores, lowercased).
code="$(json_header "${base}/search-settings/get-current-search-settings")"
if [ "$code" != "200" ]; then
  echo "get-current-search-settings failed HTTP ${code}" >&2
  head -c 500 "$body" >&2
  echo >&2
  exit 1
fi

overlay_dir="$(cd "$(dirname "$0")" && pwd)"
search_payload="$(jq -c --arg m "$embed_model" --argjson d "$embed_dim" \
  -f "${overlay_dir}/search-settings-payload.jq" "$body")"

code="$(json_header -X POST "${base}/search-settings/set-new-search-settings" -d "$search_payload")"
if [ "$code" != "200" ]; then
  echo "set-new-search-settings failed HTTP ${code}" >&2
  head -c 500 "$body" >&2
  echo >&2
  exit 1
fi

# --- 7. Unrestricted PAT for ReleaseDesk Everywhere (Community-safe; not /admin/api-key) -
# CreateTokenRequest: scopes null = full user access (pat/models.py).
code="$(json_header -X POST "${base}/user/pats" \
  -d "$(jq -cn --arg n "$pat_name" '{name: $n, expiration_days: null, scopes: null}')")"
if [ "$code" != "200" ]; then
  echo "creating PAT failed HTTP ${code}" >&2
  echo "if this is 402, you hit a Business-only route — this script uses /user/pats, not /admin/api-key" >&2
  head -c 500 "$body" >&2
  echo >&2
  exit 1
fi

pat="$(jq -r '.token // empty' "$body")"
if [ -z "$pat" ]; then
  echo "PAT response did not include token (it is only returned once)" >&2
  exit 1
fi

echo "$pat"
echo "store this PAT as the ReleaseDesk Everywhere engine bearer (ONYX_API_KEY); it is not shown again" >&2
echo "turn ENABLE_PUBLIC_DOCS=false in .env and recreate nginx/api after setup" >&2
