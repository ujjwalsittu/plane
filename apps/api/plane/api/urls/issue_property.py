# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.issue_property import (
    ProjectOptionDetailAPIEndpoint,
    ProjectOptionListCreateAPIEndpoint,
    ProjectPropertyDetailAPIEndpoint,
    ProjectPropertyListCreateAPIEndpoint,
    ProjectTypePropertyLinksAPIEndpoint,
    ProjectTypePropertyUnlinkAPIEndpoint,
    TypePropertyDetailAPIEndpoint,
    TypePropertyListCreateAPIEndpoint,
    WorkItemPropertyValueAPIEndpoint,
    WorkspaceOptionDetailAPIEndpoint,
    WorkspaceOptionListCreateAPIEndpoint,
    WorkspacePropertyDetailAPIEndpoint,
    WorkspacePropertyListCreateAPIEndpoint,
    WorkspaceTypePropertyLinksAPIEndpoint,
    WorkspaceTypePropertyUnlinkAPIEndpoint,
)

_WORKSPACE = "workspaces/<str:slug>"
_PROJECT = f"{_WORKSPACE}/projects/<uuid:project_id>"
_W_PROP = f"{_WORKSPACE}/work-item-properties/<uuid:property_id>"
_P_PROP = f"{_PROJECT}/work-item-properties/<uuid:property_id>"
_P_TYPE = f"{_PROJECT}/work-item-types/<uuid:type_id>"

_routes = [
    # workspace
    (f"{_WORKSPACE}/work-item-properties", WorkspacePropertyListCreateAPIEndpoint, ["get", "post"], "ws-props"),
    (_W_PROP, WorkspacePropertyDetailAPIEndpoint, ["get", "patch", "delete"], "ws-prop"),
    (f"{_W_PROP}/options", WorkspaceOptionListCreateAPIEndpoint, ["get", "post"], "ws-prop-options"),
    (
        f"{_W_PROP}/options/<uuid:option_id>",
        WorkspaceOptionDetailAPIEndpoint,
        ["get", "patch", "delete"],
        "ws-prop-option",
    ),
    (
        f"{_WORKSPACE}/work-item-types/<uuid:type_id>/properties",
        WorkspaceTypePropertyLinksAPIEndpoint,
        ["get", "post"],
        "ws-type-props",
    ),
    (
        f"{_WORKSPACE}/work-item-types/<uuid:type_id>/properties/<uuid:property_id>",
        WorkspaceTypePropertyUnlinkAPIEndpoint,
        ["delete"],
        "ws-type-prop",
    ),
    # project
    (f"{_PROJECT}/work-item-properties", ProjectPropertyListCreateAPIEndpoint, ["get", "post"], "p-props"),
    (_P_PROP, ProjectPropertyDetailAPIEndpoint, ["get", "patch", "delete"], "p-prop"),
    (f"{_P_PROP}/options", ProjectOptionListCreateAPIEndpoint, ["get", "post"], "p-prop-options"),
    (
        f"{_P_PROP}/options/<uuid:option_id>",
        ProjectOptionDetailAPIEndpoint,
        ["get", "patch", "delete"],
        "p-prop-option",
    ),
    (f"{_P_TYPE}/work-item-properties", TypePropertyListCreateAPIEndpoint, ["get", "post"], "type-props"),
    (
        f"{_P_TYPE}/work-item-properties/<uuid:work_item_property_id>",
        TypePropertyDetailAPIEndpoint,
        ["get", "patch", "delete"],
        "type-prop",
    ),
    (f"{_P_TYPE}/properties", ProjectTypePropertyLinksAPIEndpoint, ["post"], "p-type-links"),
    (f"{_P_TYPE}/properties/<uuid:property_id>", ProjectTypePropertyUnlinkAPIEndpoint, ["delete"], "p-type-link"),
    # values
    (
        f"{_PROJECT}/work-items/<uuid:issue_id>/work-item-properties/<uuid:property_id>/values",
        WorkItemPropertyValueAPIEndpoint,
        ["get", "post", "patch", "delete"],
        "work-item-prop-values",
    ),
]

# The Plane SDK calls some of these with and some without a trailing slash; serve both, since a
# redirect would turn POST/PATCH/DELETE bodies into GETs.
urlpatterns = [
    path(f"{route}/", view.as_view(http_method_names=methods), name=f"issue-property-{name}")
    for route, view, methods, name in _routes
] + [
    path(route, view.as_view(http_method_names=methods), name=f"issue-property-{name}-no-slash")
    for route, view, methods, name in _routes
]
