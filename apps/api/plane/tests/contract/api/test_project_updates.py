# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Project updates (on track / at risk / off track) and the predicted finish date."""

from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import Issue, Project, ProjectMember, ProjectUpdate, State, User, WorkspaceMember
from plane.utils.project_health import predicted_finish, project_health


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


@pytest.mark.contract
@pytest.mark.django_db
def test_predicted_finish_from_recent_throughput(project, states):
    _open(project, states, 10)
    _done(project, states, 14)  # one a day over the last 14 days
    _done(project, states, 20, days_ago=30)  # too old to count
    today = date(2026, 11, 21)
    assert predicted_finish(project, today) == today + timedelta(days=10)


@pytest.mark.contract
@pytest.mark.django_db
def test_no_throughput_no_prediction(project, states):
    _open(project, states, 5)
    _done(project, states, 3, days_ago=30)
    assert predicted_finish(project, date(2026, 11, 21)) is None


@pytest.mark.contract
@pytest.mark.django_db
def test_health_falls_back_to_prediction(project, states, create_user):
    today = date(2026, 11, 21)
    _open(project, states, 10)
    _done(project, states, 14)  # finishes in 10 days
    Project.objects.filter(pk=project.pk).update(target_date=today + timedelta(days=5))
    project.refresh_from_db()
    assert project_health(project, None, today) == "at_risk"
    Project.objects.filter(pk=project.pk).update(target_date=today + timedelta(days=20))
    project.refresh_from_db()
    assert project_health(project, None, today) == "on_track"
    # A posted update wins over the prediction.
    update = ProjectUpdate(health="off_track")
    assert project_health(project, update, today) == "off_track"
