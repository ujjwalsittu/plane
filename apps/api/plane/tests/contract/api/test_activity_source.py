# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Work item activity records whether an API key (an agent) or the browser app made the change."""

from unittest.mock import patch

import pytest
from rest_framework import status

from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import Issue, IssueActivity, Project, ProjectMember, State
from plane.utils.supervision import SupervisionError, is_agent_activity

pytestmark = pytest.mark.contract


@pytest.fixture
def run_activity_inline(mock_celery):
    """Run the activity task synchronously; mock_celery keeps its notification follow-ups inert.

    patch.object removes the instance attribute again on exit (monkeypatch would leave the mock behind
    and break later tests that rely on eager Celery)."""
    with patch.object(issue_activity, "delay", lambda *args, **kwargs: issue_activity.run(*args, **kwargs)):
        yield


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Source Project", identifier="SRC", workspace=workspace)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    State.objects.create(name="Todo", project=project, workspace=workspace, group="backlog", default=True)
    return project


@pytest.mark.django_db
class TestActivitySource:
    def test_api_key_writes_are_marked_api(
        self, api_key_client, session_client, run_activity_inline, workspace, project
    ):
        api_url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/issues/"
        response = api_key_client.post(api_url, {"name": "From agent"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.data
        api_issue = Issue.objects.get(pk=response.data["id"])

        response = api_key_client.patch(f"{api_url}{api_issue.id}/", {"name": "Agent rename"}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data

        api_activities = IssueActivity.objects.filter(issue=api_issue)
        assert api_activities.count() >= 2
        assert set(api_activities.values_list("source", flat=True)) == {"api"}

        # Same client object, so switch it to session auth for the browser-app route
        api_key_client.credentials()
        app_url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/"
        response = session_client.post(app_url, {"name": "From person"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.data
        app_issue = Issue.objects.get(pk=response.data["id"])

        app_activities = IssueActivity.objects.filter(issue=app_issue)
        assert app_activities.exists()
        assert set(app_activities.values_list("source", flat=True)) == {"app"}

    def test_bot_actor_is_agent(self, workspace, project, create_bot_user, create_user):
        bot_activity = IssueActivity.objects.create(
            project=project, workspace=workspace, verb="created", actor=create_bot_user
        )
        person_activity = IssueActivity.objects.create(
            project=project, workspace=workspace, verb="created", actor=create_user
        )
        api_activity = IssueActivity.objects.create(
            project=project, workspace=workspace, verb="created", actor=create_user, source="api"
        )
        assert is_agent_activity(bot_activity) is True
        assert is_agent_activity(person_activity) is False
        assert is_agent_activity(api_activity) is True

    def test_supervision_error_shape(self):
        error = SupervisionError("nope", status_code=404, field="issue")
        assert (error.message, error.status_code, error.field) == ("nope", 404, "issue")
        assert SupervisionError("x").status_code == 400
