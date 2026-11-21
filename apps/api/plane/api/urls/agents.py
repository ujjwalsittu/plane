# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.agents import (
    AgentRunAPIEndpoint,
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
        )
    ],
]
