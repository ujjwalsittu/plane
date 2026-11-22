# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Agent tools for the Plane MCP server: runs, approvals and the event feed.

The Plane SDK has no client for these endpoints, so the tools call the external API directly with the
connection's own credentials (same header choice as the other tools). One tool per resource with an `action`
argument, like the upstream tools. `patch_mcp.py` copies this file into plane_mcp/tools/ and appends
RESOURCES to the registry.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, Literal

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token

from plane_mcp.client import get_plane_client_context
from plane_mcp.toolkit import Action, build_annotations, build_description, needs, one_of

TIMEOUT_SECONDS = 20
STEP_KINDS = ("message", "tool", "status", "pr", "commit", "error")
FINISH_STATUSES = ("succeeded", "failed", "cancelled")
RUN_STATUSES = ("running", "waiting", *FINISH_STATUSES)


def _auth_headers() -> dict[str, str]:
    """The auth header for this connection, chosen like upstream get_plane_client_context does.

    API-key connections (env, x-api-key header, or our bearer provider) send x-api-key; OAuth access tokens
    send Authorization: Bearer, as the Plane SDK's PlaneClient(access_token=...) does.
    """
    token = get_access_token()
    if token is None:
        return {"x-api-key": os.getenv("PLANE_API_KEY", "")}
    if token.claims.get("auth_method", "oauth") in ("api_key_env", "api_key_header"):
        return {"x-api-key": token.token}
    return {"Authorization": f"Bearer {token.token}"}


def _request(method: str, path: str, *, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> Any:
    """Call Plane's external API as the connection. Returns the decoded JSON, or an error string for the model."""
    base_url = (os.getenv("PLANE_INTERNAL_BASE_URL") or os.getenv("PLANE_BASE_URL", "https://api.plane.so")).rstrip("/")
    try:
        response = httpx.request(
            method,
            f"{base_url}/api/v1/{path}",
            params=params,
            json=body,
            headers=_auth_headers(),
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.RequestError as exc:
        return f"Error: could not reach Plane ({type(exc).__name__}). Try again shortly."
    if response.status_code >= 400:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text[:300]
        return f"Error: Plane returned {response.status_code}: {detail}"
    return response.json() if response.content else {}


def _run_path(slug: str, project_id: str, workitem_id: str, run_id: str = "") -> str:
    base = f"workspaces/{slug}/projects/{project_id}/work-items/{workitem_id}/agent-runs/"
    return f"{base}{run_id}/" if run_id else base


# --- agent_run ----------------------------------------------------------------------------------
RUN_ACTIONS = (
    Action("list", ("project_id", "workitem_id"), read=True),
    Action("retrieve", ("project_id", "workitem_id", "run_id"), read=True),
    Action(
        "start",
        ("project_id", "workitem_id"),
        ("title", "instructions", "external_url"),
        note="records a run of yours as running now; returns the run, keep its id",
    ),
    Action(
        "step",
        ("project_id", "workitem_id", "run_id", "kind"),
        ("text", "data", "external_event_id"),
        note="append a step to your own running run; a repeated external_event_id is ignored",
    ),
    Action(
        "finish",
        ("project_id", "workitem_id", "run_id", "status"),
        ("summary", "error", "cost_cents"),
        note="mark your own run succeeded, failed or cancelled; cost_cents is an integer number of US cents",
    ),
)
RUN_FOOTER = (
    f"kind is one of: {', '.join(STEP_KINDS)}. status is one of: {', '.join(FINISH_STATUSES)}. "
    "data is a JSON object (a JSON-encoded string is accepted). Only the agent that started a run can step or finish it."
)


def _register_agent_run(mcp: FastMCP) -> None:
    @mcp.tool(
        name="agent_run",
        description=build_description("Agent runs on a work item: report what you are doing.", RUN_ACTIONS, RUN_FOOTER),
        annotations=build_annotations("Agent runs", RUN_ACTIONS),
    )
    def agent_run(
        action: Literal["list", "retrieve", "start", "step", "finish"],
        project_id: str = "",
        workitem_id: str = "",
        run_id: str = "",
        title: str = "",
        instructions: str = "",
        external_url: str = "",
        kind: str = "",
        text: str = "",
        data: str = "",
        external_event_id: str = "",
        status: str = "",
        summary: str = "",
        error: str = "",
        cost_cents: int | None = None,
    ) -> Any:
        _, slug = get_plane_client_context()
        if err := needs(action, project_id=project_id, workitem_id=workitem_id):
            return err
        path = _run_path(slug, project_id, workitem_id)

        if action == "list":
            return _request("GET", path)

        if action == "start":
            body = {"title": title, "instructions": instructions, "external_url": external_url}
            return _request("POST", path, body={k: v for k, v in body.items() if v})

        if err := needs(action, run_id=run_id):
            return err
        if action == "retrieve":
            return _request("GET", _run_path(slug, project_id, workitem_id, run_id))

        if action == "step":
            if err := needs(action, kind=kind) or one_of("kind", kind, STEP_KINDS):
                return err
            body: dict[str, Any] = {"kind": kind}
            if text:
                body["text"] = text
            if data:
                parsed = _json_object(data)
                if parsed is None:
                    return "Error: data must be a JSON object."
                body["data"] = parsed
            if external_event_id:
                body["external_event_id"] = external_event_id
            return _request("POST", f"{_run_path(slug, project_id, workitem_id, run_id)}steps/", body=body)

        # finish
        if err := needs(action, status=status) or one_of("status", status, FINISH_STATUSES):
            return err
        body = {"status": status}
        if summary:
            body["summary"] = summary
        if error:
            body["error"] = error
        if cost_cents is not None:
            body["cost_cents"] = cost_cents
        return _request("PATCH", _run_path(slug, project_id, workitem_id, run_id), body=body)


def _json_object(value: str) -> dict[str, Any] | None:
    import json

    try:
        parsed = json.loads(value)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


# --- approval -----------------------------------------------------------------------------------
APPROVAL_ACTIONS = (Action("retrieve", ("approval_id",), read=True),)
APPROVAL_FOOTER = "Check whether a request of yours that waited for approval was approved, denied or is still pending."


def _register_approval(mcp: FastMCP) -> None:
    @mcp.tool(
        name="approval",
        description=build_description("Approval requests raised for an agent.", APPROVAL_ACTIONS, APPROVAL_FOOTER),
        annotations=build_annotations("Approvals", APPROVAL_ACTIONS),
    )
    def approval(action: Literal["retrieve"], approval_id: str = "") -> Any:
        _, slug = get_plane_client_context()
        if err := needs(action, approval_id=approval_id):
            return err
        return _request("GET", f"workspaces/{slug}/approvals/{approval_id}/")


# --- event --------------------------------------------------------------------------------------
EVENT_ACTIONS = (Action("list", (), ("after", "types", "project_id"), read=True),)
EVENT_FOOTER = (
    "Changes in the projects you are a member of, oldest first. after is the cursor: pass the previous "
    "response's next_after to get only newer events. types is a comma-separated list of event types."
)


def _register_event(mcp: FastMCP) -> None:
    @mcp.tool(
        name="event",
        description=build_description("The workspace event feed.", EVENT_ACTIONS, EVENT_FOOTER),
        annotations=build_annotations("Events", EVENT_ACTIONS),
    )
    def event(
        action: Literal["list"],
        after: int = 0,
        types: str = "",
        project_id: str = "",
    ) -> Any:
        _, slug = get_plane_client_context()
        params: dict[str, Any] = {}
        if after:
            params["after"] = after
        if types:
            params["types"] = types
        if project_id:
            params["project"] = project_id
        return _request("GET", f"workspaces/{slug}/events/", params=params or None)


def _resource(name: str, title: str, actions: tuple[Action, ...], register) -> SimpleNamespace:
    # The registry reads NAME, ACTIONS and LEGACY off each module and calls register(mcp).
    return SimpleNamespace(NAME=name, TITLE=title, ACTIONS=actions, LEGACY={}, register=register)


RESOURCES = (
    _resource("agent_run", "Agent runs", RUN_ACTIONS, _register_agent_run),
    _resource("approval", "Approvals", APPROVAL_ACTIONS, _register_approval),
    _resource("event", "Events", EVENT_ACTIONS, _register_event),
)
