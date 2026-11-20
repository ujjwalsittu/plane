# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Project updates (on track / at risk / off track) and the predicted finish date."""

from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import Issue, Project, ProjectMember, ProjectUpdate, State, User, Workspace, WorkspaceMember
from plane.utils.brief import brief_for, zone_for
from plane.utils.project_health import finish_from_counts


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Alpha", identifier="ALP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def states(project):
    return {
        group: State.objects.create(name=group.title(), group=group, project=project, workspace=project.workspace)
        for group in ("backlog", "started", "completed")
    }


def _open(project, states, count):
    for n in range(count):
        Issue.objects.create(name=f"Open {n}", project=project, workspace=project.workspace, state=states["started"])


def _done(project, states, count, days_ago=1):
    for n in range(count):
        issue = Issue.objects.create(
            name=f"Done {n}", project=project, workspace=project.workspace, state=states["completed"]
        )
        Issue.objects.filter(pk=issue.pk).update(completed_at=timezone.now() - timedelta(days=days_ago))


def _url(workspace, project):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/updates/"


@pytest.mark.contract
@pytest.mark.django_db
def test_agent_posts_update_with_health(api_key_client, workspace, project, create_user):
    response = api_key_client.post(
        _url(workspace, project),
        {"health": "at_risk", "body_html": "<p>Slipping</p><script>alert(1)</script>"},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["health"] == "at_risk"
    assert "<script" not in response.data["body_html"] and "Slipping" in response.data["body_html"]
    assert response.data["source"] == "api"
    assert response.data["by"]["is_agent"] is True
    assert ProjectUpdate.objects.get(project=project).created_by == create_user

    bad = api_key_client.post(_url(workspace, project), {"health": "great"}, format="json")
    assert bad.status_code == 400
    listed = api_key_client.get(_url(workspace, project))
    assert [row["health"] for row in listed.data] == ["at_risk"]

    # The browser twin records the source as "app".
    web = APIClient()
    web.force_authenticate(user=create_user)
    created = web.post(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/updates/",
        {"health": "on_track", "body_html": "<p>Fine</p>"},
        format="json",
    )
    assert created.status_code == 201, created.data
    assert created.data["source"] == "app" and created.data["by"]["is_agent"] is False


@pytest.mark.contract
@pytest.mark.django_db
def test_guests_read_but_cannot_post(workspace, project):
    guest = User.objects.create(email="g@example.com", username="guest")
    WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
    ProjectMember.objects.create(project=project, member=guest, workspace=workspace, role=5)
    client = APIClient()
    client.force_authenticate(user=guest)
    assert client.get(_url(workspace, project)).status_code == 200
    assert client.post(_url(workspace, project), {"health": "on_track"}, format="json").status_code == 403


def _row(workspace, user):
    rows = brief_for(workspace.id, user)["projects"]
    return rows[0] if rows else None


def _today(user):
    return timezone.now().astimezone(zone_for(user)).date()


@pytest.mark.contract
@pytest.mark.django_db
def test_predicted_finish_from_recent_throughput(workspace, project, states, create_user):
    _open(project, states, 10)
    _done(project, states, 14)  # one a day over the last 14 days
    _done(project, states, 20, days_ago=30)  # too old to count
    assert _row(workspace, create_user)["predicted_finish"] == (_today(create_user) + timedelta(days=10)).isoformat()
    today = date(2026, 11, 21)
    assert finish_from_counts(10, 14, today) == today + timedelta(days=10)
    assert finish_from_counts(0, 3, today) == today
    assert finish_from_counts(5, 3, today) == today + timedelta(days=24)  # 5 * 14 / 3 rounded up


@pytest.mark.contract
@pytest.mark.django_db
def test_no_throughput_no_prediction(workspace, project, states, create_user):
    _open(project, states, 5)
    _done(project, states, 3, days_ago=30)
    assert _row(workspace, create_user)["predicted_finish"] is None
    assert finish_from_counts(5, 0, date(2026, 11, 21)) is None


@pytest.mark.contract
@pytest.mark.django_db
def test_health_falls_back_to_prediction(workspace, project, states, create_user):
    today = _today(create_user)
    _open(project, states, 10)
    _done(project, states, 14)  # finishes in 10 days
    Project.objects.filter(pk=project.pk).update(target_date=today + timedelta(days=5))
    assert _row(workspace, create_user)["health"] == "at_risk"
    Project.objects.filter(pk=project.pk).update(target_date=today + timedelta(days=20))
    assert _row(workspace, create_user)["health"] == "on_track"
    # A posted update wins over the prediction, however old it is.
    update = ProjectUpdate.objects.create(
        project=project, workspace=workspace, health="off_track", body_html="<p>Old news</p>", created_by=create_user
    )
    ProjectUpdate.objects.filter(pk=update.pk).update(created_at=timezone.now() - timedelta(days=40))
    row = _row(workspace, create_user)
    assert row["health"] == "off_track"
    assert row["latest_update"]["excerpt"] == "Old news"


@pytest.mark.contract
@pytest.mark.django_db
def test_stale_update_without_open_work_leaves_the_strip(workspace, project, states, create_user):
    update = ProjectUpdate.objects.create(
        project=project, workspace=workspace, health="at_risk", body_html="<p>x</p>", created_by=create_user
    )
    assert _row(workspace, create_user)["health"] == "at_risk"
    ProjectUpdate.objects.filter(pk=update.pk).update(created_at=timezone.now() - timedelta(days=40))
    assert _row(workspace, create_user) is None


@pytest.mark.contract
@pytest.mark.django_db
def test_outsiders_cannot_read_or_post(workspace, project, create_user):
    outsider = User.objects.create(email="o@example.com", username="outsider")
    WorkspaceMember.objects.create(workspace=workspace, member=outsider, role=15)  # in the workspace, not the project
    other_ws = Workspace.objects.create(name="Other", slug="other-ws", owner=outsider)
    WorkspaceMember.objects.create(workspace=other_ws, member=outsider, role=20)
    foreign = Project.objects.create(name="Mine", identifier="MIN", workspace=other_ws, created_by=outsider)
    ProjectMember.objects.create(project=foreign, member=outsider, workspace=other_ws, role=20)
    client = APIClient()
    client.force_authenticate(user=outsider)
    body = {"health": "on_track", "body_html": "<p>hi</p>"}
    assert client.get(_url(workspace, project)).status_code == 403
    assert client.post(_url(workspace, project), body, format="json").status_code == 403
    # Another workspace's member using their own project id under this workspace's slug.
    assert client.get(_url(workspace, foreign)).status_code == 403
    assert client.post(_url(workspace, foreign), body, format="json").status_code == 403
    assert not ProjectUpdate.objects.exists()


@pytest.mark.contract
@pytest.mark.django_db
def test_guest_brief_counts_respect_visibility(workspace, project, states, create_user):
    guest = User.objects.create(email="g2@example.com", username="guest2")
    WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
    ProjectMember.objects.create(project=project, member=guest, workspace=workspace, role=5)
    Project.objects.filter(pk=project.pk).update(guest_view_all_features=False)
    _open(project, states, 4)  # created by someone else: a guest does not see these
    Issue.objects.create(name="Mine", project=project, workspace=workspace, state=states["started"])
    _done(project, states, 14)
    # created_by is stamped by the model on save, so hand the guest their items afterwards.
    Issue.objects.filter(project=project).exclude(name__startswith="Open").update(created_by=guest)
    # 14 done in 14 days is one a day: the prediction is today plus the open count each person can see.
    assert _row(workspace, create_user)["predicted_finish"] == (_today(create_user) + timedelta(days=5)).isoformat()
    assert _row(workspace, guest)["predicted_finish"] == (_today(guest) + timedelta(days=1)).isoformat()
