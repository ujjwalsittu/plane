# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.estimate import (
    ProjectEstimateAPIEndpoint,
    EstimatePointListCreateAPIEndpoint,
    EstimatePointDetailAPIEndpoint,
)

_ESTIMATES = "workspaces/<str:slug>/projects/<uuid:project_id>/estimates"

_routes = [
    (
        _ESTIMATES,
        ProjectEstimateAPIEndpoint.as_view(http_method_names=["get", "post", "patch", "delete"]),
        "project-estimate",
    ),
    (
        f"{_ESTIMATES}/<uuid:estimate_id>/estimate-points",
        EstimatePointListCreateAPIEndpoint.as_view(http_method_names=["get", "post"]),
        "estimate-point-list-create",
    ),
    (
        f"{_ESTIMATES}/<uuid:estimate_id>/estimate-points/<uuid:estimate_point_id>",
        EstimatePointDetailAPIEndpoint.as_view(http_method_names=["patch", "delete"]),
        "estimate-point-detail",
    ),
]

# The Plane SDK calls these routes without a trailing slash. APPEND_SLASH
# would answer with a redirect, which turns a POST into a GET, so serve both.
urlpatterns = [path(f"{route}/", view, name=name) for route, view, name in _routes] + [
    path(route, view, name=f"{name}-no-slash") for route, view, name in _routes
]
