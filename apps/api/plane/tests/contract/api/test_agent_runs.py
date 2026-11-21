# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Run log: agents and people's own Claude Code sessions report runs, steps, cost and PRs on a work item."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import (
    AgentRun,
    GitHubWorkItemLink,
    Issue,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)
from plane.utils import agent_runs


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Alpha", identifier="ALP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def issue(project):
    state = State.objects.create(name="Started", group="started", project=project, workspace=project.workspace)
    return Issue.objects.create(name="Item", project=project, workspace=project.workspace, state=state)


def _member(workspace, project, email):
    user = User.objects.create(email=email, username=email.split("@")[0], first_name=email.split("@")[0].title())
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=15)
    return user


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _url(workspace, project, issue, suffix=""):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/{issue.id}/agent-runs/{suffix}"


def _start(client, workspace, project, issue, **extra):
    return client.post(_url(workspace, project, issue), {"title": "Fix it", **extra}, format="json")


@pytest.mark.contract
@pytest.mark.django_db
def test_agent_reports_a_run_with_steps(api_key_client, workspace, project, issue, create_user):
    with patch("plane.utils.agent_runs.on_run_changed") as hook:
        created = _start(api_key_client, workspace, project, issue, external_url="https://example.com/session/1")
        assert created.status_code == 201 and created.data["status"] == "running"
        run_id = created.data["id"]
        for kind, text in (("message", "Reading the code"), ("tool", "ran pytest")):
            step = api_key_client.post(
                _url(workspace, project, issue, f"{run_id}/steps/"), {"kind": kind, "text": text}, format="json"
            )
            assert step.status_code == 201
        run = AgentRun.objects.get(pk=run_id)
        AgentRun.objects.filter(pk=run_id).update(started_at=run.started_at - timedelta(seconds=90))
        done = api_key_client.patch(
            _url(workspace, project, issue, f"{run_id}/"),
            {"status": "succeeded", "summary": "Done", "cost_cents": 37},
            format="json",
        )
    assert done.status_code == 200
    assert [call.args[1] for call in hook.call_args_list] == ["created", "step", "step", "finished"]

    shown = api_key_client.get(_url(workspace, project, issue, f"{run_id}/"))
    assert shown.status_code == 200
    assert shown.data["status"] == "succeeded" and shown.data["cost_cents"] == 37
    assert shown.data["summary"] == "Done" and shown.data["is_live"] is False
    assert 89 <= shown.data["duration_seconds"] <= 95
    assert [(s["seq"], s["text"]) for s in shown.data["steps"]] == [(1, "Reading the code"), (2, "ran pytest")]
    assert shown.data["actor"]["id"] == str(create_user.id) and shown.data["actor"]["is_agent"] is False

    listed = api_key_client.get(_url(workspace, project, issue))
    assert [r["id"] for r in listed.data] == [run_id] and "steps" not in listed.data[0]
    # The app twin reads the same run
    twin = _client(create_user).get(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/agent-runs/{run_id}/"
    )
    assert twin.status_code == 200 and twin.data["cost_cents"] == 37
    # A finished run takes no more steps
    late = api_key_client.post(_url(workspace, project, issue, f"{run_id}/steps/"), {"text": "x"}, format="json")
    assert late.status_code == 409


@pytest.mark.contract
@pytest.mark.django_db
def test_only_reporter_can_write_run(api_key_client, workspace, project, issue):
    run_id = _start(api_key_client, workspace, project, issue).data["id"]
    other = _client(_member(workspace, project, "bob@example.com"))
    assert other.get(_url(workspace, project, issue, f"{run_id}/")).status_code == 200
    patch_response = other.patch(_url(workspace, project, issue, f"{run_id}/"), {"status": "failed"}, format="json")
    assert patch_response.status_code == 403
    step = other.post(_url(workspace, project, issue, f"{run_id}/steps/"), {"text": "hi"}, format="json")
    assert step.status_code == 403
    run = AgentRun.objects.get(pk=run_id)
    assert run.status == "running" and run.steps.count() == 0


@pytest.mark.contract
@pytest.mark.django_db
def test_duplicate_external_step_ignored(api_key_client, workspace, project, issue):
    run_id = _start(api_key_client, workspace, project, issue).data["id"]
    url = _url(workspace, project, issue, f"{run_id}/steps/")
    body = {"kind": "tool", "text": "ran", "external_event_id": "evt-1"}
    assert api_key_client.post(url, body, format="json").status_code == 201
    again = api_key_client.post(url, body, format="json")
    assert again.status_code == 200 and again.data == {"duplicate": True}
    api_key_client.post(url, {"text": "next"}, format="json")
    run = AgentRun.objects.get(pk=run_id)
    assert list(run.steps.order_by("seq").values_list("seq", "text")) == [(1, "ran"), (2, "next")]
    assert agent_runs.add_step(run, "tool", "ran", external_event_id="evt-1") is None


@pytest.mark.contract
@pytest.mark.django_db
def test_live_flag_expires_after_10_minutes(api_key_client, workspace, project, issue, create_user):
    run_id = _start(api_key_client, workspace, project, issue).data["id"]
    live_url = f"/api/workspaces/{workspace.slug}/agent-runs/live/?issue_ids={issue.id}"
    session = _client(create_user)
    assert session.get(live_url).data[str(issue.id)]["id"] == run_id

    stale = timezone.now() - timedelta(minutes=11)
    AgentRun.objects.filter(pk=run_id).update(last_event_at=stale)
    shown = api_key_client.get(_url(workspace, project, issue, f"{run_id}/"))
    assert shown.data["status"] == "running" and shown.data["is_live"] is False
    assert session.get(live_url).data == {}

    # A new step makes it live again
    api_key_client.post(_url(workspace, project, issue, f"{run_id}/steps/"), {"text": "still here"}, format="json")
    assert session.get(live_url).data[str(issue.id)]["is_live"] is True


@pytest.mark.contract
@pytest.mark.django_db
def test_run_links_include_prs_since_start(api_key_client, workspace, project, issue):
    run_id = _start(api_key_client, workspace, project, issue).data["id"]
    started = AgentRun.objects.get(pk=run_id).started_at

    def link(kind, ref, created):
        GitHubWorkItemLink.objects.create(
            project=project,
            issue=issue,
            kind=kind,
            repository_id=1,
            repository_full_name="acme/app",
            ref=ref,
            title=f"{kind} {ref}",
            url=f"https://github.com/acme/app/{ref}",
            github_created_at=created,
        )

    link("pull_request", "7", started - timedelta(hours=1))
    link("pull_request", "8", started + timedelta(minutes=5))
    link("commit", "abc123", started + timedelta(minutes=6))
    link("branch", "feature-x", started + timedelta(minutes=7))
    shown = api_key_client.get(_url(workspace, project, issue, f"{run_id}/"))
    assert sorted((item["kind"], item["ref"]) for item in shown.data["links"]) == [
        ("commit", "abc123"),
        ("pull_request", "8"),
    ]
