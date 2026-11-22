# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Project updates for the Plane MCP server: post and read a project's health (on track / at risk / off track).

The Plane SDK has no client for the fork's /projects/<id>/updates/ endpoint, so the tool calls it through
agent_tools._request, which authenticates as the connection (agent_tools._auth_headers). `patch_mcp.py` copies
this file next to agent_tools.py in plane_mcp/tools/ and appends RESOURCES to the registry.
"""

from __future__ import annotations

import html
from types import SimpleNamespace
from typing import Any, Literal

from fastmcp import FastMCP

from plane_mcp.client import get_plane_client_context
from plane_mcp.tools import agent_tools
from plane_mcp.toolkit import Action, build_annotations, build_description, needs, one_of

HEALTH = ("on_track", "at_risk", "off_track")

ACTIONS = (
    Action("list", ("project_id",), read=True),
    Action(
        "create",
        ("project_id", "health"),
        ("body_html", "body"),
        note="post an update on the project's health; pass body_html, or body as plain text",
    ),
)
FOOTER = (
    f"health is one of: {', '.join(HEALTH)}. list returns the latest 100 updates, newest first. "
    "body is plain text (blank lines start new paragraphs); body_html is HTML and is sanitized by Plane."
)


def _text_to_html(text: str) -> str:
    paragraphs = [part.strip() for part in text.replace("\r\n", "\n").split("\n\n") if part.strip()]
    return "".join(f"<p>{html.escape(part).replace(chr(10), '<br />')}</p>" for part in paragraphs)


def _register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="project_update",
        description=build_description("Project updates: report how a project is going.", ACTIONS, FOOTER),
        annotations=build_annotations("Project updates", ACTIONS),
    )
    def project_update(
        action: Literal["list", "create"],
        project_id: str = "",
        health: str = "",
        body_html: str = "",
        body: str = "",
    ) -> Any:
        _, slug = get_plane_client_context()
        if err := needs(action, project_id=project_id):
            return err
        path = f"workspaces/{slug}/projects/{project_id}/updates/"

        if action == "list":
            return agent_tools._request("GET", path)

        if err := needs(action, health=health) or one_of("health", health, HEALTH):
            return err
        if body_html and body:
            return "Error: pass body_html or body, not both."
        payload: dict[str, Any] = {"health": health}
        content = body_html or _text_to_html(body)
        if content:
            payload["body_html"] = content
        return agent_tools._request("POST", path, body=payload)


RESOURCES = (
    SimpleNamespace(NAME="project_update", TITLE="Project updates", ACTIONS=ACTIONS, LEGACY={}, register=_register),
)
