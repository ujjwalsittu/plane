# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.agents import WorkspaceAgentsAPIEndpoint

urlpatterns = [
    path(
        "workspaces/<str:slug>/agents/",
        WorkspaceAgentsAPIEndpoint.as_view(http_method_names=["get"]),
        name="agents",
    ),
    path(
        "workspaces/<str:slug>/agents",
        WorkspaceAgentsAPIEndpoint.as_view(http_method_names=["get"]),
        name="agents-no-slash",
    ),
]
