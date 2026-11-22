# Plane MCP server with the fork's patches:
# - API-key auth: only a 401/403 from Plane invalidates a key; 429s, restarts and timeouts no longer drop clients.
# - Bearer auth: the workspace slug can come from the token (token_workspace_slug) instead of x-workspace-slug.
# - patch_mcp.py: project dates/priority/status, milestone description, work item completed_at, agent_run/approval/event and project_update tools.
ARG MCP_VERSION=v0.3.6
FROM makeplane/plane-mcp-server:${MCP_VERSION}
COPY plane_header_auth_provider.py /app/plane_mcp/auth/plane_header_auth_provider.py
COPY patch_mcp.py /tmp/patch_mcp.py
COPY agent_tools.py /tmp/agent_tools.py
COPY project_update_tools.py /tmp/project_update_tools.py
RUN python /tmp/patch_mcp.py && python -m compileall -q /app/plane_mcp /usr/local/lib/python3.11/site-packages/plane/models && rm /tmp/patch_mcp.py /tmp/agent_tools.py /tmp/project_update_tools.py
