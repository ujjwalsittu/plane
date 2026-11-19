# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.release import (
    ReleaseChangelogAPIEndpoint,
    ReleaseDetailAPIEndpoint,
    ReleaseItemLabelAPIEndpoint,
    ReleaseLabelDetailAPIEndpoint,
    ReleaseLabelListCreateAPIEndpoint,
    ReleaseListCreateAPIEndpoint,
    ReleaseTagDetailAPIEndpoint,
    ReleaseTagListCreateAPIEndpoint,
    ReleaseWorkItemAPIEndpoint,
)

_BASE = "workspaces/<str:slug>/releases"
_ONE = f"{_BASE}/<uuid:release_id>"
_routes = [
    # tags and labels come before <uuid:release_id> only for readability; the uuid converter
    # already keeps them apart.
    (f"{_BASE}/tags", ReleaseTagListCreateAPIEndpoint, ["get", "post"], "release-tags"),
    (f"{_BASE}/tags/<uuid:tag_id>", ReleaseTagDetailAPIEndpoint, ["get", "patch", "delete"], "release-tag"),
    (f"{_BASE}/labels", ReleaseLabelListCreateAPIEndpoint, ["get", "post"], "release-labels"),
    (f"{_BASE}/labels/<uuid:label_id>", ReleaseLabelDetailAPIEndpoint, ["get", "patch", "delete"], "release-label"),
    (_BASE, ReleaseListCreateAPIEndpoint, ["get", "post"], "releases"),
    (_ONE, ReleaseDetailAPIEndpoint, ["get", "patch", "delete"], "release"),
    (f"{_ONE}/changelog", ReleaseChangelogAPIEndpoint, ["get", "patch"], "release-changelog"),
    (f"{_ONE}/work-items", ReleaseWorkItemAPIEndpoint, ["get", "post", "delete"], "release-work-items"),
    (f"{_ONE}/labels", ReleaseItemLabelAPIEndpoint, ["get", "post", "delete"], "release-item-labels"),
]

# The SDK calls these with a trailing slash; serve both (a redirect would drop bodies).
urlpatterns = [
    path(f"{route}/", view.as_view(http_method_names=methods), name=name) for route, view, methods, name in _routes
] + [
    path(route, view.as_view(http_method_names=methods), name=f"{name}-no-slash")
    for route, view, methods, name in _routes
]
