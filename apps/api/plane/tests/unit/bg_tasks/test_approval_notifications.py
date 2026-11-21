# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Agent approvals on the Brief, in Slack (DM buttons and clicks) and in the agent's audit trail."""

import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

import pytest
from rest_framework.test import APIClient

from plane.bgtasks import supervision_task
from plane.db.models import (
    AgentApproval,
    AgentRun,
    APIActivityLog,
    Issue,
    Notification,
    Project,
    ProjectMember,
    SlackUserLink,
    State,
    User,
    WorkspaceMember,
)
from plane.utils import agents, slack_app
from plane.utils.brief import brief_for

SECRET = "signing-secret"
INTERACTIVITY_URL = "/api/slack/interactivity/"


def _resp(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


class FakeSlack:
    def __init__(self):
        self.calls = []

    def __call__(self, url, **kwargs):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, kwargs.get("data") or {}))
        if method == "conversations.open":
            return _resp({"ok": True, "channel": {"id": "D" + kwargs["data"]["users"]}})
        return _resp({"ok": True})

    def posts(self):
        return [data for method, data in self.calls if method == "chat.postMessage"]


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Alpha", identifier="ALP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    State.objects.create(name="Todo", project=project, workspace=workspace, group="backlog", default=True)
    return project


@pytest.fixture
def linked(workspace, create_user):
    with patch("plane.utils.slack_app.requests.post", return_value=_resp({"ok": True, "team_id": "T1", "team": "A"})):
        slack_app.connect(workspace, "xoxb-secret")
    SlackUserLink.objects.create(workspace=workspace, user=create_user, slack_user_id="U1")
    return create_user


def _agent(workspace, owner, project):
    agent, token = agents.create_agent(
        workspace, {"name": "Bot", "owner": str(owner.id), "project_ids": [str(project.id)]}, owner
    )
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=token)
    return agent, client, token


def _held_delete(workspace, project, client):
    """The agent deletes an item it created; the request is held and the approval returned."""
    created = client.post(
        f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/issues/", {"name": "Old <thing>"}, format="json"
    )
    assert created.status_code == 201, created.data
    held = client.delete(f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/issues/{created.data['id']}/")
    assert held.status_code == 403, held.data
    return Issue.objects.get(pk=created.data["id"]), AgentApproval.objects.get(pk=held.data["approval_id"])


@pytest.mark.unit
@pytest.mark.django_db
class TestApprovalBrief:
    def test_approval_shows_in_owners_brief(self, mock_celery, workspace, create_user, project):
        agent, client, _ = _agent(workspace, create_user, project)
        issue, approval = _held_delete(workspace, project, client)
        rows = [r for r in brief_for(workspace.id, create_user)["needs_me"] if r["why"] == "approval"]
        assert len(rows) == 1
        row = rows[0]
        assert row["approval"]["id"] == str(approval.id)
        assert row["approval"]["action"] == "delete" and row["approval"]["summary"] == approval.summary
        assert row["approval"]["agent"]["id"] == str(agent.id) and row["approval"]["agent"]["name"] == "Bot"
        assert "avatar_url" in row["approval"]["agent"] and row["approval"]["created_at"]
        assert row["issue"]["id"] == str(issue.id)

        # Nobody else sees it, and once decided it leaves the list
        other = User.objects.create(email="other@plane.so", username="other", first_name="O")
        WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
        assert [r for r in brief_for(workspace.id, other)["needs_me"] if r["why"] == "approval"] == []
        approval.status = "rejected"
        approval.save()
        assert [r for r in brief_for(workspace.id, create_user)["needs_me"] if r["why"] == "approval"] == []

    def test_brief_api_includes_approval(self, mock_celery, session_client, workspace, create_user, project):
        _, client, _ = _agent(workspace, create_user, project)
        _held_delete(workspace, project, client)
        response = session_client.get(f"/api/workspaces/{workspace.slug}/brief/")
        assert response.status_code == 200
        assert [r["why"] for r in response.data["needs_me"]] == ["approval"]


@pytest.mark.unit
@pytest.mark.django_db
class TestApprovalNotification:
    def test_approval_dm_has_buttons(self, mock_celery, settings, workspace, create_user, project, linked):
        settings.WEB_URL = "https://plane.example.com"
        _, client, _ = _agent(workspace, create_user, project)
        _, approval = _held_delete(workspace, project, client)
        slack = FakeSlack()
        with patch("plane.utils.slack_app.requests.post", side_effect=slack):
            supervision_task.notify_approval(str(approval.id))
            supervision_task.notify_approval(str(approval.id))  # a retry must not duplicate the inbox row
        posts = slack.posts()
        assert len(posts) == 2 and posts[0]["channel"] == "DU1"
        assert posts[0]["text"] == f"Bot wants to {approval.summary}"
        blocks = json.loads(posts[0]["blocks"])
        assert supervision_task.escape_mrkdwn(f"Bot wants to {approval.summary}") in blocks[0]["text"]["text"]
        buttons = blocks[1]["elements"]
        assert [(b["text"]["text"], b["action_id"]) for b in buttons] == [
            ("Approve", f"approval:{approval.id}:approve"),
            ("Reject", f"approval:{approval.id}:reject"),
        ]
        notes = Notification.objects.filter(receiver=create_user, entity_name="approval")
        assert notes.count() == 1
        note = notes.get()
        assert note.sender == "approval" and note.entity_identifier == approval.issue_id
        assert note.data["approval"]["id"] == str(approval.id)

    def test_decided_approval_is_not_sent(self, mock_celery, workspace, create_user, project, linked):
        _, client, _ = _agent(workspace, create_user, project)
        _, approval = _held_delete(workspace, project, client)
        approval.status = "rejected"
        approval.save()
        slack = FakeSlack()
        with patch("plane.utils.slack_app.requests.post", side_effect=slack):
            supervision_task.notify_approval(str(approval.id))
        assert slack.posts() == [] and not Notification.objects.filter(entity_name="approval").exists()

    def test_creating_an_approval_queues_the_notification(self, workspace, create_user, project):
        _, client, _ = _agent(workspace, create_user, project)
        with patch.object(supervision_task.notify_approval, "delay") as delay:
            with patch("django.db.transaction.on_commit", side_effect=lambda fn: fn()):
                _, approval = _held_delete(workspace, project, client)
        delay.assert_called_once_with(str(approval.id))


def _signed(payload, secret=SECRET):
    body = urlencode({"payload": json.dumps(payload)}).encode()
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(secret.encode(), f"v0:{timestamp}:".encode() + body, hashlib.sha256).hexdigest()
    return body, {"HTTP_X_SLACK_REQUEST_TIMESTAMP": timestamp, "HTTP_X_SLACK_SIGNATURE": signature}


def _click(approval, verb="approve", slack_user="U1"):
    return {
        "type": "block_actions",
        "team": {"id": "T1"},
        "user": {"id": slack_user},
        "response_url": "https://hooks.slack.com/actions/T1/1/abc",
        "actions": [{"action_id": f"approval:{approval.id}:{verb}", "type": "button"}],
    }


def _post(client, payload, **kwargs):
    body, headers = _signed(payload, **kwargs)
    with patch("plane.app.views.slack_interactivity.requests.post") as post:
        response = client.post(
            INTERACTIVITY_URL, data=body, content_type="application/x-www-form-urlencoded", **headers
        )
    return response, post


@pytest.mark.unit
@pytest.mark.django_db
class TestApprovalClicks:
    @pytest.fixture(autouse=True)
    def _secret(self, settings):
        settings.SLACK_SIGNING_SECRET = SECRET

    def test_slack_click_approves_and_runs(self, mock_celery, client, workspace, create_user, project, linked):
        _, agent_client, _ = _agent(workspace, create_user, project)
        issue, approval = _held_delete(workspace, project, agent_client)
        response, post = _post(client, _click(approval))
        assert response.status_code == 200
        approval.refresh_from_db()
        assert approval.status == "executed" and approval.decided_by_id == create_user.id
        assert not Issue.issue_objects.filter(pk=issue.pk).exists()
        sent = post.call_args.kwargs["json"]
        assert sent["replace_original"] is True and "Approved" in json.dumps(sent)
        assert post.call_args.args[0] == "https://hooks.slack.com/actions/T1/1/abc"

        again, post = _post(client, _click(approval))
        assert again.status_code == 200 and "Already executed" in json.dumps(post.call_args.kwargs["json"])

    def test_slack_click_rejects(self, mock_celery, client, workspace, create_user, project, linked):
        _, agent_client, _ = _agent(workspace, create_user, project)
        issue, approval = _held_delete(workspace, project, agent_client)
        response, post = _post(client, _click(approval, "reject"))
        assert response.status_code == 200
        approval.refresh_from_db()
        assert approval.status == "rejected"
        assert Issue.issue_objects.filter(pk=issue.pk).exists()
        assert "Rejected" in json.dumps(post.call_args.kwargs["json"])

    def test_click_needs_a_valid_signature_and_a_linked_person(
        self, mock_celery, client, workspace, create_user, project, linked
    ):
        _, agent_client, _ = _agent(workspace, create_user, project)
        issue, approval = _held_delete(workspace, project, agent_client)
        bad, post = _post(client, _click(approval), secret="wrong")
        assert bad.status_code == 401 and not post.called
        stranger, post = _post(client, _click(approval, slack_user="UOTHER"))
        assert stranger.status_code == 200
        assert post.call_args.kwargs["json"]["response_type"] == "ephemeral"
        approval.refresh_from_db()
        assert approval.status == "open" and Issue.issue_objects.filter(pk=issue.pk).exists()

    def test_other_members_cannot_decide(self, mock_celery, client, workspace, create_user, project, linked):
        _, agent_client, _ = _agent(workspace, create_user, project)
        _, approval = _held_delete(workspace, project, agent_client)
        other = User.objects.create(email="other@plane.so", username="other", first_name="O")
        WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
        SlackUserLink.objects.create(workspace=workspace, user=other, slack_user_id="U2")
        response, post = _post(client, _click(approval, slack_user="U2"))
        assert response.status_code == 200
        assert post.call_args.kwargs["json"]["response_type"] == "ephemeral"
        approval.refresh_from_db()
        assert approval.status == "open"


@pytest.mark.unit
@pytest.mark.django_db
class TestAgentAudit:
    def test_audit_lists_requests_approvals_and_runs(
        self, mock_celery, session_client, workspace, create_user, project
    ):
        agent, client, token = _agent(workspace, create_user, project)
        issue, approval = _held_delete(workspace, project, client)
        old = agents.rotate_token(agent, create_user)  # the first token is now revoked; its history must stay
        APIActivityLog.objects.create(
            token_identifier=token, path="/api/v1/x/", method="GET", response_code=200, query_params=""
        )
        APIActivityLog.objects.create(token_identifier=old, path="/api/v1/y/", method="POST", response_code=201)
        APIActivityLog.objects.create(
            token_identifier="someone-else", path="/api/v1/z/", method="GET", response_code=200
        )
        run = AgentRun.objects.create(
            workspace=workspace, project=project, issue=issue, agent=agent, actor=agent.user, title="Fix it"
        )

        response = session_client.get(f"/api/workspaces/{workspace.slug}/agents/{agent.id}/audit/")
        assert response.status_code == 200, response.data
        rows = response.data
        kinds = [r["kind"] for r in rows]
        assert kinds.count("request") == 2 and kinds.count("approval") == 1 and kinds.count("run") == 1
        assert [r["at"] for r in rows] == sorted((r["at"] for r in rows), reverse=True)
        requests = {r["path"]: r for r in rows if r["kind"] == "request"}
        assert set(requests) == {"/api/v1/x/", "/api/v1/y/"}
        assert requests["/api/v1/y/"]["method"] == "POST" and requests["/api/v1/y/"]["status"] == 201
        approval_row = next(r for r in rows if r["kind"] == "approval")
        assert approval_row["id"] == str(approval.id) and approval_row["status"] == "open"
        run_row = next(r for r in rows if r["kind"] == "run")
        assert run_row["id"] == str(run.id) and run_row["title"] == "Fix it"
        assert len(agents.audit_for(agent, limit=2)) == 2

    def test_audit_is_for_admins_only(self, mock_celery, workspace, create_user, project):
        agent, _, _ = _agent(workspace, create_user, project)
        member = User.objects.create(email="member@plane.so", username="member", first_name="M")
        WorkspaceMember.objects.create(workspace=workspace, member=member, role=15)
        client = APIClient()
        client.force_authenticate(user=member)
        response = client.get(f"/api/workspaces/{workspace.slug}/agents/{agent.id}/audit/")
        assert response.status_code == 403
