# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Pages linked to work items, in the external API (SDK/MCP) and the app API (web)."""

from uuid import uuid4

import pytest
from rest_framework import status

from plane.db.models import Issue, IssuePage, Page, Project, ProjectMember, ProjectPage, User, WorkspaceMember


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Links", identifier="LNK", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def issue(project):
    return Issue.objects.create(name="Build it", project=project, workspace=project.workspace)


def _page(workspace, project, owner, **kwargs):
    page = Page.objects.create(workspace=workspace, owned_by=owner, name=kwargs.pop("name", "Spec"), **kwargs)
    ProjectPage.objects.create(project=project, page=page, workspace=workspace)
    return page


def _url(workspace, project, issue, suffix=""):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/{issue.id}/pages{suffix}"


@pytest.mark.contract
@pytest.mark.django_db
@pytest.mark.parametrize("slash", ["", "/"])
def test_link_list_retrieve_unlink(api_key_client, workspace, project, issue, create_user, slash):
    page = _page(workspace, project, create_user, name="Design doc")

    created = api_key_client.post(_url(workspace, project, issue) + slash, {"page_id": str(page.id)}, format="json")
    assert created.status_code == status.HTTP_201_CREATED, created.data
    assert created.data["page"]["id"] == str(page.id)
    assert created.data["page"]["name"] == "Design doc"
    assert created.data["issue"] == str(issue.id)
    link_id = created.data["id"]

    again = api_key_client.post(_url(workspace, project, issue) + slash, {"page_id": str(page.id)}, format="json")
    assert again.status_code == status.HTTP_200_OK
    assert again.data["id"] == link_id
    assert IssuePage.objects.filter(issue=issue).count() == 1

    listed = api_key_client.get(_url(workspace, project, issue) + slash)
    assert listed.status_code == status.HTTP_200_OK
    assert [link["id"] for link in listed.data["results"]] == [link_id]

    one = api_key_client.get(_url(workspace, project, issue, f"/{link_id}") + slash)
    assert one.data["page"]["name"] == "Design doc"

    gone = api_key_client.delete(_url(workspace, project, issue, f"/{link_id}") + slash)
    assert gone.status_code == status.HTTP_204_NO_CONTENT
    assert api_key_client.get(_url(workspace, project, issue)).data["results"] == []
    assert Page.objects.filter(pk=page.id).exists()


@pytest.mark.contract
@pytest.mark.django_db
def test_link_validation(api_key_client, workspace, project, issue, create_user):
    url = _url(workspace, project, issue)
    assert api_key_client.post(url, {}, format="json").status_code == 400
    assert api_key_client.post(url, {"page_id": str(uuid4())}, format="json").status_code == 400

    other_project = Project.objects.create(name="Else", identifier="ELS", workspace=workspace)
    elsewhere = _page(workspace, other_project, create_user)
    assert api_key_client.post(url, {"page_id": str(elsewhere.id)}, format="json").status_code == 400

    missing = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/{uuid4()}/pages"
    assert api_key_client.get(missing).status_code == 404


@pytest.mark.contract
@pytest.mark.django_db
def test_private_pages_of_others_are_hidden(api_key_client, workspace, project, issue):
    other = User.objects.create(email=f"o-{uuid4().hex[:8]}@plane.so", username=uuid4().hex[:8])
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
    private = _page(workspace, project, other, access=Page.PRIVATE_ACCESS)
    url = _url(workspace, project, issue)
    assert api_key_client.post(url, {"page_id": str(private.id)}, format="json").status_code == 400

    IssuePage.objects.create(issue=issue, page=private, project=project)
    assert api_key_client.get(url).data["results"] == []


@pytest.mark.contract
@pytest.mark.django_db
def test_app_api(session_client, workspace, project, issue, create_user):
    page = _page(workspace, project, create_user, name="Runbook")
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/pages/"
    created = session_client.post(base, {"page_id": str(page.id)}, format="json")
    assert created.status_code == status.HTTP_201_CREATED, created.data
    assert [link["page"]["name"] for link in session_client.get(base).data] == ["Runbook"]
    assert session_client.delete(f"{base}{created.data['id']}/").status_code == status.HTTP_204_NO_CONTENT
    assert session_client.get(base).data == []
