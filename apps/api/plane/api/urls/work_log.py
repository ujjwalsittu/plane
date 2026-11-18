# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.work_log import (
    ProjectWorkLogSummaryAPIEndpoint,
    WorkLogDetailAPIEndpoint,
    WorkLogListCreateAPIEndpoint,
)

_PROJECT = "workspaces/<str:slug>/projects/<uuid:project_id>"
_routes = [
    (f"{_PROJECT}/work-items/<uuid:issue_id>/worklogs", WorkLogListCreateAPIEndpoint, ["get", "post"], "work-logs"),
    (
        f"{_PROJECT}/work-items/<uuid:issue_id>/worklogs/<uuid:work_log_id>",
        WorkLogDetailAPIEndpoint,
        ["patch", "delete"],
        "work-log",
    ),
    (f"{_PROJECT}/total-worklogs", ProjectWorkLogSummaryAPIEndpoint, ["get"], "work-log-summary"),
]

# The SDK calls these without a trailing slash; serve both (a redirect would drop bodies).
urlpatterns = [
    path(f"{route}/", view.as_view(http_method_names=methods), name=name) for route, view, methods, name in _routes
] + [
    path(route, view.as_view(http_method_names=methods), name=f"{name}-no-slash")
    for route, view, methods, name in _routes
]
