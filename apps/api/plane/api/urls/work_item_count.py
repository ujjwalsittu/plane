# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.work_item_count import WorkItemCountAPIEndpoint

# The SDK calls this without a trailing slash; serve both.
urlpatterns = [
    path(
        "workspaces/<str:slug>/work-items/count/",
        WorkItemCountAPIEndpoint.as_view(http_method_names=["get"]),
        name="work-item-count",
    ),
    path(
        "workspaces/<str:slug>/work-items/count",
        WorkItemCountAPIEndpoint.as_view(http_method_names=["get"]),
        name="work-item-count-no-slash",
    ),
]
