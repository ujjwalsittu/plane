# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""App (web) API for milestones and work item types, and the work item
fields, grouping and activity they add."""

from unittest import mock

import pytest
from rest_framework import status

from plane.bgtasks.issue_activities_task import track_milestone, track_type
from plane.db.models import Issue, IssueType, Milestone, Project, ProjectIssueType, ProjectMember, State


@pytest.fixture(autouse=True)
def _no_side_effects(db):
    with (
        mock.patch("plane.utils.milestone.issue_activity"),
        mock.patch("plane.app.views.issue.base.issue_activity"),
        mock.patch("plane.app.views.milestone.base.base_host", return_value="http://testserver"),
    ):
        yield


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="App", identifier="APP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


def _url(workspace, project, suffix):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/{suffix}"


def _issue(project, name, **kwargs):
    return Issue.objects.create(name=name, project=project, workspace=project.workspace, **kwargs)


@pytest.mark.contract
@pytest.mark.django_db
def test_milestone_progress_counts(session_client, workspace, project):
    created = session_client.post(_url(workspace, project, "milestones/"), {"title": "Beta"}, format="json")
    assert created.status_code == status.HTTP_201_CREATED, created.data
    milestone_id = created.data["id"]
    State.objects.create(name="Todo", group="backlog", default=True, project=project, workspace=workspace)
    done = State.objects.create(name="Done", group="completed", project=project, workspace=workspace)
    a = _issue(project, "A", milestone_id=milestone_id, state=done)
    _issue(project, "B", milestone_id=milestone_id)
    _issue(project, "Archived", milestone_id=milestone_id, archived_at="2026-01-01")

    listed = session_client.get(_url(workspace, project, "milestones/")).data
    assert listed[0]["total_issues"] == 2
    assert listed[0]["completed_issues"] == 1

    removed = session_client.delete(
        _url(workspace, project, f"milestones/{milestone_id}/milestone-issues/"), {"issues": [str(a.id)]}, format="json"
    )
    assert removed.status_code == status.HTTP_204_NO_CONTENT
    a.refresh_from_db()
    assert a.milestone_id is None


@pytest.mark.contract
@pytest.mark.django_db
def test_issue_patch_sets_milestone_and_type_and_lists_return_them(session_client, workspace, project):
    milestone = Milestone.objects.create(title="GA", project=project, workspace=workspace)
    created = session_client.post(
        _url(workspace, project, "issue-types/"), {"name": "Epic", "is_epic": True}, format="json"
    )
    assert created.status_code == status.HTTP_201_CREATED, created.data
    epic_type_id = created.data["id"]
    item = _issue(project, "Item")

    patched = session_client.patch(
        _url(workspace, project, f"issues/{item.id}/"),
        {"milestone_id": str(milestone.id), "type_id": str(epic_type_id)},
        format="json",
    )
    assert patched.status_code == status.HTTP_204_NO_CONTENT, getattr(patched, "data", None)
    item.refresh_from_db()
    assert item.milestone_id == milestone.id
    assert str(item.type_id) == str(epic_type_id)

    detail = session_client.get(_url(workspace, project, f"issues/{item.id}/")).data
    assert str(detail["milestone_id"]) == str(milestone.id)
    assert str(detail["type_id"]) == str(epic_type_id)

    listed = session_client.get(_url(workspace, project, "issues/"), {"group_by": "milestone_id"})
    assert listed.status_code == status.HTTP_200_OK, listed.data
    groups = listed.data["results"]
    assert str(milestone.id) in {str(key) for key in groups}
    assert "None" in {str(key) for key in groups}

    by_type = session_client.get(_url(workspace, project, "issues/"), {"group_by": "type_id"})
    assert by_type.status_code == status.HTTP_200_OK, by_type.data

    filtered = session_client.get(_url(workspace, project, "issues/"), {"milestone": str(milestone.id)})
    assert filtered.status_code == status.HTTP_200_OK


@pytest.mark.contract
@pytest.mark.django_db
def test_type_from_another_project_is_rejected(session_client, workspace, project, create_user):
    other = Project.objects.create(name="Other", identifier="OTH", workspace=workspace, created_by=create_user)
    foreign_type = IssueType.objects.create(workspace=workspace, name="Foreign")
    ProjectIssueType.objects.create(project=other, workspace=workspace, issue_type=foreign_type)
    item = _issue(project, "Item")
    response = session_client.patch(
        _url(workspace, project, f"issues/{item.id}/"), {"type_id": str(foreign_type.id)}, format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.contract
@pytest.mark.django_db
def test_issue_types_admin_only_for_writes(api_client, workspace, project):
    from plane.db.models import User, WorkspaceMember

    member = User.objects.create(email="member-types@plane.so", username="member-types")
    WorkspaceMember.objects.create(workspace=workspace, member=member, role=15)
    ProjectMember.objects.create(project=project, member=member, workspace=workspace, role=15)
    api_client.force_authenticate(user=member)
    assert api_client.get(_url(workspace, project, "issue-types/")).status_code == status.HTTP_200_OK
    refused = api_client.post(_url(workspace, project, "issue-types/"), {"name": "Epic"}, format="json")
    assert refused.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.unit
@pytest.mark.django_db
def test_activity_trackers_record_names(workspace, project, create_user):
    milestone = Milestone.objects.create(title="M9", project=project, workspace=workspace)
    epic = IssueType.objects.create(workspace=workspace, name="Epic", is_epic=True)
    item = _issue(project, "Tracked")
    activities = []
    common = dict(
        issue_id=item.id,
        project_id=project.id,
        workspace_id=workspace.id,
        actor_id=create_user.id,
        issue_activities=activities,
        epoch=1,
    )
    track_milestone(
        requested_data={"milestone_id": str(milestone.id)}, current_instance={"milestone_id": None}, **common
    )
    track_type(requested_data={"type_id": str(epic.id)}, current_instance={"type_id": None}, **common)
    track_type(requested_data={"type_id": str(epic.id)}, current_instance={"type_id": str(epic.id)}, **common)
    assert [(a.field, a.new_value) for a in activities] == [("milestone", "M9"), ("type", "Epic")]
