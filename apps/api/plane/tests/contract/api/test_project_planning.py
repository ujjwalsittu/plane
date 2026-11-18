# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Project dates, priority and status; explicit completed_at on work items."""

import pytest
from rest_framework import status

from plane.db.models import Issue, Project, ProjectMember, State


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Plan", identifier="PLN", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.mark.contract
@pytest.mark.django_db
def test_external_update_retrieve_and_list(api_key_client, workspace, project):
    url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/"
    assert api_key_client.get(url).data["status"] == "backlog"

    updated = api_key_client.patch(
        url,
        {"start_date": "2026-11-11", "target_date": "2026-12-20", "priority": "high", "status": "in_progress"},
        format="json",
    )
    assert updated.status_code == status.HTTP_200_OK, updated.data

    detail = api_key_client.get(url).data
    assert (detail["start_date"], detail["target_date"]) == ("2026-11-11", "2026-12-20")
    assert (detail["priority"], detail["status"]) == ("high", "in_progress")

    lite = api_key_client.get(f"/api/v1/workspaces/{workspace.slug}/projects-lite/").data["results"]
    row = next(p for p in lite if str(p["id"]) == str(project.id))
    assert (row["priority"], row["status"], row["target_date"]) == ("high", "in_progress", "2026-12-20")


@pytest.mark.contract
@pytest.mark.django_db
def test_external_validation(api_key_client, workspace, project):
    url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/"
    assert api_key_client.patch(url, {"priority": "critical"}, format="json").status_code == 400
    assert api_key_client.patch(url, {"status": "done"}, format="json").status_code == 400
    bad = api_key_client.patch(url, {"start_date": "2027-01-10", "target_date": "2027-01-01"}, format="json")
    assert bad.status_code == 400
    # Only the target changes: still checked against the stored start date.
    api_key_client.patch(url, {"start_date": "2027-01-10"}, format="json")
    assert api_key_client.patch(url, {"target_date": "2027-01-01"}, format="json").status_code == 400


@pytest.mark.contract
@pytest.mark.django_db
def test_app_api(session_client, workspace, project):
    url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/"
    patched = session_client.patch(
        url, {"status": "paused", "priority": "low", "target_date": "2027-02-01"}, format="json"
    )
    assert patched.status_code == status.HTTP_200_OK, patched.data
    project.refresh_from_db()
    assert (project.status, project.priority, str(project.target_date)) == ("paused", "low", "2027-02-01")
    listed = session_client.get(f"/api/workspaces/{workspace.slug}/projects/").data
    row = next(p for p in listed if str(p["id"]) == str(project.id))
    assert row["status"] == "paused"


@pytest.mark.contract
@pytest.mark.django_db
def test_explicit_completed_at_wins(api_key_client, workspace, project):
    done = State.objects.create(name="Done", project=project, workspace=workspace, group="completed")
    State.objects.create(name="Todo", project=project, workspace=workspace, group="unstarted", default=True)
    base = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/"

    created = api_key_client.post(
        base,
        {"name": "Imported", "state": str(done.id), "completed_at": "2026-11-16T10:00:00Z"},
        format="json",
    )
    assert created.status_code == status.HTTP_201_CREATED, created.data
    issue = Issue.objects.get(pk=created.data["id"])
    assert issue.completed_at.isoformat().startswith("2026-11-16T10:00:00")

    other = Issue.objects.create(name="Done later", project=project, workspace=workspace)
    patched = api_key_client.patch(
        f"{base}{other.id}/", {"state": str(done.id), "completed_at": "2026-11-15T08:30:00Z"}, format="json"
    )
    assert patched.status_code == status.HTTP_200_OK, patched.data
    other.refresh_from_db()
    assert other.completed_at.isoformat().startswith("2026-11-15T08:30:00")

    # Without completed_at the state change stamps the current time as before.
    third = Issue.objects.create(name="Normal", project=project, workspace=workspace)
    api_key_client.patch(f"{base}{third.id}/", {"state": str(done.id)}, format="json")
    third.refresh_from_db()
    assert third.completed_at is not None and third.completed_at.year >= 2026
