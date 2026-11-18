# Plane MCP server with the fork's patches:
# - API-key auth: only a 401/403 from Plane invalidates a key; 429s, restarts and timeouts no longer drop clients.
# - patch_mcp.py: project dates/priority/status, milestone description and work item completed_at.
ARG MCP_VERSION=v0.3.6
FROM makeplane/plane-mcp-server:${MCP_VERSION}
COPY plane_header_auth_provider.py /app/plane_mcp/auth/plane_header_auth_provider.py
COPY patch_mcp.py /tmp/patch_mcp.py
RUN python /tmp/patch_mcp.py && python -m compileall -q /app/plane_mcp /usr/local/lib/python3.11/site-packages/plane/models && rm /tmp/patch_mcp.py
