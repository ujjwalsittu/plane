# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""v1 milestones, work item types, feature flags and the pql subset, in the
shapes the Plane SDK / MCP server use."""

from unittest import mock

import pytest
from rest_framework import status

from plane.db.models import Issue, IssueType, Milestone, Project, ProjectIssueType, ProjectMember


@pytest.fixture(autouse=True)
def _no_side_effects(db):
    with (
        mock.patch("plane.utils.milestone.issue_activity"),
        mock.patch("plane.api.views.milestone.base_host", return_value="http://testserver"),
        mock.patch("plane.api.views.issue.issue_activity"),
        mock.patch("plane.api.views.issue.base_host", return_value="http://testserver"),
    ):
        yield


def _project(workspace, owner, identifier):
    project = Project.objects.create(name=identifier, identifier=identifier, workspace=workspace, created_by=owner)
    ProjectMember.objects.create(project=project, member=owner, workspace=workspace, role=20)
    return project


@pytest.fixture
def project(workspace, create_user):
    return _project(workspace, create_user, "MIL")


@pytest.fixture
def other_project(workspace, create_user):
    return _project(workspace, create_user, "OTH")


def _issue(project, name, **kwargs):
    return Issue.objects.create(name=name, project=project, workspace=project.workspace, **kwargs)


def _url(workspace, project, suffix):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/{suffix}"


# --- milestones ---------------------------------------------------------------


@pytest.mark.contract
@pytest.mark.django_db
@pytest.mark.parametrize("slash", ["", "/"])
def test_milestone_crud(api_key_client, workspace, project, slash):
    base = _url(workspace, project, "milestones")
    created = api_key_client.post(
        f"{base}{slash}",
        {"title": "M0 Foundations", "target_date": "2026-12-31", "external_source": "spec", "external_id": "M0"},
        format="json",
    )
    assert created.status_code == status.HTTP_201_CREATED, created.data
    milestone_id = str(created.data["id"])
    assert created.data["total_issues"] == 0

    listed = api_key_client.get(f"{base}{slash}")
    assert listed.status_code == status.HTTP_200_OK
    assert [str(m["id"]) for m in listed.data["results"]] == [milestone_id]
    assert listed.data["next_page_results"] is False

    updated = api_key_client.patch(f"{base}/{milestone_id}{slash}", {"title": "M0"}, format="json")
    assert updated.status_code == status.HTTP_200_OK
    assert updated.data["title"] == "M0"

    assert api_key_client.get(f"{base}/{milestone_id}{slash}").data["title"] == "M0"
    assert api_key_client.delete(f"{base}/{milestone_id}{slash}").status_code == status.HTTP_204_NO_CONTENT
    assert not Milestone.objects.filter(pk=milestone_id).exists()


@pytest.mark.contract
@pytest.mark.django_db
def test_duplicate_external_id_is_409(api_key_client, workspace, project):
    base = _url(workspace, project, "milestones")
    body = {"title": "M1", "external_source": "spec", "external_id": "M1"}
    first = api_key_client.post(base, body, format="json")
    second = api_key_client.post(base, body, format="json")
    assert second.status_code == status.HTTP_409_CONFLICT
    assert str(second.data["id"]) == str(first.data["id"])


@pytest.mark.contract
@pytest.mark.django_db
def test_title_is_required(api_key_client, workspace, project):
    response = api_key_client.post(_url(workspace, project, "milestones"), {"title": "  "}, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.contract
@pytest.mark.django_db
def test_milestone_work_items_add_list_remove(api_key_client, workspace, project, other_project):
    milestone = Milestone.objects.create(title="M2", project=project, workspace=workspace)
    a, b = _issue(project, "A"), _issue(project, "B")
    stranger = _issue(other_project, "Stranger")
    base = _url(workspace, project, f"milestones/{milestone.id}/work-items")

    missing = api_key_client.post(base, {"issues": [str(a.id), str(stranger.id)]}, format="json")
    assert missing.status_code == status.HTTP_404_NOT_FOUND
    assert not Issue.objects.filter(milestone=milestone).exists()

    added = api_key_client.post(base, {"issues": [str(a.id), str(b.id)]}, format="json")
    assert added.status_code == status.HTTP_204_NO_CONTENT
    listed = api_key_client.get(base).data["results"]
    assert {row["issue"] for row in listed} == {str(a.id), str(b.id)}
    assert all(row["milestone"] == str(milestone.id) for row in listed)
    progress = api_key_client.get(_url(workspace, project, f"milestones/{milestone.id}")).data
    assert progress["total_issues"] == 2

    removed = api_key_client.delete(base, {"issues": [str(a.id)]}, format="json")
    assert removed.status_code == status.HTTP_204_NO_CONTENT
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.milestone_id is None and b.milestone_id == milestone.id


@pytest.mark.contract
@pytest.mark.django_db
def test_work_item_milestone_via_patch_and_delete_clears(api_key_client, workspace, project, other_project):
    milestone = Milestone.objects.create(title="M3", project=project, workspace=workspace)
    foreign = Milestone.objects.create(title="X", project=other_project, workspace=workspace)
    item = _issue(project, "Item")
    url = _url(workspace, project, f"work-items/{item.id}/")

    rejected = api_key_client.patch(url, {"milestone_id": str(foreign.id)}, format="json")
    assert rejected.status_code == status.HTTP_400_BAD_REQUEST

    accepted = api_key_client.patch(url, {"milestone_id": str(milestone.id)}, format="json")
    assert accepted.status_code == status.HTTP_200_OK, accepted.data
    item.refresh_from_db()
    assert item.milestone_id == milestone.id

    api_key_client.delete(_url(workspace, project, f"milestones/{milestone.id}"))
    item.refresh_from_db()
    assert item.milestone_id is None


# --- work item types -------------------------------------------------------------


@pytest.mark.contract
@pytest.mark.django_db
def test_type_lifecycle(api_key_client, workspace, project, other_project):
    base = _url(workspace, project, "work-item-types")
    assert api_key_client.get(base).data == []

    created = api_key_client.post(base, {"name": "Epic", "is_epic": True}, format="json")
    assert created.status_code == status.HTTP_201_CREATED, created.data
    type_id = str(created.data["id"])
    assert created.data["is_epic"] is True
    assert created.data["project_ids"] == [str(project.id)]
    project.refresh_from_db()
    assert project.is_issue_type_enabled

    assert api_key_client.post(base, {"name": "epic"}, format="json").status_code == status.HTTP_409_CONFLICT
    assert [str(t["id"]) for t in api_key_client.get(base).data] == [type_id]
    # Not linked to the other project.
    assert api_key_client.get(_url(workspace, other_project, "work-item-types")).data == []

    item = api_key_client.post(
        _url(workspace, project, "work-items/"), {"name": "Big thing", "type_id": type_id}, format="json"
    )
    assert item.status_code == status.HTTP_201_CREATED, item.data
    assert str(Issue.objects.get(pk=item.data["id"]).type_id) == type_id

    wrong_project = api_key_client.post(
        _url(workspace, other_project, "work-items/"), {"name": "Nope", "type_id": type_id}, format="json"
    )
    assert wrong_project.status_code == status.HTTP_400_BAD_REQUEST

    renamed = api_key_client.patch(f"{base}/{type_id}", {"name": "Initiative"}, format="json")
    assert renamed.data["name"] == "Initiative"

    assert api_key_client.delete(f"{base}/{type_id}").status_code == status.HTTP_204_NO_CONTENT
    assert Issue.objects.get(pk=item.data["id"]).type_id is None
    assert not IssueType.objects.filter(pk=type_id).exists()


@pytest.mark.contract
@pytest.mark.django_db
def test_workspace_types_and_import(api_key_client, workspace, project):
    created = api_key_client.post(
        f"/api/v1/workspaces/{workspace.slug}/work-item-types/", {"name": "Story"}, format="json"
    )
    assert created.status_code == status.HTTP_201_CREATED, created.data
    type_id = str(created.data["id"])
    assert created.data["project_ids"] == []

    imported = api_key_client.post(
        _url(workspace, project, "import-work-item-types"), {"work_item_types": [type_id]}, format="json"
    )
    assert imported.status_code == status.HTTP_204_NO_CONTENT
    assert ProjectIssueType.objects.filter(project=project, issue_type_id=type_id).exists()
    listed = api_key_client.get(f"/api/v1/workspaces/{workspace.slug}/work-item-types/").data
    assert listed[0]["project_ids"] == [str(project.id)]


# --- features -------------------------------------------------------------------


@pytest.mark.contract
@pytest.mark.django_db
def test_project_features_and_epics_toggle(api_key_client, workspace, project):
    url = _url(workspace, project, "features")
    features = api_key_client.get(url).data
    assert features["epics"] is False and features["work_item_types"] is False
    assert features["workflows"] is False

    turned_on = api_key_client.patch(url, {"epics": True, "modules": True, "milestones": True}, format="json")
    assert turned_on.status_code == status.HTTP_200_OK
    assert turned_on.data["epics"] and turned_on.data["work_item_types"] and turned_on.data["modules"]
    project.refresh_from_db()
    assert project.module_view and project.milestone_view and project.is_issue_type_enabled
    assert IssueType.objects.filter(project_issue_types__project=project, is_epic=True).count() == 1

    # Idempotent: no second Epic type.
    api_key_client.patch(url, {"epics": True}, format="json")
    assert IssueType.objects.filter(project_issue_types__project=project, is_epic=True).count() == 1

    refused = api_key_client.patch(url, {"workflows": True}, format="json")
    assert refused.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.contract
@pytest.mark.django_db
def test_workspace_features_keep_types_per_project(api_key_client, workspace):
    url = f"/api/v1/workspaces/{workspace.slug}/features"
    assert api_key_client.get(url).data["work_item_types"] is False
    assert api_key_client.patch(url, {"work_item_types": True}, format="json").status_code == 400


@pytest.mark.contract
@pytest.mark.django_db
def test_mcp_resolve_epic_sequence(api_key_client, workspace, project):
    """What the MCP's `workitem_type resolve` does for "Epic" in a fresh project."""
    types_url = _url(workspace, project, "work-item-types")
    assert not [t for t in api_key_client.get(types_url).data if t["name"] == "Epic"]
    assert api_key_client.get(f"/api/v1/workspaces/{workspace.slug}/features").data["work_item_types"] is False
    features_url = _url(workspace, project, "features")
    if not api_key_client.get(features_url).data["work_item_types"]:
        assert api_key_client.patch(features_url, {"work_item_types": True}, format="json").status_code == 200
    created = api_key_client.post(types_url, {"name": "Epic"}, format="json")
    assert created.status_code == status.HTTP_201_CREATED


# --- pql subset and id filters -------------------------------------------------


@pytest.fixture
def typed_tree(workspace, project):
    epic_type = IssueType.objects.create(workspace=workspace, name="Epic", is_epic=True)
    ProjectIssueType.objects.create(project=project, workspace=workspace, issue_type=epic_type)
    epic = _issue(project, "Epic", type=epic_type)
    child = _issue(project, "Child", parent=epic)
    loose = _issue(project, "Loose")
    return epic_type, epic, child, loose


def _names(response):
    return {item["name"] for item in response.data["results"]}


@pytest.mark.contract
@pytest.mark.django_db
def test_pql_type_and_child_of(api_key_client, workspace, project, typed_tree):
    epic_type, epic, child, loose = typed_tree
    url = _url(workspace, project, "work-items/")

    by_type = api_key_client.get(url, {"pql": f'type = "{epic_type.id}"'})
    assert by_type.status_code == status.HTTP_200_OK, by_type.data
    assert _names(by_type) == {"Epic"}

    children = api_key_client.get(url, {"pql": f'childOf("{project.identifier}-{epic.sequence_id}")'})
    assert _names(children) == {"Child"}

    combined = api_key_client.get(
        url, {"pql": f'childOf("{project.identifier}-{epic.sequence_id}") AND type IN ("{epic_type.id}")'}
    )
    assert _names(combined) == set()

    assert _names(api_key_client.get(url, {"type_id": str(epic_type.id)})) == {"Epic"}


@pytest.mark.contract
@pytest.mark.django_db
@pytest.mark.parametrize("pql", ['priority = "high"', 'type = "not-a-uuid"', 'type = "x" OR', 'childOf("NOPE")'])
def test_unsupported_pql_is_400_with_guidance(api_key_client, workspace, project, pql):
    response = api_key_client.get(_url(workspace, project, "work-items/"), {"pql": pql})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Supported" in response.data["pql"]
