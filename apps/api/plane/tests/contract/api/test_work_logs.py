# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Work logs (time tracking), in minutes, through the external API and the app API."""

from uuid import uuid4

import pytest
from rest_framework import status

from plane.db.models import Issue, IssueWorkLog, Project, ProjectMember, User, WorkspaceMember


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(
        name="Time", identifier="TIM", workspace=workspace, created_by=create_user, is_time_tracking_enabled=True
    )
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def issue(project):
    return Issue.objects.create(name="Work", project=project, workspace=project.workspace)


def _url(workspace, project, issue, suffix=""):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/{issue.id}/worklogs{suffix}"


@pytest.mark.contract
@pytest.mark.django_db
@pytest.mark.parametrize("slash", ["", "/"])
def test_log_list_update_delete_and_summary(api_key_client, workspace, project, issue, create_user, slash):
    created = api_key_client.post(
        _url(workspace, project, issue) + slash, {"duration": 90, "description": "Setup"}, format="json"
    )
    assert created.status_code == status.HTTP_201_CREATED, created.data
    assert created.data["duration"] == 90 and created.data["logged_by"] == str(create_user.id)
    api_key_client.post(_url(workspace, project, issue), {"duration": 30}, format="json")

    listed = api_key_client.get(_url(workspace, project, issue) + slash).data
    assert sorted(log["duration"] for log in listed) == [30, 90]

    log_id = created.data["id"]
    patched = api_key_client.patch(
        _url(workspace, project, issue, f"/{log_id}") + slash, {"duration": 120}, format="json"
    )
    assert patched.status_code == 200 and patched.data["duration"] == 120

    summary = api_key_client.get(f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/total-worklogs" + slash)
    assert summary.data == [{"issue_id": str(issue.id), "duration": 150}]

    assert api_key_client.delete(_url(workspace, project, issue, f"/{log_id}") + slash).status_code == 204
    assert IssueWorkLog.objects.filter(issue=issue).count() == 1


@pytest.mark.contract
@pytest.mark.django_db
def test_validation_and_feature_switch(api_key_client, workspace, project, issue):
    url = _url(workspace, project, issue)
    for bad in ({}, {"duration": 0}, {"duration": -5}, {"duration": "60"}, {"duration": 1.5}, {"duration": 20000}):
        assert api_key_client.post(url, bad, format="json").status_code == 400, bad
    project.is_time_tracking_enabled = False
    project.save()
    off = api_key_client.post(url, {"duration": 10}, format="json")
    assert off.status_code == 400 and "Time tracking is off" in off.data["error"]
    missing = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/{uuid4()}/worklogs"
    assert api_key_client.get(missing).status_code == 404


@pytest.mark.contract
@pytest.mark.django_db
def test_only_author_or_admin_edits(session_client, workspace, project, issue):
    other = User.objects.create(email=f"o-{uuid4().hex[:8]}@plane.so", username=uuid4().hex[:8])
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
    ProjectMember.objects.create(project=project, member=other, workspace=workspace, role=15)
    theirs = IssueWorkLog.objects.create(issue=issue, project=project, logged_by=other, duration=15)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/work-logs/"
    # The session user is a project admin (role 20), so they may edit someone else's entry.
    assert session_client.patch(f"{base}{theirs.id}/", {"duration": 20}, format="json").status_code == 200

    ProjectMember.objects.filter(project=project, role=20).update(role=15)
    assert session_client.patch(f"{base}{theirs.id}/", {"duration": 25}, format="json").status_code == 403
    assert session_client.delete(f"{base}{theirs.id}/").status_code == 403
    mine = session_client.post(base, {"duration": 45, "description": "Review"}, format="json")
    assert mine.status_code == 201, mine.data
    assert session_client.delete(f"{base}{mine.data['id']}/").status_code == 204
    summary = session_client.get(f"/api/workspaces/{workspace.slug}/projects/{project.id}/work-log-summary/").data
    assert summary == [{"issue_id": str(issue.id), "duration": 20}]
