# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.teamspace import (
    TeamspaceDetailAPIEndpoint,
    TeamspaceListCreateAPIEndpoint,
    TeamspaceMemberAPIEndpoint,
    TeamspaceProjectAPIEndpoint,
    TeamspaceWorkItemAPIEndpoint,
    TeamspaceWorkloadAPIEndpoint,
)

_BASE = "workspaces/<str:slug>/teamspaces"
_ONE = f"{_BASE}/<uuid:team_id>"
_routes = [
    (_BASE, TeamspaceListCreateAPIEndpoint, ["get", "post"], "teamspaces"),
    (_ONE, TeamspaceDetailAPIEndpoint, ["get", "patch", "delete"], "teamspace"),
    (f"{_ONE}/members", TeamspaceMemberAPIEndpoint, ["get", "post", "delete"], "teamspace-members"),
    (f"{_ONE}/projects", TeamspaceProjectAPIEndpoint, ["get", "post", "delete"], "teamspace-projects"),
    (f"{_ONE}/work-items", TeamspaceWorkItemAPIEndpoint, ["get"], "teamspace-work-items"),
    (f"{_ONE}/workload", TeamspaceWorkloadAPIEndpoint, ["get"], "teamspace-workload"),
]

# The SDK calls these without a trailing slash; serve both (a redirect would drop bodies).
urlpatterns = [
    path(f"{route}/", view.as_view(http_method_names=methods), name=name) for route, view, methods, name in _routes
] + [
    path(route, view.as_view(http_method_names=methods), name=f"{name}-no-slash")
    for route, view, methods, name in _routes
]
