# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Waiting on, blocked-by and stale work items."""

from datetime import timedelta

import pytest
from rest_framework.test import APIClient
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
    # Nothing open is a 200 with a null body; 404 is reserved for a missing work item.
    empty = api_key_client.get(url)
    assert empty.status_code == 200 and empty.data is None
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


def _outsider(workspace, email, role=None, project=None):
    user = User.objects.create(email=email, username=email.split("@")[0], first_name="U")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    if project is not None:
        ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=role)
    return user


@pytest.mark.contract
@pytest.mark.django_db
def test_non_member_sees_nothing_and_no_foreign_blocker_titles(workspace, project, create_user):
    secret = Project.objects.create(name="Secret", identifier="SEC", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=secret, member=create_user, workspace=workspace, role=20)
    hidden_blocker = _issue(secret, "started", "Secret roadmap")
    blocked = _issue(project, "unstarted", "Blocked")
    IssueRelation.objects.create(
        issue=blocked, related_issue=hidden_blocker, relation_type="blocked_by", project=project, workspace=workspace
    )
    WorkItemWaiting.objects.create(issue=hidden_blocker, project=secret, waiting_on_text="Legal")

    # A member of `project` only: sees the blocked item but not the other project's title.
    viewer = _outsider(workspace, "viewer@example.com", role=15, project=project)
    rows = _by_id(blocked_items(workspace.id, viewer))
    assert str(hidden_blocker.id) not in rows
    detail = rows[str(blocked.id)]["reasons"][0]["detail"]
    assert "Secret" not in detail and "SEC-" not in detail
    assert detail == "Blocked by an item in another project"

    # The owner, a member of both, still gets the real title.
    owner_detail = _by_id(blocked_items(workspace.id, create_user))[str(blocked.id)]["reasons"][0]["detail"]
    assert "Secret roadmap" in owner_detail

    # A workspace member of no project sees nothing at all.
    stranger = _outsider(workspace, "stranger@example.com")
    assert blocked_items(workspace.id, stranger) == []


@pytest.mark.contract
@pytest.mark.django_db
def test_stale_falls_back_to_created_at_without_activity(workspace, project, create_user):
    old = _issue(project, "started", "Old")
    new = _issue(project, "started", "New")
    IssueActivity.objects.filter(issue__in=[old, new]).delete()
    Issue.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=30))
    rows = _by_id(blocked_items(workspace.id, create_user))
    assert [r["kind"] for r in rows[str(old.id)]["reasons"]] == ["stale"]
    assert str(new.id) not in rows


@pytest.mark.contract
@pytest.mark.django_db
def test_non_started_items_never_stale(workspace, project, create_user):
    for group in ("backlog", "unstarted"):
        issue = _issue(project, group, group)
        Issue.objects.filter(pk=issue.pk).update(created_at=timezone.now() - timedelta(days=60))
        IssueActivity.objects.filter(issue=issue).delete()
    assert blocked_items(workspace.id, create_user) == []


@pytest.mark.contract
@pytest.mark.django_db
def test_cancelled_and_deleted_blockers_do_not_block(workspace, project, create_user):
    blocked = _issue(project, "unstarted", "Blocked")
    cancelled = _issue(project, "cancelled", "Cancelled blocker")
    deleted = _issue(project, "started", "Deleted blocker")
    for blocker in (cancelled, deleted):
        IssueRelation.objects.create(
            issue=blocked, related_issue=blocker, relation_type="blocked_by", project=project, workspace=workspace
        )
    deleted.delete()
    assert str(blocked.id) not in _by_id(blocked_items(workspace.id, create_user))


@pytest.mark.contract
@pytest.mark.django_db
def test_guest_who_cannot_view_issue_gets_404(workspace, project, create_user):
    project.guest_view_all_features = False
    project.save()
    issue = _issue(project, "started")  # not created by the guest
    guest = _outsider(workspace, "guest@example.com", role=5, project=project)
    client = APIClient()
    client.force_authenticate(user=guest)
    twin = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/waiting/"
    assert client.get(twin).status_code == 404
    # Writes are refused outright for guests by the permission class.
    assert client.put(twin, {"waiting_on_text": "x"}, format="json").status_code == 403
    assert not WorkItemWaiting.objects.filter(issue=issue).exists()
