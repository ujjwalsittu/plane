# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Agents as workspace members: a bot user with its own token, limited to the projects it was given."""

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import (
    APIToken,
    Issue,
    IssueActivity,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceAgent,
    WorkspaceMember,
)
from plane.utils.supervision import is_agent_activity

pytestmark = pytest.mark.contract


def _project(workspace, user, name, identifier):
    project = Project.objects.create(name=name, identifier=identifier, workspace=workspace, created_by=user)
    ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=20)
    State.objects.create(name="Todo", project=project, workspace=workspace, group="backlog", default=True)
    return project


@pytest.fixture
def alpha(workspace, create_user):
    return _project(workspace, create_user, "Alpha", "ALP")


@pytest.fixture
def beta(workspace, create_user):
    return _project(workspace, create_user, "Beta", "BET")


def _url(workspace, suffix=""):
    return f"/api/workspaces/{workspace.slug}/agents/{suffix}"


def _create(client, workspace, owner_user, projects, **extra):
    body = {"name": "Triage bot", "owner": str(owner_user.id), "project_ids": [str(p.id) for p in projects], **extra}
    return client.post(_url(workspace), body, format="json")


@pytest.mark.django_db
def test_admin_creates_agent_with_token_shown_once(session_client, workspace, create_user, alpha, beta):
    response = _create(session_client, workspace, create_user, [alpha], avatar_url="https://example.com/a.png")
    assert response.status_code == 201, response.data
    token = response.data["token"]
    assert token.startswith("plane_api_")
    assert response.data["project_ids"] == [str(alpha.id)]
    assert response.data["permission"] == "contribute"
    assert response.data["approval_actions"] == ["change_dates", "delete"]
    assert response.data["run_budget_cents"] == 500
    assert response.data["avatar_url"] == "https://example.com/a.png"
    assert response.data["owner"]["id"] == str(create_user.id)

    agent = WorkspaceAgent.objects.get(pk=response.data["id"])
    assert agent.user.is_bot and agent.user.bot_type == "agent"
    assert agent.user.email.endswith("@agents.invalid")
    assert WorkspaceMember.objects.get(workspace=workspace, member=agent.user).role == 15
    memberships = ProjectMember.objects.filter(member=agent.user, is_active=True)
    assert [m.project_id for m in memberships] == [alpha.id]
    assert memberships[0].role == 15
    api_token = APIToken.objects.get(user=agent.user)
    assert api_token.token == token and api_token.user_type == 1 and api_token.label == "agent:Triage bot"

    listing = session_client.get(_url(workspace))
    assert listing.status_code == 200
    assert [row["id"] for row in listing.data] == [str(agent.id)]
    detail = session_client.get(_url(workspace, f"{agent.id}/"))
    assert detail.status_code == 200
    assert "token" not in listing.data[0] and "token" not in detail.data
    assert token not in str(listing.data) + str(detail.data)


@pytest.mark.django_db
def test_agent_writes_are_credited_to_agent(session_client, api_client, mock_celery, workspace, create_user, alpha):
    token = _create(session_client, workspace, create_user, [alpha]).data["token"]
    agent_client = APIClient()
    agent_client.credentials(HTTP_X_API_KEY=token)
    with patch.object(issue_activity, "delay", lambda *a, **k: issue_activity.run(*a, **k)):
        response = agent_client.post(
            f"/api/v1/workspaces/{workspace.slug}/projects/{alpha.id}/issues/", {"name": "By agent"}, format="json"
        )
    assert response.status_code == 201, response.data
    activity = IssueActivity.objects.filter(issue_id=response.data["id"]).first()
    bot = User.objects.get(workspace_agent__workspace=workspace)
    assert activity.actor_id == bot.id
    assert activity.source == "api"
    assert is_agent_activity(activity)


@pytest.mark.django_db
def test_agent_only_reaches_its_projects(session_client, workspace, create_user, alpha, beta):
    token = _create(session_client, workspace, create_user, [alpha]).data["token"]
    hidden = Issue.objects.create(name="Hidden", project=beta, workspace=workspace)
    agent_client = APIClient()
    agent_client.credentials(HTTP_X_API_KEY=token)
    response = agent_client.get(f"/api/v1/workspaces/{workspace.slug}/projects/{beta.id}/issues/{hidden.id}/")
    # The project permission class answers 403 to a non-member; either way the agent is kept out
    assert response.status_code in (403, 404)
    visible = Issue.objects.create(name="Visible", project=alpha, workspace=workspace)
    response = agent_client.get(f"/api/v1/workspaces/{workspace.slug}/projects/{alpha.id}/issues/{visible.id}/")
    assert response.status_code == 200

    # Agents can see each other through the read-only external list
    listing = agent_client.get(f"/api/v1/workspaces/{workspace.slug}/agents/")
    assert listing.status_code == 200 and len(listing.data) == 1


@pytest.mark.django_db
def test_non_admin_cannot_manage_agents(session_client, workspace, create_user, alpha):
    agent_id = _create(session_client, workspace, create_user, [alpha]).data["id"]
    member = User.objects.create(email="member@plane.so", username="member")
    WorkspaceMember.objects.create(workspace=workspace, member=member, role=15)
    client = APIClient()
    client.force_authenticate(user=member)
    assert _create(client, workspace, create_user, [alpha], name="Other").status_code == 403
    assert client.patch(_url(workspace, f"{agent_id}/"), {"name": "X"}, format="json").status_code == 403
    assert client.delete(_url(workspace, f"{agent_id}/")).status_code == 403
    assert client.post(_url(workspace, f"{agent_id}/rotate-token/")).status_code == 403
    assert client.get(_url(workspace)).status_code == 200


@pytest.mark.django_db
def test_deactivate_revokes_token(session_client, workspace, create_user, alpha):
    created = _create(session_client, workspace, create_user, [alpha])
    token, agent_id = created.data["token"], created.data["id"]
    agent_client = APIClient()
    agent_client.credentials(HTTP_X_API_KEY=token)
    url = f"/api/v1/workspaces/{workspace.slug}/projects/{alpha.id}/issues/"
    assert agent_client.get(url).status_code == 200

    assert session_client.delete(_url(workspace, f"{agent_id}/")).status_code == 204
    assert agent_client.get(url).status_code in (401, 403)
    # An endpoint that does not depend on project membership is rejected too: the token itself is revoked
    assert agent_client.get(f"/api/v1/workspaces/{workspace.slug}/agents/").status_code in (401, 403)
    agent = WorkspaceAgent.objects.get(pk=agent_id)
    assert not APIToken.objects.filter(user=agent.user, is_active=True).exists()
    assert not agent.is_active and not agent.user.is_active
    assert not ProjectMember.objects.filter(member=agent.user, is_active=True).exists()


@pytest.mark.django_db
def test_deactivate_calls_hook(session_client, workspace, create_user, alpha):
    agent_id = _create(session_client, workspace, create_user, [alpha]).data["id"]
    with patch("plane.utils.agents.on_agent_deactivated") as hook:
        session_client.delete(_url(workspace, f"{agent_id}/"))
    hook.assert_called_once()
    assert str(hook.call_args.args[0].id) == agent_id


@pytest.mark.django_db
def test_rotate_token_replaces_old_token(session_client, workspace, create_user, alpha):
    created = _create(session_client, workspace, create_user, [alpha])
    rotated = session_client.post(_url(workspace, f"{created.data['id']}/rotate-token/"))
    assert rotated.status_code == 200 and rotated.data["token"] != created.data["token"]
    client = APIClient()
    url = f"/api/v1/workspaces/{workspace.slug}/projects/{alpha.id}/issues/"
    client.credentials(HTTP_X_API_KEY=created.data["token"])
    assert client.get(url).status_code in (401, 403)
    client.credentials(HTTP_X_API_KEY=rotated.data["token"])
    assert client.get(url).status_code == 200


@pytest.mark.django_db
def test_update_syncs_projects_and_validates(session_client, workspace, create_user, alpha, beta):
    agent_id = _create(session_client, workspace, create_user, [alpha]).data["id"]
    url = _url(workspace, f"{agent_id}/")
    response = session_client.patch(
        url,
        {"project_ids": [str(beta.id)], "permission": "read", "approval_actions": ["delete"], "run_budget_cents": 900},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["project_ids"] == [str(beta.id)]
    assert response.data["permission"] == "read" and response.data["approval_actions"] == ["delete"]
    assert session_client.patch(url, {"run_budget_cents": 10}, format="json").status_code == 400
    assert session_client.patch(url, {"approval_actions": ["nuke"]}, format="json").status_code == 400
    assert session_client.patch(url, {"permission": "root"}, format="json").status_code == 400
    assert _create(session_client, workspace, create_user, [alpha], name="Triage bot").status_code == 400


@pytest.mark.django_db
def test_project_must_be_one_the_actor_admins(session_client, workspace, create_user, alpha):
    other = User.objects.create(email="p@plane.so", username="p")
    foreign = Project.objects.create(name="Gamma", identifier="GAM", workspace=workspace)
    ProjectMember.objects.create(project=foreign, member=other, workspace=workspace, role=20)
    response = _create(session_client, workspace, create_user, [foreign])
    assert response.status_code == 403


@pytest.mark.django_db
def test_malformed_input_is_a_400(session_client, workspace, create_user, alpha):
    assert _create(session_client, workspace, create_user, [alpha], owner="abc").status_code == 400
    assert _create(session_client, workspace, create_user, [alpha], project_ids=["nope"]).status_code == 400
    assert _create(session_client, workspace, create_user, [alpha], approval_actions=[["x"]]).status_code == 400
    assert _create(session_client, workspace, create_user, [alpha], avatar_url=5).status_code == 400
    assert _create(session_client, workspace, create_user, [alpha], run_budget_cents="x").status_code == 400
    agent_id = _create(session_client, workspace, create_user, [alpha]).data["id"]
    url = _url(workspace, f"{agent_id}/")
    assert session_client.patch(url, {"owner": "abc"}, format="json").status_code == 400
    assert session_client.patch(url, {"project_ids": ["nope"]}, format="json").status_code == 400
    assert session_client.patch(url, {"approval_actions": [["x"]]}, format="json").status_code == 400
    assert session_client.patch(url, {"avatar_url": ["x"]}, format="json").status_code == 400


@pytest.mark.django_db
def test_agent_does_not_see_public_projects_it_is_not_in(session_client, workspace, create_user, alpha):
    public = Project.objects.create(name="Open", identifier="OPN", workspace=workspace, network=2)
    ProjectMember.objects.create(project=public, member=create_user, workspace=workspace, role=20)
    token = _create(session_client, workspace, create_user, [alpha]).data["token"]
    agent_client = APIClient()
    agent_client.credentials(HTTP_X_API_KEY=token)
    response = agent_client.get(f"/api/v1/workspaces/{workspace.slug}/projects/")
    assert response.status_code == 200
    rows = response.data["results"] if isinstance(response.data, dict) else response.data
    assert [str(r["id"]) for r in rows] == [str(alpha.id)]
    assert agent_client.get(f"/api/v1/workspaces/{workspace.slug}/projects/{public.id}/").status_code in (403, 404)
