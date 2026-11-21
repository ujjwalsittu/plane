#!/bin/sh
# Bearer-only end-to-end check: the built image against a stub Plane API, one MCP client sending only
# `Authorization: Bearer <token>`. Usage: docker build -t plane-mcp-p7 . && ./e2e_bearer.sh [image]
set -e
cd "$(dirname "$0")"
IMAGE="${1:-plane-mcp-p7}"
docker run --rm --platform linux/amd64 -v "$PWD":/t -e PYTHONPATH=/app -e STUB_TOKEN=plane_api_e2e_token \
  -e PLANE_BASE_URL=http://127.0.0.1:8000 -e PLANE_INTERNAL_BASE_URL=http://127.0.0.1:8000 \
  -e PLANE_OAUTH_PROVIDER_BASE_URL=http://127.0.0.1:8211 -e PLANE_OAUTH_PROVIDER_CLIENT_ID=unused -e PLANE_OAUTH_PROVIDER_CLIENT_SECRET=unused \
  --entrypoint sh "$IMAGE" -c '
    python /t/stub_plane.py &
    python -m plane_mcp http >/tmp/mcp.log 2>&1 &
    for i in $(seq 1 40); do python -c "import socket;socket.create_connection((\"127.0.0.1\",8211),1)" 2>/dev/null && break; sleep 1; done
    if python -W ignore /t/e2e_bearer_client.py >/tmp/client.log 2>&1; then grep -v "Warning\|^  from\|It will" /tmp/client.log
    else cat /tmp/client.log; tail -30 /tmp/mcp.log; exit 1; fi
  '
