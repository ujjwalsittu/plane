# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Project overview (home page) and project tags, in both APIs."""

from uuid import uuid4

import pytest
from rest_framework import status

from plane.db.models import Page, Project, ProjectMember, ProjectPage, ProjectTag, User, WorkspaceMember


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Home", identifier="HOME", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


def _page(workspace, project, owner, **kwargs):
    page = Page.objects.create(workspace=workspace, owned_by=owner, name=kwargs.pop("name", "Doc"), **kwargs)
    ProjectPage.objects.create(project=project, page=page, workspace=workspace)
    return page


@pytest.mark.contract
@pytest.mark.django_db
def test_external_overview_markdown_pages_and_tags(api_key_client, workspace, project, create_user):
    url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/overview"
    assert api_key_client.get(url).data["overview_html"] == "<p></p>"

    doc = _page(workspace, project, create_user, name="Architecture")
    tag = api_key_client.post(
        f"/api/v1/workspaces/{workspace.slug}/project-tags", {"name": "Gov", "color": "#f00"}, format="json"
    )
    assert tag.status_code == status.HTTP_201_CREATED, tag.data
    assert (
        api_key_client.post(
            f"/api/v1/workspaces/{workspace.slug}/project-tags", {"name": "gov"}, format="json"
        ).status_code
        == 400
    )

    updated = api_key_client.patch(
        url,
        {
            "overview_markdown": "# OSMG\n\n```mermaid\ngraph TD; A-->B\n```",
            "overview_page_ids": [str(doc.id)],
            "tag_ids": [tag.data["id"]],
        },
        format="json",
    )
    assert updated.status_code == status.HTTP_200_OK, updated.data
    assert "<h1>OSMG</h1>" in updated.data["overview_html"]
    assert 'class="language-mermaid"' in updated.data["overview_html"]
    assert updated.data["linked_pages"] == [
        {"id": str(doc.id), "name": "Architecture", "access": 0, "archived_at": None}
    ]
    assert updated.data["tags"] == [{"id": tag.data["id"], "name": "Gov", "color": "#f00"}]

    as_markdown = api_key_client.get(url, {"markdown": "true"})
    assert as_markdown.data["overview_markdown"].startswith("# OSMG")


@pytest.mark.contract
@pytest.mark.django_db
def test_overview_validation(api_key_client, workspace, project):
    url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/overview"
    assert api_key_client.patch(url, {"overview_page_ids": [str(uuid4())]}, format="json").status_code == 400
    assert api_key_client.patch(url, {"tag_ids": [str(uuid4())]}, format="json").status_code == 400
    sanitized = api_key_client.patch(url, {"overview_html": "<p>ok</p><script>x()</script>"}, format="json")
    assert "<script" not in sanitized.data["overview_html"]


@pytest.mark.contract
@pytest.mark.django_db
def test_private_pages_of_others_are_not_linked_or_shown(api_key_client, workspace, project):
    other = User.objects.create(email=f"o-{uuid4().hex[:8]}@plane.so", username=uuid4().hex[:8])
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
    private = _page(workspace, project, other, access=Page.PRIVATE_ACCESS)
    url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/overview"
    assert api_key_client.patch(url, {"overview_page_ids": [str(private.id)]}, format="json").status_code == 400
    project.overview_page_ids = [str(private.id)]
    project.save()
    assert api_key_client.get(url).data["linked_pages"] == []


@pytest.mark.contract
@pytest.mark.django_db
def test_app_overview_and_tags(session_client, workspace, project):
    tag = session_client.post(f"/api/workspaces/{workspace.slug}/project-tags/", {"name": "Infra"}, format="json")
    assert tag.status_code == status.HTTP_201_CREATED, tag.data
    renamed = session_client.patch(
        f"/api/workspaces/{workspace.slug}/project-tags/{tag.data['id']}/", {"name": "Platform"}, format="json"
    )
    assert renamed.data["name"] == "Platform"
    url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/overview/"
    patched = session_client.patch(url, {"overview_html": "<h2>Hi</h2>", "tag_ids": [tag.data["id"]]}, format="json")
    assert patched.status_code == status.HTTP_200_OK, patched.data
    assert session_client.get(url).data["tags"][0]["name"] == "Platform"
    deleted = session_client.delete(f"/api/workspaces/{workspace.slug}/project-tags/{tag.data['id']}/")
    assert deleted.status_code == status.HTTP_204_NO_CONTENT
    assert not ProjectTag.objects.filter(pk=tag.data["id"]).exists()
    assert session_client.get(url).data["tags"] == []
