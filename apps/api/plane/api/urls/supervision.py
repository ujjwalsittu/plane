# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.supervision import (
    DecisionAnswerAPIEndpoint,
    DecisionRequestAPIEndpoint,
    DecisionWithdrawAPIEndpoint,
    ProjectUpdateAPIEndpoint,
    WorkItemWaitingAPIEndpoint,
)

_route = "workspaces/<str:slug>/projects/<uuid:project_id>/work-items/<uuid:issue_id>/waiting"
_methods = ["get", "put", "delete"]

# The SDK calls these with a trailing slash; serve both (a redirect would drop bodies).
urlpatterns = [
    path(f"{_route}/", WorkItemWaitingAPIEndpoint.as_view(http_method_names=_methods), name="work-item-waiting"),
    path(_route, WorkItemWaitingAPIEndpoint.as_view(http_method_names=_methods), name="work-item-waiting-no-slash"),
]

_decisions = "workspaces/<str:slug>/projects/<uuid:project_id>/work-items/<uuid:issue_id>/decisions"
for _suffix, _slash in (("/", True), ("", False)):
    _tag = "" if _slash else "-no-slash"
    urlpatterns += [
        path(
            f"{_decisions}{_suffix}",
            DecisionRequestAPIEndpoint.as_view(http_method_names=["get", "post"]),
            name=f"work-item-decisions{_tag}",
        ),
        path(
            f"{_decisions}/<uuid:decision_id>/answer{_suffix}",
            DecisionAnswerAPIEndpoint.as_view(http_method_names=["post"]),
            name=f"work-item-decision-answer{_tag}",
        ),
        path(
            f"{_decisions}/<uuid:decision_id>/withdraw{_suffix}",
            DecisionWithdrawAPIEndpoint.as_view(http_method_names=["post"]),
            name=f"work-item-decision-withdraw{_tag}",
        ),
    ]

_updates = "workspaces/<str:slug>/projects/<uuid:project_id>/updates"
urlpatterns += [
    path(f"{_updates}/", ProjectUpdateAPIEndpoint.as_view(http_method_names=["get", "post"]), name="project-updates"),
    path(
        _updates,
        ProjectUpdateAPIEndpoint.as_view(http_method_names=["get", "post"]),
        name="project-updates-no-slash",
    ),
]
