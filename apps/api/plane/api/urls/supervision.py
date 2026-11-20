# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.supervision import WorkItemWaitingAPIEndpoint

_route = "workspaces/<str:slug>/projects/<uuid:project_id>/work-items/<uuid:issue_id>/waiting"
_methods = ["get", "put", "delete"]

# The SDK calls these with a trailing slash; serve both (a redirect would drop bodies).
urlpatterns = [
    path(f"{_route}/", WorkItemWaitingAPIEndpoint.as_view(http_method_names=_methods), name="work-item-waiting"),
    path(_route, WorkItemWaitingAPIEndpoint.as_view(http_method_names=_methods), name="work-item-waiting-no-slash"),
]
