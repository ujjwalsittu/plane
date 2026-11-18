# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views.issue.relation_definition import (
    IssueCustomRelationDetailEndpoint,
    IssueCustomRelationListEndpoint,
    RelationDefinitionDetailEndpoint,
    RelationDefinitionListEndpoint,
)
from plane.app.views.issue.work_log import (
    IssueWorkLogDetailEndpoint,
    IssueWorkLogEndpoint,
    ProjectWorkLogSummaryEndpoint,
)
from plane.app.views.issue.page_link import IssuePageLinkDetailEndpoint, IssuePageLinkEndpoint
from plane.app.views.issue.property import (
    IssuePropertyDetailEndpoint,
    IssuePropertyEndpoint,
    IssuePropertyOptionDetailEndpoint,
    IssuePropertyOptionEndpoint,
    IssuePropertyValuesEndpoint,
)

from plane.app.views.project.overview import (
    ProjectOverviewEndpoint,
    ProjectTagDetailEndpoint,
    ProjectTagEndpoint,
)
from plane.app.views import (
    MilestoneIssueEndpoint,
    MilestoneViewSet,
    ProjectIssueTypeDetailEndpoint,
    ProjectIssueTypeEndpoint,
)

_PROJECT = "workspaces/<str:slug>/projects/<uuid:project_id>"

urlpatterns = [
    path(
        f"{_PROJECT}/milestones/",
        MilestoneViewSet.as_view({"get": "list", "post": "create"}),
        name="project-milestones",
    ),
    path(
        f"{_PROJECT}/milestones/<uuid:pk>/",
        MilestoneViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="project-milestone-detail",
    ),
    path(
        f"{_PROJECT}/milestones/<uuid:milestone_id>/milestone-issues/",
        MilestoneIssueEndpoint.as_view(),
        name="project-milestone-issues",
    ),
    path(
        f"{_PROJECT}/issue-types/",
        ProjectIssueTypeEndpoint.as_view(),
        name="project-issue-types",
    ),
    path(
        f"{_PROJECT}/issue-types/<uuid:pk>/",
        ProjectIssueTypeDetailEndpoint.as_view(),
        name="project-issue-type-detail",
    ),
    path(f"{_PROJECT}/overview/", ProjectOverviewEndpoint.as_view(), name="project-overview"),
    path(f"{_PROJECT}/issues/<uuid:issue_id>/pages/", IssuePageLinkEndpoint.as_view(), name="issue-page-links"),
    path(
        "workspaces/<str:slug>/relation-definitions/",
        RelationDefinitionListEndpoint.as_view(),
        name="relation-definitions",
    ),
    path(
        "workspaces/<str:slug>/relation-definitions/<uuid:definition_id>/",
        RelationDefinitionDetailEndpoint.as_view(),
        name="relation-definition",
    ),
    path(
        f"{_PROJECT}/issues/<uuid:issue_id>/custom-relations/",
        IssueCustomRelationListEndpoint.as_view(),
        name="issue-custom-relations",
    ),
    path(
        f"{_PROJECT}/issues/<uuid:issue_id>/custom-relations/<uuid:related_issue_id>/",
        IssueCustomRelationDetailEndpoint.as_view(),
        name="issue-custom-relation",
    ),
    path(f"{_PROJECT}/issues/<uuid:issue_id>/work-logs/", IssueWorkLogEndpoint.as_view(), name="issue-work-logs"),
    path(
        f"{_PROJECT}/issues/<uuid:issue_id>/work-logs/<uuid:work_log_id>/",
        IssueWorkLogDetailEndpoint.as_view(),
        name="issue-work-log",
    ),
    path(f"{_PROJECT}/work-log-summary/", ProjectWorkLogSummaryEndpoint.as_view(), name="project-work-log-summary"),
    path(f"{_PROJECT}/issue-properties/", IssuePropertyEndpoint.as_view(), name="issue-properties"),
    path(f"{_PROJECT}/issue-properties/<uuid:pk>/", IssuePropertyDetailEndpoint.as_view(), name="issue-property"),
    path(
        f"{_PROJECT}/issue-properties/<uuid:property_id>/options/",
        IssuePropertyOptionEndpoint.as_view(),
        name="issue-property-options",
    ),
    path(
        f"{_PROJECT}/issue-properties/<uuid:property_id>/options/<uuid:pk>/",
        IssuePropertyOptionDetailEndpoint.as_view(),
        name="issue-property-option",
    ),
    path(
        f"{_PROJECT}/issues/<uuid:issue_id>/property-values/",
        IssuePropertyValuesEndpoint.as_view(),
        name="issue-property-values",
    ),
    path(
        f"{_PROJECT}/issues/<uuid:issue_id>/pages/<uuid:pk>/",
        IssuePageLinkDetailEndpoint.as_view(),
        name="issue-page-link-detail",
    ),
    path("workspaces/<str:slug>/project-tags/", ProjectTagEndpoint.as_view(), name="project-tags"),
    path(
        "workspaces/<str:slug>/project-tags/<uuid:pk>/", ProjectTagDetailEndpoint.as_view(), name="project-tag-detail"
    ),
]
