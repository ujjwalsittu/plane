# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Waiting on, blocked-by and stale work items."""

from datetime import timedelta

import pytest
from django.utils import timezone

from plane.db.models import (
    Issue,
    IssueActivity,
    IssueRelation,
    Project,
    ProjectMember,
    State,
    User,
    WorkItemWaiting,
    WorkspaceMember,
)
from plane.utils.supervision import blocked_items


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Alpha", identifier="ALP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


def _state(project, group, name=None):
    return State.objects.create(name=name or group.title(), group=group, project=project, workspace=project.workspace)


def _issue(project, group, name="Item"):
    state = State.objects.filter(project=project, group=group).first() or _state(project, group)
    return Issue.objects.create(name=name, project=project, workspace=project.workspace, state=state)


def _url(workspace, project, issue):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/{issue.id}/waiting/"


def _by_id(rows):
    return {row["issue"]["id"]: row for row in rows}


@pytest.mark.contract
@pytest.mark.django_db
def test_waiting_on_person_and_external(api_key_client, session_client, workspace, project, create_user):
    issue = _issue(project, "started")
    other = User.objects.create(email="other@example.com", username="other", first_name="Other")
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
    url = _url(workspace, project, issue)

    put = api_key_client.put(url, {"waiting_on_user": str(other.id), "note": "needs review"}, format="json")
    assert put.status_code == 200 and put.data["waiting_on_user"] == str(other.id)
    # A second PUT replaces the open row instead of adding one.
    put = api_key_client.put(url, {"waiting_on_text": "Legal"}, format="json")
    assert put.status_code == 200 and put.data["waiting_on_user"] is None and put.data["waiting_on_text"] == "Legal"
    assert WorkItemWaiting.objects.filter(issue=issue, resolved_at__isnull=True).count() == 1
    assert api_key_client.get(url).data["waiting_on_text"] == "Legal"

    reasons = _by_id(blocked_items(workspace.id, create_user))[str(issue.id)]["reasons"]
    assert [r["kind"] for r in reasons] == ["waiting_on"] and reasons[0]["detail"] == "Legal"

    # The app twin serves the same row.
    twin = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/waiting/"
    assert session_client.get(twin).data["waiting_on_text"] == "Legal"

    assert api_key_client.delete(url).status_code == 204
    assert api_key_client.get(url).status_code == 404
    assert str(issue.id) not in _by_id(blocked_items(workspace.id, create_user))


@pytest.mark.contract
@pytest.mark.django_db
def test_waiting_requires_target(api_key_client, workspace, project):
    issue = _issue(project, "started")
    outsider = User.objects.create(email="out@example.com", username="out", first_name="Out")
    url = _url(workspace, project, issue)
    assert api_key_client.put(url, {}, format="json").status_code == 400
    assert api_key_client.put(url, {"waiting_on_text": "   "}, format="json").status_code == 400
    assert api_key_client.put(url, {"waiting_on_user": str(outsider.id)}, format="json").status_code == 400
    assert api_key_client.put(url, {"waiting_on_user": "nope"}, format="json").status_code == 400
    assert not WorkItemWaiting.objects.filter(issue=issue).exists()


@pytest.mark.contract
@pytest.mark.django_db
def test_blocked_by_relation_listed_until_blocker_done(workspace, project, create_user):
    blocked = _issue(project, "unstarted", "Blocked")
    blocker = _issue(project, "started", "Blocker")
    # blocked_by: `issue` is blocked by `related_issue`.
    IssueRelation.objects.create(
        issue=blocked, related_issue=blocker, relation_type="blocked_by", project=project, workspace=workspace
    )
    rows = _by_id(blocked_items(workspace.id, create_user))
    assert [r["kind"] for r in rows[str(blocked.id)]["reasons"]] == ["blocked_by"]
    assert "Blocker" in rows[str(blocked.id)]["reasons"][0]["detail"]
    assert rows[str(blocked.id)]["issue"]["identifier"] == f"ALP-{blocked.sequence_id}"
    # The blocker itself is not blocked.
    assert str(blocker.id) not in rows

    blocker.state = _state(project, "completed", "Done")
    blocker.save()
    assert str(blocked.id) not in _by_id(blocked_items(workspace.id, create_user))


@pytest.mark.contract
@pytest.mark.django_db
def test_stale_after_seven_days(workspace, project, create_user):
    stale = _issue(project, "started", "Stale")
    fresh = _issue(project, "started", "Fresh")
    for issue, days in ((stale, 8), (fresh, 1)):
        activity = IssueActivity.objects.create(issue=issue, project=project, workspace=workspace, verb="updated")
        IssueActivity.objects.filter(pk=activity.pk).update(created_at=timezone.now() - timedelta(days=days))
    rows = _by_id(blocked_items(workspace.id, create_user))
    assert [r["kind"] for r in rows[str(stale.id)]["reasons"]] == ["stale"]
    assert str(fresh.id) not in rows


@pytest.mark.contract
@pytest.mark.django_db
def test_completed_items_never_blocked(workspace, project, create_user):
    done = _issue(project, "completed", "Done")
    blocker = _issue(project, "started", "Blocker")
    IssueRelation.objects.create(
        issue=done, related_issue=blocker, relation_type="blocked_by", project=project, workspace=workspace
    )
    WorkItemWaiting.objects.create(issue=done, project=project, waiting_on_text="Legal")
    activity = IssueActivity.objects.create(issue=done, project=project, workspace=workspace, verb="updated")
    IssueActivity.objects.filter(pk=activity.pk).update(created_at=timezone.now() - timedelta(days=30))
    assert str(done.id) not in _by_id(blocked_items(workspace.id, create_user))
