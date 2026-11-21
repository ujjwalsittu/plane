# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workspace event log: the cursor feed, the live stream and the webhooks for the newer event kinds."""

import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from asgiref.sync import async_to_sync
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from plane.api.views import events as events_views
from plane.bgtasks.events_task import prune_events as prune_events_task
from plane.bgtasks.webhook_task import webhook_activity
from plane.db.models import (
    APIToken,
    Issue,
    Project,
    ProjectMember,
    State,
    User,
    Webhook,
    WorkspaceEvent,
    WorkspaceMember,
)
from plane.utils import agent_runs, agents, decisions
from plane.utils.events import emit_event

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def _project(workspace, owner, name, identifier):
    project = Project.objects.create(name=name, identifier=identifier, workspace=workspace, created_by=owner)
    ProjectMember.objects.create(project=project, member=owner, workspace=workspace, role=20)
    State.objects.create(name="Todo", project=project, workspace=workspace, group="backlog", default=True)
    return project


@pytest.fixture
def project(workspace, create_user):
    return _project(workspace, create_user, "Alpha", "ALP")


@pytest.fixture
def other_project(workspace, create_user):
    return _project(workspace, create_user, "Beta", "BET")


@pytest.fixture
def issue(project):
    return Issue.objects.create(name="Item", project=project, workspace=project.workspace)


def _agent(workspace, owner, projects):
    agent, token = agents.create_agent(
        workspace, {"name": "Bot", "owner": str(owner.id), "project_ids": [str(p.id) for p in projects]}, owner
    )
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=token)
    return agent, client, token


def _feed(client, workspace, query=""):
    return client.get(f"/api/v1/workspaces/{workspace.slug}/events/{query}")


def _change(workspace, issue, actor, field="priority", verb="updated"):
    webhook_activity(
        event="issue",
        verb=verb,
        field=field,
        old_value="low",
        new_value="high",
        actor_id=str(actor.id),
        slug=workspace.slug,
        current_site="http://localhost",
        event_id=str(issue.id),
        old_identifier=None,
        new_identifier=None,
    )


def test_issue_change_appears_in_feed(api_key_client, workspace, project, issue, create_user):
    agent, agent_client, _ = _agent(workspace, create_user, [project])
    _change(workspace, issue, create_user)
    _change(workspace, issue, agent.user, field="state")

    body = _feed(api_key_client, workspace).data
    assert [(e["event"], e["action"], e["is_agent"]) for e in body["results"]] == [
        ("issue", "updated", False),
        ("issue", "updated", True),
    ]
    first = body["results"][0]
    assert first["entity_id"] == str(issue.id) and first["project_id"] == str(project.id)
    assert first["actor_id"] == str(create_user.id)
    assert first["data"] == {"field": "priority", "old_value": "low", "new_value": "high"}
    assert body["next_after"] == body["results"][-1]["id"]
    # An agent reads the same feed with its own key
    assert len(_feed(agent_client, workspace).data["results"]) == 2


def test_feed_cursor_and_type_filter(api_key_client, workspace, project, issue, create_user):
    _change(workspace, issue, create_user)
    emit_event(workspace.id, "milestone", "created", issue.id, project_id=project.id, actor=create_user)
    _change(workspace, issue, create_user, field="name")

    everything = _feed(api_key_client, workspace).data
    assert [e["event"] for e in everything["results"]] == ["issue", "milestone", "issue"]
    after_first = _feed(api_key_client, workspace, f"?after={everything['results'][0]['id']}").data
    assert [e["event"] for e in after_first["results"]] == ["milestone", "issue"]
    only_issue = _feed(api_key_client, workspace, "?types=issue,decision").data
    assert [e["event"] for e in only_issue["results"]] == ["issue", "issue"]
    paged = _feed(api_key_client, workspace, "?limit=1").data
    assert len(paged["results"]) == 1
    # Nothing new: the cursor stays where it was
    empty = _feed(api_key_client, workspace, f"?after={everything['next_after']}").data
    assert empty == {"results": [], "next_after": everything["next_after"]}
    by_project = _feed(api_key_client, workspace, f"?project={project.id}").data
    assert len(by_project["results"]) == 3


def test_feed_hides_projects_agent_is_not_in(workspace, project, other_project, create_user):
    agent, agent_client, _ = _agent(workspace, create_user, [project])
    secret = Issue.objects.create(name="Secret", project=other_project, workspace=workspace)
    visible = Issue.objects.create(name="Visible", project=project, workspace=workspace)
    _change(workspace, secret, create_user)
    _change(workspace, visible, create_user)
    emit_event(workspace.id, "decision", "created", visible.id, project_id=None, actor=create_user)

    results = _feed(agent_client, workspace).data["results"]
    assert {e["entity_id"] for e in results} == {str(visible.id)}
    assert len(results) == 2  # the project row and the workspace-level row
    assert _feed(agent_client, workspace, f"?project={other_project.id}").data["results"] == []
    # A person who is not an active member of the project follows the same rule
    person = User.objects.create(email="p@example.com", username="p")
    WorkspaceMember.objects.create(workspace=workspace, member=person, role=15)
    ProjectMember.objects.create(project=other_project, member=person, workspace=workspace, role=15)
    client = APIClient()
    client.force_authenticate(user=person)
    # (they see the Beta row and the workspace-level row, not Alpha's)
    assert [(e["entity_id"], e["project_id"]) for e in _feed(client, workspace).data["results"]] == [
        (str(secret.id), str(other_project.id)),
        (str(visible.id), None),
    ]
    # Someone outside the workspace gets nothing
    stranger = User.objects.create(email="s@example.com", username="s")
    client.force_authenticate(user=stranger)
    assert _feed(client, workspace).status_code == 404


def test_decision_and_run_events_reach_webhooks(
    workspace, project, issue, create_user, django_capture_on_commit_callbacks
):
    Webhook.objects.create(workspace=workspace, url="https://hooks.example.com/a", decision=True, agent_run=True)
    Webhook.objects.create(workspace=workspace, url="https://hooks.example.com/b", approval=True)
    Webhook.objects.create(workspace=workspace, url="https://hooks.example.com/c", milestone=True, is_active=False)
    agent, _, _ = _agent(workspace, create_user, [project])
    with patch("plane.bgtasks.webhook_task.webhook_send_task.delay") as send:
        with django_capture_on_commit_callbacks(execute=True):
            run = agent_runs.start_external_run(issue, agent.user, {"title": "Fix"})
            agent_runs.add_step(run, "message", "Reading", {})
            agent_runs.finish_run(run, "succeeded")
            decision = decisions.create_decision(
                issue, {"question": "Ship it?", "asked_user": str(create_user.id)}, agent.user, "api"
            )
            decisions.answer_decision(decision, create_user, "Yes")

    sent = [(c.kwargs["event"], c.kwargs["action"]) for c in send.call_args_list]
    # Only the first webhook (decision + agent_run) is called, once per event; approval and inactive ones are not
    assert sent == [
        ("agent_run", "created"),
        ("agent_run", "step"),
        ("agent_run", "finished"),
        ("decision", "created"),
        ("decision", "answered"),
    ]
    assert {c.kwargs["slug"] for c in send.call_args_list} == {workspace.slug}
    # The same events are in the feed, with the right is_agent
    rows = list(WorkspaceEvent.objects.filter(workspace=workspace).order_by("id"))
    assert [(r.event, r.action, r.is_agent) for r in rows] == [
        ("agent_run", "created", True),
        ("agent_run", "step", True),
        ("agent_run", "finished", True),
        ("decision", "created", True),
        ("decision", "answered", False),
    ]
    assert rows[1].data["steps"] == 1 and "Reading" not in json.dumps(rows[1].data)


def _stream_request(token, workspace, query="", **headers):
    return RequestFactory().get(
        f"/api/v1/workspaces/{workspace.slug}/events/stream/{query}", HTTP_X_API_KEY=token, **headers
    )


async def _collect(response, count):
    frames = []
    async for chunk in response.streaming_content:
        frames.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        if len(frames) >= count:
            break
    return frames


def test_stream_sends_events_and_ping(monkeypatch, workspace, project, issue, create_user):
    monkeypatch.setattr(events_views, "STREAM_POLL_SECONDS", 0.02)
    monkeypatch.setattr(events_views, "STREAM_PING_SECONDS", 0.1)
    monkeypatch.setattr(events_views, "STREAM_MAX_SECONDS", 1)
    agent, _, token = _agent(workspace, create_user, [project])
    hidden = _project(workspace, create_user, "Gamma", "GAM")
    emit_event(workspace.id, "milestone", "created", issue.id, project_id=hidden.id, actor=create_user)
    first = emit_event(workspace.id, "milestone", "created", issue.id, project_id=project.id, actor=create_user)
    second = emit_event(workspace.id, "milestone", "updated", issue.id, project_id=project.id, actor=create_user)

    async def run(request, count):
        response = await events_views.workspace_events_stream(request, workspace.slug)
        return response, await _collect(response, count)

    response, frames = async_to_sync(run)(_stream_request(token, workspace), 4)
    assert response.status_code == 200
    assert response["Content-Type"] == "text/event-stream"
    assert response["Cache-Control"] == "no-cache" and response["X-Accel-Buffering"] == "no"
    assert frames[0].startswith(":")
    assert frames[1].startswith(f"id: {first.id}\nevent: milestone\ndata: ")
    assert json.loads(frames[1].split("data: ", 1)[1])["action"] == "created"
    assert frames[2].startswith(f"id: {second.id}\n")  # the hidden project's row never appears
    assert frames[3] == ": ping\n\n"

    # Last-Event-ID resumes after that event; the stream closes after the (shortened) maximum
    _, resumed = async_to_sync(run)(_stream_request(token, workspace, HTTP_LAST_EVENT_ID=str(first.id)), 2)
    assert resumed[1].startswith(f"id: {second.id}\n")

    async def drain(request):
        response = await events_views.workspace_events_stream(request, workspace.slug)
        return await _collect(response, 10_000)

    frames = async_to_sync(drain)(_stream_request(token, workspace, f"?after={second.id}"))
    assert frames[-1] == ": ping\n\n" and all(not f.startswith("id:") for f in frames)


def test_stream_requires_authentication_and_membership(workspace, create_user):
    async def call(request):
        return await events_views.workspace_events_stream(request, workspace.slug)

    anonymous = RequestFactory().get(f"/api/v1/workspaces/{workspace.slug}/events/stream/")
    anonymous.user = type("Anon", (), {"is_authenticated": False})()
    assert async_to_sync(call)(anonymous).status_code == 401
    bad_key = _stream_request("nope", workspace)
    assert async_to_sync(call)(bad_key).status_code == 401
    stranger = User.objects.create(email="x@example.com", username="x")
    token = APIToken.objects.create(user=stranger, label="x", token="stranger-token")
    assert async_to_sync(call)(_stream_request(token.token, workspace)).status_code == 404


def test_prune_events_drops_rows_older_than_30_days(workspace, issue, create_user):
    old = emit_event(workspace.id, "milestone", "created", issue.id, actor=create_user)
    WorkspaceEvent.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=31))
    fresh = emit_event(workspace.id, "milestone", "updated", issue.id, actor=create_user)
    assert prune_events_task() == 1
    assert list(WorkspaceEvent.objects.values_list("pk", flat=True)) == [fresh.pk]


def test_milestone_changes_and_agent_approvals_are_logged(workspace, project, issue, create_user):
    agent, agent_client, _ = _agent(workspace, create_user, [project])
    base = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/milestones/"
    created = agent_client.post(base, {"title": "Beta"}, format="json")
    assert created.status_code == 201, created.data
    patched = agent_client.patch(f"{base}{created.data['id']}/", {"title": "Beta 2"}, format="json")
    assert patched.status_code == 200, patched.data
    # Deleting is gated for agents: the request waits for the owner, and that is an event too
    held = agent_client.delete(f"{base}{created.data['id']}/")
    assert held.status_code == 403 and held.data["error"] == "approval_required"
    rows = WorkspaceEvent.objects.filter(workspace=workspace).order_by("id")
    assert [(r.event, r.action, r.is_agent) for r in rows] == [
        ("milestone", "created", True),
        ("milestone", "updated", True),
        ("approval", "created", True),
    ]
