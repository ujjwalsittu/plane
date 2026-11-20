# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.template import (
    ProjectPageTemplateDetailAPIEndpoint,
    ProjectPageTemplateListCreateAPIEndpoint,
    ProjectWorkItemTemplateDetailAPIEndpoint,
    ProjectWorkItemTemplateListCreateAPIEndpoint,
    TemplateUseAPIEndpoint,
    WorkspacePageTemplateDetailAPIEndpoint,
    WorkspacePageTemplateListCreateAPIEndpoint,
    WorkspaceProjectTemplateDetailAPIEndpoint,
    WorkspaceProjectTemplateListCreateAPIEndpoint,
    WorkspaceWorkItemTemplateDetailAPIEndpoint,
    WorkspaceWorkItemTemplateListCreateAPIEndpoint,
)

_WS = "workspaces/<str:slug>"
_PROJECT = f"{_WS}/projects/<uuid:project_id>"
_LIST = ["get", "post"]
_ONE = ["get", "patch", "delete"]
_routes = [
    (f"{_WS}/workitems/templates", WorkspaceWorkItemTemplateListCreateAPIEndpoint, _LIST, "ws-workitem-templates"),
    (
        f"{_WS}/workitems/templates/<uuid:template_id>",
        WorkspaceWorkItemTemplateDetailAPIEndpoint,
        _ONE,
        "ws-workitem-template",
    ),
    (f"{_WS}/pages/templates", WorkspacePageTemplateListCreateAPIEndpoint, _LIST, "ws-page-templates"),
    (f"{_WS}/pages/templates/<uuid:template_id>", WorkspacePageTemplateDetailAPIEndpoint, _ONE, "ws-page-template"),
    (f"{_WS}/projects/templates", WorkspaceProjectTemplateListCreateAPIEndpoint, _LIST, "ws-project-templates"),
    (
        f"{_WS}/projects/templates/<uuid:template_id>",
        WorkspaceProjectTemplateDetailAPIEndpoint,
        _ONE,
        "ws-project-template",
    ),
    (
        f"{_PROJECT}/workitems/templates",
        ProjectWorkItemTemplateListCreateAPIEndpoint,
        _LIST,
        "project-workitem-templates",
    ),
    (
        f"{_PROJECT}/workitems/templates/<uuid:template_id>",
        ProjectWorkItemTemplateDetailAPIEndpoint,
        _ONE,
        "project-workitem-template",
    ),
    (f"{_PROJECT}/pages/templates", ProjectPageTemplateListCreateAPIEndpoint, _LIST, "project-page-templates"),
    (
        f"{_PROJECT}/pages/templates/<uuid:template_id>",
        ProjectPageTemplateDetailAPIEndpoint,
        _ONE,
        "project-page-template",
    ),
    (f"{_WS}/templates/<uuid:template_id>/use", TemplateUseAPIEndpoint, ["post"], "template-use"),
]

# The SDK calls these with and without a trailing slash; serve both (a redirect would drop bodies).
urlpatterns = [
    path(f"{route}/", view.as_view(http_method_names=methods), name=name) for route, view, methods, name in _routes
] + [
    path(route, view.as_view(http_method_names=methods), name=f"{name}-no-slash")
    for route, view, methods, name in _routes
]
