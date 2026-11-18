# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""v1 project pages, in the shapes the Plane SDK / MCP server use."""

from unittest import mock
from uuid import uuid4

import pytest
from rest_framework import status

from plane.db.models import Page, Project, ProjectMember, ProjectPage, User, WorkspaceMember


@pytest.fixture(autouse=True)
def _no_side_effects(db):
    with mock.patch("plane.api.views.page.page_transaction"):
        yield


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(
        name="Docs", identifier="DOC", workspace=workspace, created_by=create_user, page_view=True
    )
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


def _url(workspace, project, suffix=""):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/pages{suffix}"


def _make_page(workspace, project, owner, **kwargs):
    page = Page.objects.create(workspace=workspace, owned_by=owner, name=kwargs.pop("name", "P"), **kwargs)
    ProjectPage.objects.create(project=project, page=page, workspace=workspace)
    return page


@pytest.mark.contract
@pytest.mark.django_db
@pytest.mark.parametrize("slash", ["", "/"])
def test_create_list_retrieve(api_key_client, workspace, project, slash):
    created = api_key_client.post(
        f"{_url(workspace, project)}{slash}",
        {
            "name": "Architecture",
            "description_html": "<h1>Overview</h1><p>Hello</p>",
            "external_source": "spec",
            "external_id": "DOC-1",
        },
        format="json",
    )
    assert created.status_code == status.HTTP_201_CREATED, created.data
    page = Page.objects.get(pk=created.data["id"])
    assert page.description_binary is None  # the live server builds it from the HTML
    assert "<h1>Overview</h1>" in page.description_html
    assert page.external_id == "DOC-1"
    assert created.data["projects"] == [str(project.id)]

    listed = api_key_client.get(f"{_url(workspace, project)}{slash}")
    assert [p["id"] for p in listed.data["results"]] == [created.data["id"]]
    retrieved = api_key_client.get(f"{_url(workspace, project)}/{page.id}{slash}")
    assert retrieved.data["name"] == "Architecture"

    duplicate = api_key_client.post(
        _url(workspace, project),
        {"name": "Again", "description_html": "<p>x</p>", "external_source": "spec", "external_id": "DOC-1"},
        format="json",
    )
    assert duplicate.status_code == status.HTTP_409_CONFLICT
    assert duplicate.data["id"] == created.data["id"]


@pytest.mark.contract
@pytest.mark.django_db
def test_html_is_sanitised(api_key_client, workspace, project):
    created = api_key_client.post(
        _url(workspace, project),
        {"name": "Unsafe", "description_html": '<p>ok</p><script>alert(1)</script><img src=x onerror="alert(1)">'},
        format="json",
    )
    assert created.status_code == status.HTTP_201_CREATED, created.data
    html = Page.objects.get(pk=created.data["id"]).description_html
    assert "<script" not in html and "onerror" not in html


@pytest.mark.contract
@pytest.mark.django_db
def test_update_html_clears_the_editor_document(api_key_client, workspace, project, create_user):
    page = _make_page(workspace, project, create_user, description_html="<p>old</p>", description_binary=b"yjs")
    url = f"{_url(workspace, project)}/{page.id}"

    renamed = api_key_client.put(url, {"name": "Renamed"}, format="json")
    assert renamed.status_code == status.HTTP_200_OK, renamed.data
    page.refresh_from_db()
    assert page.name == "Renamed" and bytes(page.description_binary) == b"yjs"

    updated = api_key_client.put(url, {"description_html": "<p>new</p>"}, format="json")
    assert updated.status_code == status.HTTP_200_OK
    page.refresh_from_db()
    assert page.description_html == "<p>new</p>"
    assert page.description_binary is None
    assert page.description_stripped == "new"


@pytest.mark.contract
@pytest.mark.django_db
def test_locked_page_refuses_edits_until_unlocked(api_key_client, workspace, project, create_user):
    page = _make_page(workspace, project, create_user, is_locked=True)
    url = f"{_url(workspace, project)}/{page.id}"
    assert api_key_client.put(url, {"name": "x"}, format="json").status_code == status.HTTP_400_BAD_REQUEST
    assert api_key_client.put(url, {"is_locked": False}, format="json").status_code == status.HTTP_200_OK
    assert api_key_client.put(url, {"name": "x"}, format="json").status_code == status.HTTP_200_OK


@pytest.mark.contract
@pytest.mark.django_db
def test_archive_then_delete(api_key_client, workspace, project, create_user):
    page = _make_page(workspace, project, create_user)
    child = _make_page(workspace, project, create_user, name="Child", parent=page)
    url = f"{_url(workspace, project)}/{page.id}"

    assert api_key_client.delete(url).status_code == status.HTTP_400_BAD_REQUEST  # not archived yet
    assert api_key_client.post(f"{url}/archive").status_code == status.HTTP_204_NO_CONTENT
    child.refresh_from_db()
    assert child.archived_at is not None
    assert api_key_client.get(_url(workspace, project)).data["results"] == []
    archived = api_key_client.get(_url(workspace, project), {"archived": "true"}).data["results"]
    assert {p["id"] for p in archived} == {str(page.id), str(child.id)}

    assert api_key_client.delete(f"{url}/archive").status_code == status.HTTP_204_NO_CONTENT
    page.refresh_from_db()
    assert page.archived_at is None

    api_key_client.post(f"{url}/archive")
    assert api_key_client.delete(url).status_code == status.HTTP_204_NO_CONTENT
    assert not Page.objects.filter(pk=page.pk).exists()


@pytest.mark.contract
@pytest.mark.django_db
def test_private_pages_of_others_are_hidden(api_key_client, workspace, project):
    other = User.objects.create(email=f"o-{uuid4().hex[:8]}@plane.so", username=uuid4().hex[:8])
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
    ProjectMember.objects.create(project=project, member=other, workspace=workspace, role=15)
    private = _make_page(workspace, project, other, access=Page.PRIVATE_ACCESS)
    assert api_key_client.get(_url(workspace, project)).data["results"] == []
    assert api_key_client.get(f"{_url(workspace, project)}/{private.id}").status_code in (403, 404)


@pytest.mark.contract
@pytest.mark.django_db
def test_parent_page_must_be_in_the_project(api_key_client, workspace, project, create_user):
    parent = _make_page(workspace, project, create_user)
    child = api_key_client.post(
        _url(workspace, project),
        {"name": "Child", "description_html": "<p>c</p>", "parent_id": str(parent.id)},
        format="json",
    )
    assert child.status_code == status.HTTP_201_CREATED, child.data
    assert child.data["parent_id"] == str(parent.id)
    stray = api_key_client.post(
        _url(workspace, project),
        {"name": "Stray", "description_html": "<p>c</p>", "parent_id": str(uuid4())},
        format="json",
    )
    assert stray.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.contract
@pytest.mark.django_db
def test_unavailable_routes_explain_themselves(api_key_client, workspace, project, create_user):
    workspace_pages = api_key_client.get(f"/api/v1/workspaces/{workspace.slug}/pages")
    assert workspace_pages.status_code == status.HTTP_400_BAD_REQUEST
    assert "project_id" in workspace_pages.data["error"]
