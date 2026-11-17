# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views.project.overview import (
    ProjectOverviewEndpoint,
    ProjectTagDetailEndpoint,
    ProjectTagEndpoint,
)
from plane.app.views import (
    MilestoneIssueEndpoint,
    MilestoneViewSet,
    ProjectIssueTypeDetailEndpoint,
    ProjectIssueTypeEndpoint,
)

_PROJECT = "workspaces/<str:slug>/projects/<uuid:project_id>"

urlpatterns = [
    path(
        f"{_PROJECT}/milestones/",
        MilestoneViewSet.as_view({"get": "list", "post": "create"}),
        name="project-milestones",
    ),
    path(
        f"{_PROJECT}/milestones/<uuid:pk>/",
        MilestoneViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="project-milestone-detail",
    ),
    path(
        f"{_PROJECT}/milestones/<uuid:milestone_id>/milestone-issues/",
        MilestoneIssueEndpoint.as_view(),
        name="project-milestone-issues",
    ),
    path(
        f"{_PROJECT}/issue-types/",
        ProjectIssueTypeEndpoint.as_view(),
        name="project-issue-types",
    ),
    path(
        f"{_PROJECT}/issue-types/<uuid:pk>/",
        ProjectIssueTypeDetailEndpoint.as_view(),
        name="project-issue-type-detail",
    ),
    path(f"{_PROJECT}/overview/", ProjectOverviewEndpoint.as_view(), name="project-overview"),
    path("workspaces/<str:slug>/project-tags/", ProjectTagEndpoint.as_view(), name="project-tags"),
    path(
        "workspaces/<str:slug>/project-tags/<uuid:pk>/", ProjectTagDetailEndpoint.as_view(), name="project-tag-detail"
    ),
]
