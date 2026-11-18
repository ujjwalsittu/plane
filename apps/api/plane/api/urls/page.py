# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.inline_asset import InlineAssetUploadAPIEndpoint
from plane.api.views.workspace_page import (
    CollectionDetailAPIEndpoint,
    CollectionListCreateAPIEndpoint,
    CollectionMemberDetailAPIEndpoint,
    CollectionMemberListAddAPIEndpoint,
    CollectionPageDetailAPIEndpoint,
    CollectionPageListAddAPIEndpoint,
    CollectionPageSearchAPIEndpoint,
    WorkspacePageArchiveAPIEndpoint,
    WorkspacePageDetailAPIEndpoint,
    WorkspacePageListCreateAPIEndpoint,
)
from plane.api.views.page import (
    ProjectPageArchiveAPIEndpoint,
    ProjectPageDetailAPIEndpoint,
    ProjectPageListCreateAPIEndpoint,
    WorkItemPageDetailAPIEndpoint,
    WorkItemPageListCreateAPIEndpoint,
)

_WORKSPACE = "workspaces/<str:slug>"
_PROJECT = f"{_WORKSPACE}/projects/<uuid:project_id>"
_WORK_ITEM = f"{_PROJECT}/work-items/<uuid:issue_id>"

_routes = [
    (f"{_PROJECT}/pages", ProjectPageListCreateAPIEndpoint, ["get", "post"], "project-page-list"),
    (f"{_PROJECT}/assets/inline", InlineAssetUploadAPIEndpoint, ["post"], "project-inline-asset"),
    (f"{_PROJECT}/pages/<uuid:page_id>", ProjectPageDetailAPIEndpoint, ["get", "put", "delete"], "project-page-detail"),
    (
        f"{_PROJECT}/pages/<uuid:page_id>/archive",
        ProjectPageArchiveAPIEndpoint,
        ["post", "delete"],
        "project-page-archive",
    ),
    (f"{_WORKSPACE}/pages", WorkspacePageListCreateAPIEndpoint, ["get", "post"], "workspace-page-list"),
    (
        f"{_WORKSPACE}/pages/<uuid:page_id>",
        WorkspacePageDetailAPIEndpoint,
        ["get", "put", "patch", "delete"],
        "workspace-page-detail",
    ),
    (
        f"{_WORKSPACE}/pages/<uuid:page_id>/archive",
        WorkspacePageArchiveAPIEndpoint,
        ["post", "delete"],
        "workspace-page-archive",
    ),
    (f"{_WORKSPACE}/collections", CollectionListCreateAPIEndpoint, ["get", "post"], "collection-list"),
    (
        f"{_WORKSPACE}/collections/<uuid:collection_id>",
        CollectionDetailAPIEndpoint,
        ["get", "patch", "delete"],
        "collection-detail",
    ),
    (
        f"{_WORKSPACE}/collections/<uuid:collection_id>/pages",
        CollectionPageListAddAPIEndpoint,
        ["get", "post"],
        "collection-pages",
    ),
    (
        f"{_WORKSPACE}/collections/<uuid:collection_id>/pages-search",
        CollectionPageSearchAPIEndpoint,
        ["get"],
        "collection-pages-search",
    ),
    (
        f"{_WORKSPACE}/collections/<uuid:collection_id>/pages/<uuid:page_collection_id>",
        CollectionPageDetailAPIEndpoint,
        ["patch", "delete"],
        "collection-page",
    ),
    (
        f"{_WORKSPACE}/collections/<uuid:collection_id>/members",
        CollectionMemberListAddAPIEndpoint,
        ["get", "post"],
        "collection-members",
    ),
    (
        f"{_WORKSPACE}/collections/<uuid:collection_id>/members/<uuid:member_id>",
        CollectionMemberDetailAPIEndpoint,
        ["patch", "delete"],
        "collection-member",
    ),
    (f"{_WORK_ITEM}/pages", WorkItemPageListCreateAPIEndpoint, ["get", "post"], "work-item-page-list"),
    (
        f"{_WORK_ITEM}/pages/<uuid:work_item_page_id>",
        WorkItemPageDetailAPIEndpoint,
        ["get", "delete"],
        "work-item-page-detail",
    ),
]

# The Plane SDK calls these without a trailing slash; a redirect would turn
# POST/PUT/DELETE bodies into GETs, so serve both forms.
urlpatterns = [
    path(f"{route}/", view.as_view(http_method_names=methods), name=name) for route, view, methods, name in _routes
] + [
    path(route, view.as_view(http_method_names=methods), name=f"{name}-no-slash")
    for route, view, methods, name in _routes
]
