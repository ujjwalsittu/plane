# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.work_item_relation import (
    WorkItemCustomRelationDetailAPIEndpoint,
    WorkItemCustomRelationListCreateAPIEndpoint,
    WorkItemDependencyDetailAPIEndpoint,
    WorkItemDependencyListCreateAPIEndpoint,
    WorkItemRelationDefinitionDetailAPIEndpoint,
    WorkItemRelationDefinitionListAPIEndpoint,
)

_WORK_ITEM = "workspaces/<str:slug>/projects/<uuid:project_id>/work-items/<uuid:issue_id>"

urlpatterns = [
    path(
        f"{_WORK_ITEM}/dependencies/",
        WorkItemDependencyListCreateAPIEndpoint.as_view(http_method_names=["get", "post"]),
        name="work-item-dependency-list",
    ),
    path(
        f"{_WORK_ITEM}/dependencies/<uuid:related_issue_id>/",
        WorkItemDependencyDetailAPIEndpoint.as_view(http_method_names=["delete"]),
        name="work-item-dependency-detail",
    ),
    path(
        f"{_WORK_ITEM}/work-item-relations/",
        WorkItemCustomRelationListCreateAPIEndpoint.as_view(http_method_names=["get", "post"]),
        name="work-item-custom-relation-list",
    ),
    path(
        f"{_WORK_ITEM}/work-item-relations/<uuid:related_issue_id>/",
        WorkItemCustomRelationDetailAPIEndpoint.as_view(http_method_names=["delete"]),
        name="work-item-custom-relation-detail",
    ),
    path(
        "workspaces/<str:slug>/work-item-relation-definitions/",
        WorkItemRelationDefinitionListAPIEndpoint.as_view(http_method_names=["get", "post"]),
        name="work-item-relation-definition-list",
    ),
    path(
        "workspaces/<str:slug>/work-item-relation-definitions/<uuid:definition_id>/",
        WorkItemRelationDefinitionDetailAPIEndpoint.as_view(http_method_names=["get", "patch", "delete"]),
        name="work-item-relation-definition-detail",
    ),
]
