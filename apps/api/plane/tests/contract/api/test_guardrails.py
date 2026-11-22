# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Guardrails: read-only agents can't write; risky agent requests wait for the owner's approval, then run once."""

import json
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core import signing
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import (
    AgentApproval,
    APIActivityLog,
    Cycle,
    CycleIssue,
    Issue,
    IssueActivity,
    IssueComment,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceEvent,
    WorkspaceMember,
)
from plane.utils import agents, guardrails

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Alpha", identifier="ALP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    State.objects.create(name="Todo", project=project, workspace=workspace, group="backlog", default=True)
    return project


@pytest.fixture
def issue(project):
    return Issue.objects.create(name="Item", project=project, workspace=project.workspace)


def _agent(workspace, owner, project, **extra):
    agent, token = agents.create_agent(
        workspace, {"name": "Bot", "owner": str(owner.id), "project_ids": [str(project.id)], **extra}, owner
    )
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=token)
    return agent, client


def _session(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _issue_url(workspace, project, issue):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/"


def _agent_issue(client, workspace, project):
    """An item the agent created itself: members may only delete items they created."""
    response = client.post(
        f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/issues/", {"name": "Agent item"}, format="json"
    )
    assert response.status_code == 201, response.data
    return Issue.objects.get(pk=response.data["id"])


def _approve(user, workspace, approval_id, verb="approve"):
    return _session(user).post(f"/api/workspaces/{workspace.slug}/approvals/{approval_id}/{verb}/")


def test_read_only_agent_cannot_write(workspace, create_user, project, issue):
    _, client = _agent(workspace, create_user, project, permission="read")
    assert client.get(_issue_url(workspace, project, issue)).status_code == 200
    response = client.patch(_issue_url(workspace, project, issue), {"name": "Renamed"}, format="json")
    assert response.status_code == 403
    assert "read-only" in str(response.data)
    created = client.post(
        f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/issues/", {"name": "New"}, format="json"
    )
    assert created.status_code == 403
    issue.refresh_from_db()
    assert issue.name == "Item" and Issue.objects.filter(project=project).count() == 1


def test_delete_needs_approval_then_runs_once(workspace, create_user, project):
    agent, client = _agent(workspace, create_user, project)
    issue = _agent_issue(client, workspace, project)
    with patch("plane.utils.guardrails.on_approval_created") as hook:
        response = client.delete(_issue_url(workspace, project, issue))
    assert response.status_code == 403, response.data
    assert response.data["error"] == "approval_required"
    assert "do not retry" in response.data["detail"]
    approval = AgentApproval.objects.get(pk=response.data["approval_id"])
    hook.assert_called_once_with(approval)
    assert (approval.action, approval.status, approval.method) == ("delete", "open", "DELETE")
    assert approval.asked_user_id == create_user.id and approval.agent_id == agent.id
    assert approval.project_id == project.id and approval.issue_id == issue.id
    assert Issue.objects.filter(pk=issue.pk).exists()

    # The owner sees it in their list
    listed = _session(create_user).get(f"/api/workspaces/{workspace.slug}/approvals/?status=open")
    assert listed.status_code == 200 and [a["id"] for a in listed.data] == [str(approval.id)]

    # The agent can check the outcome
    shown = client.get(f"/api/v1/workspaces/{workspace.slug}/approvals/{approval.id}/")
    assert shown.status_code == 200 and shown.data["status"] == "open"

    approved = _approve(create_user, workspace, approval.id)
    assert approved.status_code == 200, approved.data
    approval.refresh_from_db()
    assert approval.status == "executed" and approval.result_status == 204, approval.result_body
    assert approval.decided_by_id == create_user.id and approval.decided_at is not None
    assert not Issue.issue_objects.filter(pk=issue.pk).exists()
    assert Issue.all_objects.get(pk=issue.pk).deleted_at is not None

    shown = client.get(f"/api/v1/workspaces/{workspace.slug}/approvals/{approval.id}/")
    assert shown.data["status"] == "executed" and shown.data["result_status"] == 204
    # Approving twice does nothing
    assert _approve(create_user, workspace, approval.id).status_code == 409


def test_date_change_needs_approval(mock_celery, workspace, create_user, project, issue):
    agent, client = _agent(workspace, create_user, project)
    gated = client.patch(_issue_url(workspace, project, issue), {"target_date": "2026-12-31"}, format="json")
    assert gated.status_code == 403 and gated.data["error"] == "approval_required"
    issue.refresh_from_db()
    assert issue.target_date is None
    approval = AgentApproval.objects.get(pk=gated.data["approval_id"])
    assert approval.action == "change_dates" and approval.body == {"target_date": "2026-12-31"}

    # A body that can't be parsed is still a 400, not an empty update
    broken = client.patch(_issue_url(workspace, project, issue), "{not json", content_type="application/json")
    assert broken.status_code == 400
    # A change that isn't gated goes through with its body intact
    renamed = client.patch(_issue_url(workspace, project, issue), {"name": "Renamed"}, format="json")
    assert renamed.status_code == 200, renamed.data
    issue.refresh_from_db()
    assert issue.name == "Renamed"

    with patch.object(issue_activity, "delay", lambda *a, **k: issue_activity.run(*a, **k)):
        assert _approve(create_user, workspace, approval.id).status_code == 200
    approval.refresh_from_db()
    issue.refresh_from_db()
    assert approval.status == "executed" and approval.result_status == 200
    assert str(issue.target_date) == "2026-12-31"
    assert issue.updated_by_id == agent.user_id
    # The replay is credited to the agent, through the API key
    activity = IssueActivity.objects.filter(issue=issue, field="target_date").get()
    assert activity.actor_id == agent.user_id and activity.source == "api"


def test_same_request_reuses_open_approval(workspace, create_user, project, issue):
    _, client = _agent(workspace, create_user, project)
    with patch("plane.utils.guardrails.on_approval_created") as hook:
        first = client.delete(_issue_url(workspace, project, issue))
        second = client.delete(_issue_url(workspace, project, issue))
        other = client.patch(_issue_url(workspace, project, issue), {"start_date": "2026-12-01"}, format="json")
    assert first.data["approval_id"] == second.data["approval_id"]
    assert other.data["approval_id"] != first.data["approval_id"]
    assert AgentApproval.objects.count() == 2 and hook.call_count == 2


def test_replay_runs_once_and_records_missing_target(workspace, create_user, project, issue, api_key_client):
    _, client = _agent(workspace, create_user, project)
    approval_id = client.delete(_issue_url(workspace, project, issue)).data["approval_id"]
    # A person deletes the item before the owner approves
    assert api_key_client.delete(_issue_url(workspace, project, issue)).status_code == 204
    response = _approve(create_user, workspace, approval_id)
    assert response.status_code == 200
    approval = AgentApproval.objects.get(pk=approval_id)
    assert approval.status == "failed" and approval.result_status == 404
    assert _approve(create_user, workspace, approval_id).status_code == 409


def test_people_are_not_gated(workspace, project, issue, api_key_client):
    response = api_key_client.delete(_issue_url(workspace, project, issue))
    assert response.status_code == 204
    assert AgentApproval.objects.count() == 0


def test_forged_approval_header_is_ignored(workspace, create_user, project, issue):
    _, client = _agent(workspace, create_user, project)
    approval_id = client.delete(_issue_url(workspace, project, issue)).data["approval_id"]
    # An unsigned header, a header signed with the wrong salt, and a valid one for an approval that is still open
    for header in (
        approval_id,
        signing.dumps(approval_id, salt="other"),
        signing.dumps(approval_id, salt="agent-approval"),
    ):
        response = client.delete(_issue_url(workspace, project, issue), HTTP_X_PLANE_APPROVAL=header)
        assert response.status_code == 403 and response.data["error"] == "approval_required"
    assert Issue.issue_objects.filter(pk=issue.pk).exists()
    # Even approved, its signature doesn't unlock a different request
    AgentApproval.objects.filter(pk=approval_id).update(status="approved")
    other = Issue.objects.create(name="Other", project=project, workspace=workspace)
    response = client.delete(
        _issue_url(workspace, project, other), HTTP_X_PLANE_APPROVAL=signing.dumps(approval_id, salt="agent-approval")
    )
    assert response.status_code == 403
    assert Issue.issue_objects.filter(pk=other.pk).exists()


def test_contribute_agent_cannot_delete_without_gate(workspace, create_user, project, issue):
    _, client = _agent(workspace, create_user, project, approval_actions=["change_dates"])
    response = client.delete(_issue_url(workspace, project, issue))
    assert response.status_code == 403 and "approval_id" not in response.data
    assert AgentApproval.objects.count() == 0
    archive = client.post(
        f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/cycles/{uuid.uuid4()}/archive/", format="json"
    )
    assert archive.status_code == 403 and "approval_id" not in archive.data
    assert Issue.issue_objects.filter(pk=issue.pk).exists()


def test_only_owner_or_admin_decides(workspace, create_user, project, issue):
    _, client = _agent(workspace, create_user, project)
    approval_id = client.delete(_issue_url(workspace, project, issue)).data["approval_id"]
    member = User.objects.create(email="member@plane.so", username="member")
    WorkspaceMember.objects.create(workspace=workspace, member=member, role=15)
    assert _approve(member, workspace, approval_id).status_code == 403
    assert _approve(create_user, workspace, approval_id, "reject").status_code == 200
    assert AgentApproval.objects.get(pk=approval_id).status == "rejected"
    assert Issue.issue_objects.filter(pk=issue.pk).exists()


def test_expire_open_approvals(workspace, create_user, project, issue):
    _, client = _agent(workspace, create_user, project)
    approval_id = client.delete(_issue_url(workspace, project, issue)).data["approval_id"]
    fresh = client.patch(_issue_url(workspace, project, issue), {"end_date": "2026-12-01"}, format="json")
    AgentApproval.objects.filter(pk=approval_id).update(created_at=timezone.now() - timedelta(days=8))
    guardrails.expire_approvals()
    assert AgentApproval.objects.get(pk=approval_id).status == "expired"
    assert AgentApproval.objects.get(pk=fresh.data["approval_id"]).status == "open"
    # Past the deadline but not swept yet: deciding it expires it instead
    AgentApproval.objects.filter(pk=fresh.data["approval_id"]).update(created_at=timezone.now() - timedelta(days=8))
    assert _approve(create_user, workspace, fresh.data["approval_id"]).status_code == 409
    assert AgentApproval.objects.get(pk=fresh.data["approval_id"]).status == "expired"


def test_stuck_approved_replay_is_failed_by_sweep(workspace, create_user, project, issue):
    agent, client = _agent(workspace, create_user, project)
    ids = [client.delete(_issue_url(workspace, project, issue)).data["approval_id"]]
    second = client.patch(_issue_url(workspace, project, issue), {"end_date": "2026-12-01"}, format="json")
    ids.append(second.data["approval_id"])
    now = timezone.now()
    AgentApproval.objects.filter(pk=ids[0]).update(status="approved", decided_at=now - timedelta(minutes=11))
    AgentApproval.objects.filter(pk=ids[1]).update(status="approved", decided_at=now - timedelta(minutes=5))
    guardrails.expire_approvals()
    stuck, recent = (AgentApproval.objects.get(pk=i) for i in ids)
    assert stuck.status == "failed" and stuck.result_body == {"error": "The approved request never ran"}
    assert recent.status == "approved"
    assert WorkspaceEvent.objects.filter(event="approval", action="failed", entity_id=stuck.id).count() == 1
    guardrails.expire_approvals()
    assert WorkspaceEvent.objects.filter(event="approval", action="failed").count() == 1


def test_stuck_replay_sweep_runs_every_ten_minutes(workspace, create_user, project, issue):
    from plane.bgtasks.guardrails_task import fail_stuck_approval_replays
    from plane.celery import app

    entry = app.conf.beat_schedule["fail-stuck-approval-replays"]
    assert entry["task"] == "plane.bgtasks.guardrails_task.fail_stuck_approval_replays"
    assert entry["schedule"].run_every == timedelta(minutes=10)
    assert entry["options"]["expires"] == 540

    _, client = _agent(workspace, create_user, project)
    approval_id = client.delete(_issue_url(workspace, project, issue)).data["approval_id"]
    AgentApproval.objects.filter(pk=approval_id).update(
        status="approved", decided_at=timezone.now() - timedelta(minutes=11)
    )
    assert fail_stuck_approval_replays() == 1
    assert AgentApproval.objects.get(pk=approval_id).status == "failed"


def test_open_approvals_capped_per_agent(workspace, create_user, project, issue):
    agent, client = _agent(workspace, create_user, project)
    for n in range(guardrails.MAX_OPEN_APPROVALS):
        AgentApproval.objects.create(
            workspace=workspace,
            project=project,
            agent=agent,
            asked_user=create_user,
            action="delete",
            summary=f"delete item {n}",
            method="DELETE",
            path=f"/api/v1/x/{n}/",
        )
    over = client.delete(_issue_url(workspace, project, issue))
    assert over.status_code == 429
    assert over.data["error"] == "too_many_approvals"
    assert over.data["detail"] == (
        "50 actions are already waiting for approval; wait for decisions before asking again."
    )
    assert AgentApproval.objects.filter(agent=agent).count() == 50
    # A request that already has an open approval is not refused
    existing = AgentApproval.objects.filter(agent=agent).first()
    existing.path, existing.method, existing.body = _issue_url(workspace, project, issue), "DELETE", None
    existing.save()
    again = client.delete(_issue_url(workspace, project, issue))
    assert again.status_code == 403 and again.data["error"] == "approval_required"
    assert again.data["approval_id"] == str(existing.id)


def test_classify():
    class Req:
        def __init__(self, method, path, body=None):
            self.method, self.path, self._body = method, path, body

    cases = [
        (Req("DELETE", "/api/v1/x/"), "delete"),
        (Req("POST", "/api/v1/x/archive/"), "delete"),
        (Req("POST", "/api/v1/x/archive"), "delete"),
        (Req("POST", "/api/v1/x/"), None),
        (Req("PATCH", "/api/v1/x/", {"target_date": None}), "change_dates"),
        (Req("PUT", "/api/v1/x/", {"name": "a"}), None),
        (Req("GET", "/api/v1/x/"), None),
    ]
    for req, expected in cases:
        with patch("plane.utils.guardrails._json_body", lambda r: r._body):
            assert guardrails.classify(req) == expected


def test_gate_stays_inside_the_agents_projects(workspace, create_user, project):
    _, client = _agent(workspace, create_user, project)
    beta = Project.objects.create(name="Beta", identifier="BET", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=beta, member=create_user, workspace=workspace, role=20)
    secret = Issue.objects.create(name="Secret plan", project=beta, workspace=workspace)
    url = _issue_url(workspace, beta, secret)
    with patch("plane.utils.guardrails.on_approval_created") as hook:
        deleted = client.delete(url)
        dated = client.patch(url, {"target_date": "2026-12-31"}, format="json")
    for response in (deleted, dated):
        assert response.status_code == 403 and "approval_id" not in response.data
        assert "Secret" not in str(response.data) and "BET" not in str(response.data)
    assert AgentApproval.objects.count() == 0 and hook.call_count == 0
    assert Issue.issue_objects.filter(pk=secret.pk).exists()


def test_summary_names_the_sub_resource(workspace, create_user, project):
    _, client = _agent(workspace, create_user, project)
    issue = _agent_issue(client, workspace, project)
    ref = f"ALP-{issue.sequence_id}"
    comment = IssueComment.objects.create(
        workspace=workspace, project=project, issue=issue, comment_html="<p>hi</p>", created_by=create_user
    )
    base = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}"
    gated = client.delete(f"{base}/issues/{issue.id}/comments/{comment.id}/")
    approval = AgentApproval.objects.get(pk=gated.data["approval_id"])
    assert approval.summary == f"delete comment on {ref}"
    assert "Agent item" not in str(gated.data)

    cycle = Cycle.objects.create(name="Sprint 1", project=project, workspace=workspace, owned_by=create_user)
    CycleIssue.objects.create(cycle=cycle, issue=issue, project=project, workspace=workspace)
    gated = client.delete(f"{base}/cycles/{cycle.id}/cycle-issues/{issue.id}/")
    assert AgentApproval.objects.get(pk=gated.data["approval_id"]).summary == f'remove {ref} from cycle "Sprint 1"'

    gated = client.delete(_issue_url(workspace, project, issue))
    assert AgentApproval.objects.get(pk=gated.data["approval_id"]).summary == f'delete {ref} "Agent item"'


def test_replay_is_logged_without_the_signature(workspace, create_user, project):
    _, client = _agent(workspace, create_user, project)
    issue = _agent_issue(client, workspace, project)
    approval_id = client.delete(_issue_url(workspace, project, issue)).data["approval_id"]
    assert _approve(create_user, workspace, approval_id).status_code == 200
    log = APIActivityLog.objects.get(path=_issue_url(workspace, project, issue), method="DELETE", response_code=204)
    assert "[REDACTED]" in log.headers
    signature = signing.dumps(str(approval_id), salt="agent-approval")
    assert signature.split(":")[0] not in log.headers
    assert "plane_api_" not in log.headers


def test_owner_outside_the_project_gets_no_request_details(workspace, create_user, project, api_key_client):
    agent, client = _agent(workspace, create_user, project)
    issue = _agent_issue(client, workspace, project)
    approval_id = client.delete(_issue_url(workspace, project, issue)).data["approval_id"]
    # The owner (a workspace admin) is not in the project the held request touches
    ProjectMember.objects.filter(project=project, member=create_user).update(is_active=False)
    hidden = ("path", "query", "body", "result_body", "issue_id")
    leaked = ("Agent item", str(issue.id), f"ALP-{issue.sequence_id}")

    def assert_scoped(row):
        assert row["summary"] == "delete an item in Alpha"
        assert all(row[key] is None for key in hidden), row
        assert row["project_id"] == str(project.id) and row["agent"]["id"] == str(agent.id)
        assert not any(word in json.dumps(row) for word in leaked), row

    listed = _session(create_user).get(f"/api/workspaces/{workspace.slug}/approvals/?status=open")
    assert listed.status_code == 200 and len(listed.data) == 1
    assert_scoped(listed.data[0])
    approved = _approve(create_user, workspace, approval_id)
    assert approved.status_code == 200 and approved.data["status"] == "executed"
    assert_scoped(approved.data)
    # The public API (the owner's own key) is scoped the same way
    shown = api_key_client.get(f"/api/v1/workspaces/{workspace.slug}/approvals/{approval_id}/")
    assert shown.status_code == 200
    assert_scoped(shown.data)

    # The agent itself keeps the full payload, and so does a project member
    full = client.get(f"/api/v1/workspaces/{workspace.slug}/approvals/{approval_id}/")
    assert full.data["path"] == _issue_url(workspace, project, issue) and full.data["issue_id"] == str(issue.id)
    assert "Agent item" in full.data["summary"]
    ProjectMember.objects.filter(project=project, member=create_user).update(is_active=True)
    rows = _session(create_user).get(f"/api/workspaces/{workspace.slug}/approvals/").data
    assert rows[0]["path"] == _issue_url(workspace, project, issue) and "Agent item" in rows[0]["summary"]


def _failing_insert(*args, **kwargs):
    """An event insert that fails inside the database, which aborts the surrounding transaction."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1/0")


def test_failed_event_insert_does_not_strand_an_approval(workspace, create_user, project):
    _, client = _agent(workspace, create_user, project)
    issue = _agent_issue(client, workspace, project)
    approval_id = client.delete(_issue_url(workspace, project, issue)).data["approval_id"]
    with (
        patch("plane.utils.events.WorkspaceEvent.objects.create", side_effect=_failing_insert),
        patch("plane.utils.events.log_exception") as logged,
    ):
        approved = _approve(create_user, workspace, approval_id)
    assert approved.status_code == 200, approved.data
    approval = AgentApproval.objects.get(pk=approval_id)
    assert approval.status == "executed" and approval.result_status == 204
    assert not Issue.issue_objects.filter(pk=issue.pk).exists()
    assert logged.call_count >= 2  # the "approved" and "executed" events were dropped and logged


def test_agent_cannot_create_project(workspace, create_user, project):
    _, client = _agent(workspace, create_user, project)
    base = f"/api/v1/workspaces/{workspace.slug}/projects/"
    response = client.post(base, {"name": "Escape", "identifier": "ESC"}, format="json")
    assert response.status_code == 403, response.data
    assert not Project.objects.filter(identifier="ESC").exists()
    # Nor change a project's settings from the workspace-level route
    renamed = client.patch(f"{base}{project.id}/", {"name": "Taken"}, format="json")
    assert renamed.status_code == 403
    project.refresh_from_db()
    assert project.name == "Alpha"
    # Reading and its own project-level writes still work
    assert client.get(base).status_code == 200
    _agent_issue(client, workspace, project)


def test_manage_agent_can_create_project(workspace, create_user, project):
    _, client = _agent(workspace, create_user, project, permission="manage")
    response = client.post(
        f"/api/v1/workspaces/{workspace.slug}/projects/", {"name": "Spinoff", "identifier": "SPN"}, format="json"
    )
    assert response.status_code == 201, response.data
    assert Project.objects.filter(identifier="SPN").exists()


def test_removed_owner_cannot_decide(workspace, create_user, project, issue):
    _, client = _agent(workspace, create_user, project)
    approval_id = client.delete(_issue_url(workspace, project, issue)).data["approval_id"]
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(is_active=False)
    approval = AgentApproval.objects.get(pk=approval_id)
    with pytest.raises(agents.AgentError) as refused:
        guardrails.decide_approval(approval, create_user, True)
    assert refused.value.status_code == 403
    assert AgentApproval.objects.get(pk=approval_id).status == "open"
    assert Issue.issue_objects.filter(pk=issue.pk).exists()
