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
from plane.app.views.page.workspace_page import (
    WikiCollectionDetailEndpoint,
    WikiCollectionListEndpoint,
    WikiCollectionPageEndpoint,
    WikiCollectionPagesEndpoint,
    WikiPageArchiveEndpoint,
    WikiPageDetailEndpoint,
    WikiPageListEndpoint,
)
from plane.app.views.slack_interactivity import SlackInteractivityView
from plane.app.views.github_app import (
    GitHubAutomationDetailEndpoint,
    GitHubAutomationListEndpoint,
    GitHubInstallationDetailEndpoint,
    GitHubInstallationListEndpoint,
    GitHubInstallationRepositoriesEndpoint,
    GitHubInstallUrlEndpoint,
    GitHubIntegrationEndpoint,
    GitHubRepositoryLinkDetailEndpoint,
    GitHubRepositoryLinkListEndpoint,
    GitHubRepositoryLinkSyncEndpoint,
    GitHubSetupCallbackView,
    GitHubUserMappingEndpoint,
    GitHubWebhookView,
    IssueGitHubEndpoint,
)
from plane.app.views.initiative import (
    InitiativeEndpoint,
    InitiativeListEndpoint,
    InitiativeProjectEndpoint,
    InitiativeWorkItemEndpoint,
)
from plane.app.views import agents as agent_views
from plane.app.views import release as release_views
from plane.app.views import supervision as supervision_views
from plane.app.views import template as template_views
from plane.app.views import teamspace as teamspace_views
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
    path("workspaces/<str:slug>/wiki/pages/", WikiPageListEndpoint.as_view(), name="wiki-pages"),
    path("workspaces/<str:slug>/wiki/pages/<uuid:page_id>/", WikiPageDetailEndpoint.as_view(), name="wiki-page"),
    path(
        "workspaces/<str:slug>/wiki/pages/<uuid:page_id>/archive/",
        WikiPageArchiveEndpoint.as_view(),
        name="wiki-page-archive",
    ),
    path("workspaces/<str:slug>/wiki/collections/", WikiCollectionListEndpoint.as_view(), name="wiki-collections"),
    path(
        "workspaces/<str:slug>/wiki/collections/<uuid:collection_id>/",
        WikiCollectionDetailEndpoint.as_view(),
        name="wiki-collection",
    ),
    path(
        "workspaces/<str:slug>/wiki/collections/<uuid:collection_id>/pages/",
        WikiCollectionPagesEndpoint.as_view(),
        name="wiki-collection-pages",
    ),
    path(
        "workspaces/<str:slug>/wiki/collections/<uuid:collection_id>/pages/<uuid:page_collection_id>/",
        WikiCollectionPageEndpoint.as_view(),
        name="wiki-collection-page",
    ),
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
    # Slack interactivity: signed by Slack, no session
    path("slack/interactivity/", SlackInteractivityView.as_view(), name="slack-interactivity"),
    # GitHub App integration
    path("integrations/github/webhook/", GitHubWebhookView.as_view(), name="github-webhook"),
    path("integrations/github/setup/", GitHubSetupCallbackView.as_view(), name="github-setup"),
    path("workspaces/<str:slug>/github/", GitHubIntegrationEndpoint.as_view(), name="github-integration"),
    path("workspaces/<str:slug>/github/install-url/", GitHubInstallUrlEndpoint.as_view(), name="github-install-url"),
    path(
        "workspaces/<str:slug>/github/installations/",
        GitHubInstallationListEndpoint.as_view(),
        name="github-installations",
    ),
    path(
        "workspaces/<str:slug>/github/installations/<uuid:pk>/",
        GitHubInstallationDetailEndpoint.as_view(),
        name="github-installation",
    ),
    path(
        "workspaces/<str:slug>/github/installations/<uuid:pk>/repositories/",
        GitHubInstallationRepositoriesEndpoint.as_view(),
        name="github-installation-repositories",
    ),
    path("workspaces/<str:slug>/github/links/", GitHubRepositoryLinkListEndpoint.as_view(), name="github-links"),
    path(
        "workspaces/<str:slug>/github/automations/", GitHubAutomationListEndpoint.as_view(), name="github-automations"
    ),
    path("workspaces/<str:slug>/github/people/", GitHubUserMappingEndpoint.as_view(), name="github-people"),
    path(
        f"{_PROJECT}/github/automation/",
        GitHubAutomationDetailEndpoint.as_view(),
        name="github-automation",
    ),
    path(
        "workspaces/<str:slug>/github/links/<uuid:pk>/sync/",
        GitHubRepositoryLinkSyncEndpoint.as_view(),
        name="github-link-sync",
    ),
    path(f"{_PROJECT}/issues/<uuid:issue_id>/github/", IssueGitHubEndpoint.as_view(), name="issue-github"),
    path(
        "workspaces/<str:slug>/github/links/<uuid:pk>/",
        GitHubRepositoryLinkDetailEndpoint.as_view(),
        name="github-link",
    ),
    # Initiatives
    path("workspaces/<str:slug>/initiatives/", InitiativeListEndpoint.as_view(), name="app-initiatives"),
    path(
        "workspaces/<str:slug>/initiatives/<uuid:initiative_id>/",
        InitiativeEndpoint.as_view(),
        name="app-initiative",
    ),
    path(
        "workspaces/<str:slug>/initiatives/<uuid:initiative_id>/projects/",
        InitiativeProjectEndpoint.as_view(),
        name="app-initiative-projects",
    ),
    path(
        "workspaces/<str:slug>/initiatives/<uuid:initiative_id>/work-items/",
        InitiativeWorkItemEndpoint.as_view(),
        name="app-initiative-work-items",
    ),
    # Releases
    path(
        "workspaces/<str:slug>/releases/tags/", release_views.ReleaseTagListEndpoint.as_view(), name="app-release-tags"
    ),
    path(
        "workspaces/<str:slug>/releases/tags/<uuid:tag_id>/",
        release_views.ReleaseTagEndpoint.as_view(),
        name="app-release-tag",
    ),
    path(
        "workspaces/<str:slug>/releases/labels/",
        release_views.ReleaseLabelListEndpoint.as_view(),
        name="app-release-labels",
    ),
    path(
        "workspaces/<str:slug>/releases/labels/<uuid:label_id>/",
        release_views.ReleaseLabelEndpoint.as_view(),
        name="app-release-label",
    ),
    path("workspaces/<str:slug>/releases/", release_views.ReleaseListEndpoint.as_view(), name="app-releases"),
    path(
        "workspaces/<str:slug>/releases/<uuid:release_id>/",
        release_views.ReleaseEndpoint.as_view(),
        name="app-release",
    ),
    path(
        "workspaces/<str:slug>/releases/<uuid:release_id>/changelog/",
        release_views.ReleaseChangelogEndpoint.as_view(),
        name="app-release-changelog",
    ),
    path(
        "workspaces/<str:slug>/releases/<uuid:release_id>/work-items/",
        release_views.ReleaseWorkItemEndpoint.as_view(),
        name="app-release-work-items",
    ),
    path(
        "workspaces/<str:slug>/releases/<uuid:release_id>/labels/",
        release_views.ReleaseItemLabelEndpoint.as_view(),
        name="app-release-item-labels",
    ),
    # Templates
    path("workspaces/<str:slug>/templates/", template_views.TemplateListEndpoint.as_view(), name="app-templates"),
    path(
        "workspaces/<str:slug>/templates/<uuid:template_id>/",
        template_views.TemplateEndpoint.as_view(),
        name="app-template",
    ),
    path(
        "workspaces/<str:slug>/templates/<uuid:template_id>/use/",
        template_views.TemplateUseEndpoint.as_view(),
        name="app-template-use",
    ),
    # Teams
    path(
        "workspaces/<str:slug>/teamspaces/",
        teamspace_views.TeamspaceListEndpoint.as_view(),
        name="app-teamspaces",
    ),
    path(
        "workspaces/<str:slug>/teamspaces/<uuid:team_id>/",
        teamspace_views.TeamspaceEndpoint.as_view(),
        name="app-teamspace",
    ),
    path(
        "workspaces/<str:slug>/teamspaces/<uuid:team_id>/members/",
        teamspace_views.TeamspaceMemberEndpoint.as_view(),
        name="app-teamspace-members",
    ),
    path(
        "workspaces/<str:slug>/teamspaces/<uuid:team_id>/projects/",
        teamspace_views.TeamspaceProjectEndpoint.as_view(),
        name="app-teamspace-projects",
    ),
    path(
        "workspaces/<str:slug>/teamspaces/<uuid:team_id>/work-items/",
        teamspace_views.TeamspaceWorkItemEndpoint.as_view(),
        name="app-teamspace-work-items",
    ),
    path(
        "workspaces/<str:slug>/teamspaces/<uuid:team_id>/workload/",
        teamspace_views.TeamspaceWorkloadEndpoint.as_view(),
        name="app-teamspace-workload",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/issues/<uuid:issue_id>/waiting/",
        supervision_views.WorkItemWaitingEndpoint.as_view(),
        name="app-work-item-waiting",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/issues/<uuid:issue_id>/decisions/",
        supervision_views.DecisionRequestEndpoint.as_view(http_method_names=["get", "post"]),
        name="app-work-item-decisions",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/issues/<uuid:issue_id>/decisions/<uuid:decision_id>/answer/",
        supervision_views.DecisionAnswerEndpoint.as_view(http_method_names=["post"]),
        name="app-work-item-decision-answer",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/issues/<uuid:issue_id>/decisions/<uuid:decision_id>/withdraw/",
        supervision_views.DecisionWithdrawEndpoint.as_view(http_method_names=["post"]),
        name="app-work-item-decision-withdraw",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/updates/",
        supervision_views.ProjectUpdateEndpoint.as_view(http_method_names=["get", "post"]),
        name="app-project-updates",
    ),
    path(
        "workspaces/<str:slug>/decisions/",
        supervision_views.MyDecisionsEndpoint.as_view(http_method_names=["get"]),
        name="app-my-decisions",
    ),
    path(
        "workspaces/<str:slug>/brief/",
        supervision_views.BriefEndpoint.as_view(http_method_names=["get"]),
        name="app-brief",
    ),
    path(
        "workspaces/<str:slug>/brief/summary/",
        supervision_views.BriefSummaryEndpoint.as_view(http_method_names=["get"]),
        name="app-brief-summary",
    ),
    path(
        "workspaces/<str:slug>/brief/seen/",
        supervision_views.BriefSeenEndpoint.as_view(http_method_names=["post"]),
        name="app-brief-seen",
    ),
    path(
        "workspaces/<str:slug>/slack/",
        supervision_views.SlackConnectionEndpoint.as_view(http_method_names=["get", "put", "delete"]),
        name="app-slack-connection",
    ),
    path(
        "workspaces/<str:slug>/agents/",
        agent_views.AgentsEndpoint.as_view(http_method_names=["get", "post"]),
        name="app-agents",
    ),
    path(
        "workspaces/<str:slug>/agents/<uuid:agent_id>/",
        agent_views.AgentEndpoint.as_view(http_method_names=["get", "patch", "delete"]),
        name="app-agent",
    ),
    path(
        "workspaces/<str:slug>/agents/<uuid:agent_id>/rotate-token/",
        agent_views.AgentRotateTokenEndpoint.as_view(http_method_names=["post"]),
        name="app-agent-rotate-token",
    ),
    path(
        "workspaces/<str:slug>/ai-settings/",
        agent_views.AISettingsEndpoint.as_view(http_method_names=["get", "put", "delete"]),
        name="app-ai-settings",
    ),
]
