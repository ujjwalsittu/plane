# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.milestone import (
    MilestoneDetailAPIEndpoint,
    MilestoneListCreateAPIEndpoint,
    MilestoneWorkItemAPIEndpoint,
    ProjectFeatureAPIEndpoint,
    ProjectImportWorkItemTypesAPIEndpoint,
    ProjectWorkItemTypeDetailAPIEndpoint,
    ProjectWorkItemTypeListCreateAPIEndpoint,
    WorkspaceFeatureAPIEndpoint,
    ProjectOverviewAPIEndpoint,
    ProjectTagListCreateAPIEndpoint,
    WorkspaceWorkItemTypeDetailAPIEndpoint,
    WorkspaceWorkItemTypeListCreateAPIEndpoint,
)

_WORKSPACE = "workspaces/<str:slug>"
_PROJECT = f"{_WORKSPACE}/projects/<uuid:project_id>"

_routes = [
    (f"{_PROJECT}/milestones", MilestoneListCreateAPIEndpoint, ["get", "post"], "milestone-list"),
    (
        f"{_PROJECT}/milestones/<uuid:milestone_id>",
        MilestoneDetailAPIEndpoint,
        ["get", "patch", "delete"],
        "milestone-detail",
    ),
    (
        f"{_PROJECT}/milestones/<uuid:milestone_id>/work-items",
        MilestoneWorkItemAPIEndpoint,
        ["get", "post", "delete"],
        "milestone-work-items",
    ),
    (
        f"{_PROJECT}/work-item-types",
        ProjectWorkItemTypeListCreateAPIEndpoint,
        ["get", "post"],
        "project-work-item-type-list",
    ),
    (
        f"{_PROJECT}/work-item-types/<uuid:type_id>",
        ProjectWorkItemTypeDetailAPIEndpoint,
        ["get", "patch", "delete"],
        "project-work-item-type-detail",
    ),
    (
        f"{_PROJECT}/import-work-item-types",
        ProjectImportWorkItemTypesAPIEndpoint,
        ["post"],
        "project-import-work-item-types",
    ),
    (f"{_PROJECT}/features", ProjectFeatureAPIEndpoint, ["get", "patch"], "project-features"),
    (
        f"{_WORKSPACE}/work-item-types",
        WorkspaceWorkItemTypeListCreateAPIEndpoint,
        ["get", "post"],
        "workspace-work-item-type-list",
    ),
    (
        f"{_WORKSPACE}/work-item-types/<uuid:type_id>",
        WorkspaceWorkItemTypeDetailAPIEndpoint,
        ["get", "patch", "delete"],
        "workspace-work-item-type-detail",
    ),
    (f"{_WORKSPACE}/features", WorkspaceFeatureAPIEndpoint, ["get", "patch"], "workspace-features"),
    (f"{_PROJECT}/overview", ProjectOverviewAPIEndpoint, ["get", "patch"], "project-overview"),
    (f"{_WORKSPACE}/project-tags", ProjectTagListCreateAPIEndpoint, ["get", "post"], "project-tags"),
]

# The Plane SDK calls most of these without a trailing slash; a redirect would
# turn POST/DELETE bodies into GETs, so serve both forms.
urlpatterns = [
    path(f"{route}/", view.as_view(http_method_names=methods), name=name) for route, view, methods, name in _routes
] + [
    path(route, view.as_view(http_method_names=methods), name=f"{name}-no-slash")
    for route, view, methods, name in _routes
]
