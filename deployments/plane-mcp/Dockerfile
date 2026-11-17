# Plane MCP server with the fork's API-key auth patch: only a 401/403 from
# Plane invalidates a key; 429s, restarts and timeouts no longer drop clients.
ARG MCP_VERSION=v0.3.6
FROM makeplane/plane-mcp-server:${MCP_VERSION}
COPY plane_header_auth_provider.py /app/plane_mcp/auth/plane_header_auth_provider.py
