#!/usr/bin/env bash
# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Deploy a build of this fork to the Coolify "plane" service and make sure it is actually live.
#
#   deploy-plane.sh <commit-sha | sha-xxxxxxx | custom-v* tag>
#
# 1. Checks the images for that release exist on GHCR.
# 2. Sets APP_RELEASE on the Coolify service and triggers a deploy.
# 3. Waits until https://$PLANE_HOST/version.json reports that commit and the API answers.
# 4. If the stack stalls (a deploy can stop the old containers without starting the new ones),
#    asks Coolify to start the service and waits again.
# On failure it prints the previous APP_RELEASE so you can roll back with the same script.
#
# Environment:
#   COOLIFY_TOKEN        Coolify API token (required)
#   COOLIFY_URL          default https://central.azeonics.com
#   PLANE_SERVICE_UUID   default uppph92wubnjsj2sp5ghyc6x
#   PLANE_HOST           default plane.azeonics.com
#   IMAGE_OWNER          default ujjwalsittu
#   DEPLOY_TIMEOUT       seconds to wait per attempt, default 600

set -euo pipefail

COOLIFY_URL="${COOLIFY_URL:-https://central.azeonics.com}"
PLANE_SERVICE_UUID="${PLANE_SERVICE_UUID:-uppph92wubnjsj2sp5ghyc6x}"
PLANE_HOST="${PLANE_HOST:-plane.azeonics.com}"
IMAGE_OWNER="${IMAGE_OWNER:-ujjwalsittu}"
DEPLOY_TIMEOUT="${DEPLOY_TIMEOUT:-600}"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { log "ERROR: $*"; exit 1; }

[ $# -eq 1 ] || die "usage: $0 <commit-sha | sha-xxxxxxx | custom-v* tag>"
[ -n "${COOLIFY_TOKEN:-}" ] || die "COOLIFY_TOKEN is not set"
command -v curl >/dev/null || die "curl is required"
command -v jq >/dev/null || die "jq is required"

# Release tag and the commit we expect /version.json to report.
input="$1"
case "$input" in
  custom-v*)
    release="$input"
    expected_sha="$(git rev-parse "${input}^{commit}" 2>/dev/null)" || die "unknown tag $input (fetch tags first)"
    ;;
  sha-*)
    release="$input"
    expected_sha="$(git rev-parse "${input#sha-}^{commit}" 2>/dev/null)" || die "unknown commit ${input#sha-}"
    ;;
  *)
    expected_sha="$(git rev-parse "${input}^{commit}" 2>/dev/null)" || die "unknown commit $input"
    release="sha-${expected_sha:0:7}"
    ;;
esac

api() {
  local method="$1" path="$2" body="${3:-}"
  curl -fsS -X "$method" "${COOLIFY_URL}/api/v1${path}" \
    -H "Authorization: Bearer ${COOLIFY_TOKEN}" -H "Accept: application/json" \
    ${body:+-H "Content-Type: application/json" --data "$body"}
}

# 1. Images exist (anonymous pull token; the packages are public).
for image in frontend backend admin space live proxy; do
  token="$(curl -fsS "https://ghcr.io/token?scope=repository:${IMAGE_OWNER}/plane-${image}:pull" | jq -r .token)"
  curl -fsS -o /dev/null -H "Authorization: Bearer ${token}" \
    -H "Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.v2+json" \
    "https://ghcr.io/v2/${IMAGE_OWNER}/plane-${image}/manifests/${release}" \
    || die "ghcr.io/${IMAGE_OWNER}/plane-${image}:${release} not found (did the image build finish?)"
done
log "Images for ${release} found on GHCR"

# 2. Point the service at the release and deploy.
previous="$(api GET "/services/${PLANE_SERVICE_UUID}/envs" | jq -r '[.[] | select(.key=="APP_RELEASE")][0].value // empty')"
log "Current APP_RELEASE: ${previous:-<unset>} -> ${release}"
api PATCH "/services/${PLANE_SERVICE_UUID}/envs" "$(jq -nc --arg v "$release" '{key:"APP_RELEASE",value:$v}')" >/dev/null
api GET "/deploy?uuid=${PLANE_SERVICE_UUID}&force=false" >/dev/null
log "Deploy triggered"

is_live() {
  local live_sha api_status
  live_sha="$(curl -fsS --max-time 10 "https://${PLANE_HOST}/version.json?ts=$(date +%s)" 2>/dev/null | jq -r .sha 2>/dev/null || true)"
  api_status="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://${PLANE_HOST}/api/instances/" || true)"
  [ "$live_sha" = "$expected_sha" ] && [ "$api_status" = "200" ]
}

wait_live() {
  local deadline=$((SECONDS + DEPLOY_TIMEOUT))
  while [ $SECONDS -lt $deadline ]; do
    if is_live; then return 0; fi
    sleep 10
  done
  return 1
}

# 3. Wait for the new build; 4. start the service if it stalled.
if wait_live; then
  log "Live: ${release} (${expected_sha:0:7}) on https://${PLANE_HOST}"
  exit 0
fi

log "Not live after ${DEPLOY_TIMEOUT}s; asking Coolify to start the service"
api POST "/services/${PLANE_SERVICE_UUID}/start" >/dev/null 2>&1 \
  || api GET "/services/${PLANE_SERVICE_UUID}/start" >/dev/null 2>&1 \
  || log "start request failed"

if wait_live; then
  log "Live after starting the service: ${release} (${expected_sha:0:7})"
  exit 0
fi

die "${release} is not live. Check Coolify logs. Roll back with: $0 ${previous:-<previous release>}"
