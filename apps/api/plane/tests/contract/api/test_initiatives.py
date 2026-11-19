# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Initiatives through the external API (SDK/MCP paths) and the app API."""

import pytest
from rest_framework import status

from plane.db.models import (
    Initiative,
    InitiativeProject,
    Issue,
    Project,
    ProjectMember,
    State,
    User,
    Workspace,
    WorkspaceMember,
)


@pytest.fixture
def projects(workspace, create_user):
    made = []
    for name, identifier in (("Alpha", "ALP"), ("Beta", "BET")):
        project = Project.objects.create(name=name, identifier=identifier, workspace=workspace, created_by=create_user)
        ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
        made.append(project)
    return made


def _states(project):
    return {
        group: State.objects.create(name=group.title(), group=group, project=project, workspace=project.workspace)
        for group in ("backlog", "started", "completed", "cancelled")
    }


def _base(workspace):
    return f"/api/v1/workspaces/{workspace.slug}/initiatives"


@pytest.mark.contract
@pytest.mark.django_db
@pytest.mark.parametrize("slash", ["", "/"])
def test_crud_and_feature_flag(api_key_client, workspace, create_user, slash):
    features = api_key_client.get(f"/api/v1/workspaces/{workspace.slug}/features/")
    assert features.data["initiatives"] is True
    assert (
        api_key_client.patch(
            f"/api/v1/workspaces/{workspace.slug}/features/", {"initiatives": True}, format="json"
        ).status_code
        == 200
    )

    created = api_key_client.post(
        _base(workspace) + slash,
        {
            "name": "Launch v2",
            "description_html": "<p>Ship <b>it</b></p>",
            "start_date": "2026-12-01",
            "end_date": "2027-01-31",
            "state": "PLANNED",
            "lead": str(create_user.id),
        },
        format="json",
    )
    assert created.status_code == status.HTTP_201_CREATED, created.data
    data = created.data
    assert (
        data["state"] == "PLANNED" and data["description_stripped"] == "Ship it" and data["lead"] == str(create_user.id)
    )
    assert data["progress"]["total"] == 0 and data["logo_props"] == {}

    listed = api_key_client.get(_base(workspace) + slash)
    assert [row["name"] for row in listed.data["results"]] == ["Launch v2"]

    one = f"{_base(workspace)}/{data['id']}"
    assert api_key_client.patch(one + slash, {"state": "active"}, format="json").data["state"] == "ACTIVE"
    for bad in ({"state": "DONE"}, {"end_date": "2026-11-01"}, {"name": ""}, {"start_date": "soon"}):
        assert api_key_client.patch(one, bad, format="json").status_code == 400, bad
    outsider = User.objects.create(email="out@plane.so", username="out")
    assert api_key_client.patch(one, {"lead": str(outsider.id)}, format="json").status_code == 400

    assert api_key_client.delete(one + slash).status_code == 204
    assert api_key_client.get(one).status_code == 404


@pytest.mark.contract
@pytest.mark.django_db
def test_projects_work_items_and_progress(api_key_client, workspace, projects):
    alpha, beta = projects
    alpha_states, beta_states = _states(alpha), _states(beta)
    for group in ("completed", "completed", "started", "cancelled"):
        Issue.objects.create(name=group, project=alpha, workspace=workspace, state=alpha_states[group])
    epic = Issue.objects.create(name="Epic in beta", project=beta, workspace=workspace, state=beta_states["completed"])
    Issue.objects.create(name="Other beta item", project=beta, workspace=workspace, state=beta_states["backlog"])

    initiative = api_key_client.post(_base(workspace), {"name": "Grow"}, format="json").data
    one = f"{_base(workspace)}/{initiative['id']}"

    added = api_key_client.post(f"{one}/projects", {"project_ids": [str(alpha.id)]}, format="json")
    assert added.status_code == 201 and str(added.data[0]["id"]) == str(alpha.id)
    # Re-adding is a no-op; a project of another workspace is refused.
    api_key_client.post(f"{one}/projects", {"project_ids": [str(alpha.id)]}, format="json")
    assert InitiativeProject.objects.count() == 1
    other_ws = Workspace.objects.create(name="Other", slug="other-ws", owner=workspace.owner)
    foreign = Project.objects.create(name="F", identifier="FOR", workspace=other_ws)
    assert api_key_client.post(f"{one}/projects", {"project_ids": [str(foreign.id)]}, format="json").status_code == 400

    # The SDK's older /epics spelling takes epic_ids.
    assert api_key_client.post(f"{one}/epics", {"epic_ids": [str(epic.id)]}, format="json").status_code == 201
    work_items = api_key_client.get(f"{one}/work-items")
    assert [str(row["id"]) for row in work_items.data["results"]] == [str(epic.id)]

    progress = api_key_client.get(one).data["progress"]
    # Alpha: 2 completed, 1 started, 1 cancelled; plus the completed epic from Beta.
    assert progress["total"] == 5 and progress["completed"] == 3 and progress["cancelled"] == 1
    assert progress["percent"] == 75

    projects_page = api_key_client.get(f"{one}/projects")
    assert [str(row["id"]) for row in projects_page.data["results"]] == [str(alpha.id)]

    assert (
        api_key_client.delete(f"{one}/work-items", {"work_item_ids": [str(epic.id)]}, format="json").status_code == 204
    )
    assert api_key_client.delete(f"{one}/projects", {"project_ids": [str(alpha.id)]}, format="json").status_code == 204
    assert api_key_client.get(one).data["progress"]["total"] == 0


@pytest.mark.contract
@pytest.mark.django_db
def test_app_api_and_permissions(session_client, api_client, workspace):
    created = session_client.post(f"/api/workspaces/{workspace.slug}/initiatives/", {"name": "From web"}, format="json")
    assert created.status_code == 201
    initiative_id = created.data["id"]
    assert (
        session_client.get(f"/api/workspaces/{workspace.slug}/initiatives/").data["results"][0]["id"] == initiative_id
    )

    guest = User.objects.create(email="guest@plane.so", username="guest")
    WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
    api_client.force_authenticate(user=guest)
    assert api_client.get(f"/api/workspaces/{workspace.slug}/initiatives/{initiative_id}/").status_code == 200
    assert (
        api_client.patch(
            f"/api/workspaces/{workspace.slug}/initiatives/{initiative_id}/", {"name": "x"}, format="json"
        ).status_code
        == 403
    )
    assert Initiative.objects.get(pk=initiative_id).name == "From web"
