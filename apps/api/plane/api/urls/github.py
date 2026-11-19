# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.github import WorkItemGitHubAPIEndpoint

_ROUTE = "workspaces/<str:slug>/projects/<uuid:project_id>/work-items/<uuid:issue_id>/github"

# The SDK calls routes without a trailing slash; serve both.
urlpatterns = [
    path(f"{_ROUTE}/", WorkItemGitHubAPIEndpoint.as_view(http_method_names=["get"]), name="work-item-github"),
    path(_ROUTE, WorkItemGitHubAPIEndpoint.as_view(http_method_names=["get"]), name="work-item-github-no-slash"),
]
