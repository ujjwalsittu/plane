# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.events import WorkspaceEventsAPIEndpoint, workspace_events_stream
from plane.api.views.agents import (
    AgentApprovalAPIEndpoint,
    AgentRunAPIEndpoint,
    AgentRunCancelAPIEndpoint,
    AgentRunDelegateAPIEndpoint,
    AgentRunFollowUpAPIEndpoint,
    AgentRunsAPIEndpoint,
    AgentRunStepsAPIEndpoint,
    WorkspaceAgentsAPIEndpoint,
)

_runs = "workspaces/<str:slug>/projects/<uuid:project_id>/work-items/<uuid:issue_id>/agent-runs"

urlpatterns = [
    path(
        "workspaces/<str:slug>/agents/",
        WorkspaceAgentsAPIEndpoint.as_view(http_method_names=["get"]),
        name="agents",
    ),
    path(
        "workspaces/<str:slug>/agents",
        WorkspaceAgentsAPIEndpoint.as_view(http_method_names=["get"]),
        name="agents-no-slash",
    ),
    path(
        "workspaces/<str:slug>/approvals/<uuid:approval_id>/",
        AgentApprovalAPIEndpoint.as_view(http_method_names=["get"]),
        name="agent-approval",
    ),
    path(
        "workspaces/<str:slug>/approvals/<uuid:approval_id>",
        AgentApprovalAPIEndpoint.as_view(http_method_names=["get"]),
        name="agent-approval-no-slash",
    ),
    path("workspaces/<str:slug>/events/", WorkspaceEventsAPIEndpoint.as_view(http_method_names=["get"]), name="events"),
    path(
        "workspaces/<str:slug>/events",
        WorkspaceEventsAPIEndpoint.as_view(http_method_names=["get"]),
        name="events-no-slash",
    ),
    path("workspaces/<str:slug>/events/stream/", workspace_events_stream, name="events-stream"),
    path("workspaces/<str:slug>/events/stream", workspace_events_stream, name="events-stream-no-slash"),
    *[
        route
        for suffix, tag in (("/", ""), ("", "-no-slash"))
        for route in (
            path(
                f"{_runs}{suffix}",
                AgentRunsAPIEndpoint.as_view(http_method_names=["get", "post"]),
                name=f"work-item-agent-runs{tag}",
            ),
            path(
                f"{_runs}/<uuid:run_id>{suffix}",
                AgentRunAPIEndpoint.as_view(http_method_names=["get", "patch"]),
                name=f"work-item-agent-run{tag}",
            ),
            path(
                f"{_runs}/<uuid:run_id>/steps{suffix}",
                AgentRunStepsAPIEndpoint.as_view(http_method_names=["post"]),
                name=f"work-item-agent-run-steps{tag}",
            ),
            path(
                f"{_runs}/delegate{suffix}",
                AgentRunDelegateAPIEndpoint.as_view(http_method_names=["post"]),
                name=f"work-item-agent-run-delegate{tag}",
            ),
            path(
                f"{_runs}/<uuid:run_id>/follow-up{suffix}",
                AgentRunFollowUpAPIEndpoint.as_view(http_method_names=["post"]),
                name=f"work-item-agent-run-follow-up{tag}",
            ),
            path(
                f"{_runs}/<uuid:run_id>/cancel{suffix}",
                AgentRunCancelAPIEndpoint.as_view(http_method_names=["post"]),
                name=f"work-item-agent-run-cancel{tag}",
            ),
        )
    ],
]
