# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Work item, page and project templates through the external API (SDK/MCP paths) and the app API,
and creating things from them."""

import pytest
from rest_framework import status

from plane.db.models import (
    Issue,
    Label,
    Page,
    Project,
    ProjectMember,
    ProjectPage,
    State,
    Template,
    User,
    WorkspaceMember,
)


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Alpha", identifier="ALP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    State.objects.create(name="Backlog", group="backlog", project=project, workspace=workspace, default=True)
    State.objects.create(name="In Review", group="started", project=project, workspace=workspace)
    Label.objects.create(name="Bug", project=project, workspace=workspace)
    return project


@pytest.mark.contract
@pytest.mark.django_db
def test_workspace_templates_sdk_shape(api_key_client, workspace, project):
    base = f"/api/v1/workspaces/{workspace.slug}"
    created = api_key_client.post(
        f"{base}/workitems/templates/",
        {
            "name": "Bug report",
            "description_html": "<p>For bugs</p>",
            "template_data": {"name": "Bug: ", "priority": "high", "labels": ["bug"]},
        },
        format="json",
    )
    assert created.status_code == status.HTTP_201_CREATED, created.data
    tid = created.data["id"]
    assert created.data["project"] is None and created.data["template_type"] == "workitem"
    assert created.data["description"] == "For bugs"

    # Bad bodies are refused.
    for bad in ({"name": "x", "template_data": {"priority": "asap"}}, {"name": "", "template_data": {}}):
        assert api_key_client.post(f"{base}/workitems/templates/", bad, format="json").status_code == 400

    # Update merges template_data; a null drops a key.
    updated = api_key_client.patch(
        f"{base}/workitems/templates/{tid}/", {"template_data": {"state": "In Review", "labels": None}}, format="json"
    )
    assert updated.data["template_data"] == {"name": "Bug: ", "priority": "high", "state": "In Review"}

    # Project-scoped templates: the project path lists them alone, the workspace path is the wider view.
    in_project = api_key_client.post(
        f"{base}/projects/{project.id}/workitems/templates/",
        {"name": "Spike", "short_description": "Timeboxed research", "template_data": {"priority": "low"}},
        format="json",
    )
    assert in_project.status_code == 201 and in_project.data["project"] == str(project.id)
    assert in_project.data["short_description"] == "Timeboxed research"
    only = api_key_client.get(f"{base}/projects/{project.id}/workitems/templates/").data
    assert [row["name"] for row in only] == ["Spike"]
    wide = api_key_client.get(f"{base}/workitems/templates/").data
    assert {row["name"] for row in wide} == {"Bug report", "Spike"}
    # The SDK's project update path has no trailing slash.
    no_slash = api_key_client.patch(
        f"{base}/projects/{project.id}/workitems/templates/{in_project.data['id']}", {"name": "Spike!"}, format="json"
    )
    assert no_slash.status_code == 200 and no_slash.data["name"] == "Spike!"

    # Pages and projects; a project kind cannot live inside a project (no route for it).
    page = api_key_client.post(
        f"{base}/pages/templates/",
        {"name": "Retro", "template_data": {"description_html": "<h2>Wins</h2>"}},
        format="json",
    )
    assert page.status_code == 201
    proj = api_key_client.post(
        f"{base}/projects/templates/",
        {"name": "Product", "description": "A product team", "template_data": {"features": {"cycles": True}}},
        format="json",
    )
    assert proj.status_code == 201 and proj.data["description"] == "A product team"
    assert api_key_client.get(f"{base}/projects/templates/").data[0]["id"] == proj.data["id"]
    bad_project = api_key_client.post(
        f"{base}/projects/templates/",
        {"name": "x", "template_data": {"states": [{"name": "Done", "group": "x"}]}},
        format="json",
    )
    assert bad_project.status_code == 400

    assert api_key_client.delete(f"{base}/workitems/templates/{tid}/").status_code == 204
    assert api_key_client.get(f"{base}/workitems/templates/{tid}/").status_code == 404


@pytest.mark.contract
@pytest.mark.django_db
def test_use_work_item_and_page_templates(session_client, workspace, project, create_user, monkeypatch):
    monkeypatch.setattr("plane.bgtasks.issue_activities_task.issue_activity.delay", lambda *a, **k: None)
    monkeypatch.setattr("plane.bgtasks.page_transaction_task.page_transaction.delay", lambda *a, **k: None)
    base = f"/api/workspaces/{workspace.slug}/templates"
    created = session_client.post(
        f"{base}/",
        {
            "kind": "workitem",
            "name": "Feature",
            "template_data": {
                "description_html": "<p>Context</p>",
                "priority": "medium",
                "state": "In Review",
                "labels": ["BUG", "missing"],
                "assignees": [create_user.email],
                "sub_work_items": ["Design", {"name": "Build", "priority": "high"}],
            },
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    used = session_client.post(
        f"{base}/{created.data['id']}/use/", {"project_id": str(project.id), "name": "Dark mode"}, format="json"
    )
    assert used.status_code == 201, used.data
    issue = Issue.objects.get(pk=used.data["id"])
    assert used.data["identifier"] == f"ALP-{issue.sequence_id}"
    assert issue.name == "Dark mode" and issue.priority == "medium" and issue.state.name == "In Review"
    assert issue.description_html == "<p>Context</p>"
    assert list(issue.labels.values_list("name", flat=True)) == ["Bug"]
    assert list(issue.assignees.values_list("id", flat=True)) == [create_user.id]
    children = Issue.objects.filter(parent=issue).order_by("sequence_id")
    assert [(c.name, c.priority) for c in children] == [("Design", "none"), ("Build", "high")]

    assert session_client.post(f"{base}/{created.data['id']}/use/", {}, format="json").status_code == 400

    # The web PATCH replaces template_data rather than merging.
    replaced = session_client.patch(
        f"{base}/{created.data['id']}/", {"template_data": {"priority": "low"}}, format="json"
    )
    assert replaced.data["template_data"] == {"priority": "low"}

    page_template = session_client.post(
        f"{base}/",
        {
            "kind": "page",
            "name": "Retro",
            "project_id": str(project.id),
            "template_data": {"description_html": "<p>Hi</p>"},
        },
        format="json",
    )
    assert page_template.status_code == 201 and page_template.data["project"] == str(project.id)
    page = session_client.post(f"{base}/{page_template.data['id']}/use/", {}, format="json")
    assert page.status_code == 201, page.data
    made = Page.objects.get(pk=page.data["id"])
    assert made.name == "Retro" and made.description_html == "<p>Hi</p>"
    assert ProjectPage.objects.filter(page=made, project=project).exists()

    listed = session_client.get(f"{base}/?kind=page").data
    assert [row["id"] for row in listed] == [page_template.data["id"]]


@pytest.mark.contract
@pytest.mark.django_db
def test_use_project_template(session_client, workspace, create_user, monkeypatch):
    monkeypatch.setattr("plane.bgtasks.issue_activities_task.issue_activity.delay", lambda *a, **k: None)
    monkeypatch.setattr("plane.bgtasks.page_transaction_task.page_transaction.delay", lambda *a, **k: None)
    base = f"/api/workspaces/{workspace.slug}/templates"
    created = session_client.post(
        f"{base}/",
        {
            "kind": "project",
            "name": "Product team",
            "template_data": {
                "description": "Ship things",
                "network": 0,
                "features": {"cycles": True, "modules": False},
                "states": [
                    {"name": "Ideas", "group": "backlog", "color": "#111111"},
                    {"name": "Doing", "group": "started"},
                    {"name": "Shipped", "group": "completed"},
                ],
                "labels": ["frontend", {"name": "backend", "color": "#222222"}],
                "work_items": [{"name": "Kickoff", "state": "Doing", "labels": ["frontend"]}],
                "pages": [{"name": "Charter", "description_html": "<p>Why</p>"}],
            },
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    tid = created.data["id"]
    assert session_client.post(f"{base}/{tid}/use/", {"name": "Mobile"}, format="json").status_code == 400
    used = session_client.post(f"{base}/{tid}/use/", {"name": "Mobile", "identifier": "mob"}, format="json")
    assert used.status_code == 201, used.data
    project = Project.objects.get(pk=used.data["project_id"])
    assert project.identifier == "MOB" and project.description == "Ship things" and project.network == 0
    assert project.cycle_view is True and project.module_view is False
    assert ProjectMember.objects.filter(project=project, member=create_user, role=20).exists()
    states = State.all_state_objects.filter(project=project)
    assert set(states.values_list("name", flat=True)) == {"Ideas", "Doing", "Shipped", "Triage"}
    assert states.get(default=True).name == "Ideas"
    assert set(Label.objects.filter(project=project).values_list("name", flat=True)) == {"frontend", "backend"}
    kickoff = Issue.objects.get(project=project)
    assert kickoff.name == "Kickoff" and kickoff.state.name == "Doing"
    assert list(kickoff.labels.values_list("name", flat=True)) == ["frontend"]
    assert Page.objects.filter(projects=project, name="Charter").exists()

    again = session_client.post(f"{base}/{tid}/use/", {"name": "Other", "identifier": "MOB"}, format="json")
    assert again.status_code == 409


@pytest.mark.contract
@pytest.mark.django_db
def test_guest_and_project_scope_access(session_client, api_client, workspace, project):
    base = f"/api/workspaces/{workspace.slug}/templates"
    ws = session_client.post(f"{base}/", {"kind": "page", "name": "Notes"}, format="json").data
    scoped = session_client.post(
        f"{base}/", {"kind": "workitem", "name": "Scoped", "project_id": str(project.id)}, format="json"
    ).data
    assert (
        session_client.post(
            f"{base}/", {"kind": "project", "name": "x", "project_id": str(project.id)}, format="json"
        ).status_code
        == 400
    )

    guest = User.objects.create(email="guest@plane.so", username="guest")
    WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
    api_client.force_authenticate(user=guest)
    assert api_client.get(f"{base}/{ws['id']}/").status_code == 200
    assert api_client.patch(f"{base}/{ws['id']}/", {"name": "y"}, format="json").status_code == 403

    # A workspace member outside the project neither sees nor uses its templates.
    member = User.objects.create(email="member@plane.so", username="member")
    WorkspaceMember.objects.create(workspace=workspace, member=member, role=15)
    api_client.force_authenticate(user=member)
    assert {row["id"] for row in api_client.get(f"{base}/").data} == {ws["id"]}
    assert api_client.get(f"{base}/{scoped['id']}/").status_code == 404
    assert api_client.post(f"{base}/{ws['id']}/use/", {"project_id": str(project.id)}, format="json").status_code == 403
    assert Template.objects.count() == 2
