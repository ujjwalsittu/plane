# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Teams (teamspaces) through the external API (SDK paths) and the app API: members, projects,
the team's work and workload, and the team PQL filter."""

import pytest
from rest_framework import status

from plane.db.models import (
    Issue,
    IssueAssignee,
    Project,
    ProjectMember,
    State,
    Teamspace,
    User,
    WorkspaceMember,
)

PAGE_KEYS = {"results", "total_count", "next_cursor", "prev_cursor", "count", "total_pages", "total_results"}


@pytest.fixture
def people(workspace):
    users = []
    for name in ("ana", "ben", "cy"):
        user = User.objects.create(email=f"{name}@plane.so", username=name, display_name=name)
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
        users.append(user)
    return users


@pytest.fixture
def projects(workspace, create_user):
    made = []
    for name, identifier in (("Alpha", "ALP"), ("Beta", "BET")):
        project = Project.objects.create(name=name, identifier=identifier, workspace=workspace, created_by=create_user)
        ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
        made.append(project)
    return made


def _issue(project, name, group, assignees=()):
    state = State.objects.filter(project=project, group=group).first() or State.objects.create(
        name=group.title(), group=group, project=project, workspace=project.workspace
    )
    issue = Issue.objects.create(name=name, project=project, workspace=project.workspace, state=state)
    for user in assignees:
        IssueAssignee.objects.create(issue=issue, assignee=user, project=project, workspace=project.workspace)
    return issue


@pytest.mark.contract
@pytest.mark.django_db
def test_team_crud_members_projects(api_key_client, workspace, people, projects):
    base = f"/api/v1/workspaces/{workspace.slug}/teamspaces"
    ana, ben, cy = people
    created = api_key_client.post(
        base, {"name": "Platform", "description_html": "<p>Infra and tools</p>", "lead": str(ana.id)}, format="json"
    )
    assert created.status_code == status.HTTP_201_CREATED, created.data
    team = created.data
    assert team["lead"] == str(ana.id) and team["member_ids"] == [str(ana.id)]
    assert team["description_stripped"] == "Infra and tools"
    assert api_key_client.post(base, {"name": "platform"}, format="json").status_code == 409
    assert api_key_client.post(base, {}, format="json").status_code == 400
    outsider = User.objects.create(email="out@plane.so", username="out")
    assert api_key_client.post(base, {"name": "X", "lead": str(outsider.id)}, format="json").status_code == 400

    listed = api_key_client.get(base).data
    assert PAGE_KEYS <= set(listed) and listed["results"][0]["id"] == team["id"]
    one = f"{base}/{team['id']}"
    assert api_key_client.patch(one, {"name": "Platform team"}, format="json").data["name"] == "Platform team"

    # Members: add, list (paginated users), refuse outsiders, never remove the lead.
    added = api_key_client.post(f"{one}/members", {"member_ids": [str(ben.id), str(cy.id)]}, format="json")
    assert added.status_code == 201 and {u["id"] for u in added.data} == {str(ben.id), str(cy.id)}
    api_key_client.post(f"{one}/members/", {"member_ids": [str(ben.id)]}, format="json")
    members = api_key_client.get(f"{one}/members").data
    assert PAGE_KEYS <= set(members) and {u["display_name"] for u in members["results"]} == {"ana", "ben", "cy"}
    assert api_key_client.post(f"{one}/members", {"member_ids": [str(outsider.id)]}, format="json").status_code == 400
    assert api_key_client.delete(f"{one}/members", {"member_ids": [str(ana.id)]}, format="json").status_code == 400
    assert api_key_client.delete(f"{one}/members", {"member_ids": [str(cy.id)]}, format="json").status_code == 204

    # Projects.
    alpha, beta = projects
    assert api_key_client.post(f"{one}/projects", {"project_ids": [str(alpha.id)]}, format="json").status_code == 201
    listed_projects = api_key_client.get(f"{one}/projects").data
    assert [p["identifier"] for p in listed_projects["results"]] == ["ALP"]
    assert api_key_client.delete(f"{one}/projects", {"project_ids": [str(alpha.id)]}, format="json").status_code == 204
    assert api_key_client.get(one).data["project_ids"] == []

    # Changing the lead adds them to the team.
    api_key_client.patch(one, {"lead": str(cy.id)}, format="json")
    assert str(cy.id) in api_key_client.get(one).data["member_ids"]

    assert api_key_client.delete(one).status_code == 204
    assert not Teamspace.objects.exists()


@pytest.mark.contract
@pytest.mark.django_db
def test_team_work_workload_and_pql(api_key_client, session_client, workspace, people, projects):
    ana, ben, cy = people
    alpha, beta = projects
    team = session_client.post(
        f"/api/workspaces/{workspace.slug}/teamspaces/", {"name": "Core", "lead": str(ana.id)}, format="json"
    ).data
    session_client.post(
        f"/api/workspaces/{workspace.slug}/teamspaces/{team['id']}/members/",
        {"member_ids": [str(ben.id)]},
        format="json",
    )
    a1 = _issue(alpha, "A1", "started", [ana])
    a5 = _issue(alpha, "A5", "unstarted", [ana, ben])
    a2 = _issue(alpha, "A2", "completed", [ben])
    _issue(alpha, "A3", "unstarted", [cy])  # cy is not on the team
    unassigned = _issue(alpha, "A4", "backlog")
    b1 = _issue(beta, "B1", "unstarted", [ben])

    base = f"/api/workspaces/{workspace.slug}/teamspaces/{team['id']}"
    # Without projects the team's work is everything assigned to its members.
    rows = session_client.get(f"{base}/work-items/").data["results"]
    assert {r["name"] for r in rows} == {"A1", "A2", "A5", "B1"}
    assert session_client.get(f"{base}/work-items/?view=unassigned").data["results"] == []

    # Scoped to Alpha.
    session_client.post(f"{base}/projects/", {"project_ids": [str(alpha.id)]}, format="json")
    rows = session_client.get(f"{base}/work-items/").data["results"]
    assert {r["id"] for r in rows} == {str(a1.id), str(a2.id), str(a5.id)}
    open_rows = session_client.get(f"{base}/work-items/?state_group=backlog,unstarted,started").data["results"]
    assert {r["name"] for r in open_rows} == {"A1", "A5"} and open_rows[0]["project_identifier"] == "ALP"
    assert {r["name"] for r in session_client.get(f"{base}/work-items/?member_id={ben.id}").data["results"]} == {
        "A2",
        "A5",
    }
    assert [r["id"] for r in session_client.get(f"{base}/work-items/?view=unassigned").data["results"]] == [
        str(unassigned.id)
    ]

    workload = session_client.get(f"{base}/workload/").data
    by_member = {row["member_id"]: row for row in workload["members"]}
    assert by_member[str(ana.id)] == {"member_id": str(ana.id), "open": 2, "started": 1, "completed": 0}
    assert by_member[str(ben.id)]["completed"] == 1 and by_member[str(ben.id)]["open"] == 1
    assert workload["unassigned_open"] == 1

    # PQL: team = "<id>" lists work assigned to team members.
    pql = f'team = "{team["id"]}"'
    alpha_rows = api_key_client.get(
        f"/api/v1/workspaces/{workspace.slug}/projects/{alpha.id}/work-items/", {"pql": pql}
    ).data["results"]
    assert {r["name"] for r in alpha_rows} == {"A1", "A2", "A5"}
    beta_rows = api_key_client.get(
        f"/api/v1/workspaces/{workspace.slug}/projects/{beta.id}/work-items/", {"pql": pql}
    ).data["results"]
    assert [str(r["id"]) for r in beta_rows] == [str(b1.id)]


@pytest.mark.contract
@pytest.mark.django_db
def test_guests_read_only_and_feature_flag(session_client, api_client, api_key_client, workspace):
    team = session_client.post(f"/api/workspaces/{workspace.slug}/teamspaces/", {"name": "Ops"}, format="json").data
    guest = User.objects.create(email="guest@plane.so", username="guest")
    WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
    api_client.force_authenticate(user=guest)
    url = f"/api/workspaces/{workspace.slug}/teamspaces/{team['id']}/"
    assert api_client.get(url).status_code == 200
    assert api_client.patch(url, {"name": "x"}, format="json").status_code == 403
    assert api_key_client.get(f"/api/v1/workspaces/{workspace.slug}/features/").data["teams"] is True
