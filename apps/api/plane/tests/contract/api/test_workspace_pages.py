# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workspace pages and collections through the external API (the SDK/MCP routes)."""

from unittest import mock
from uuid import uuid4

import pytest
from rest_framework import status

from plane.db.models import Page, PageCollectionPage, Project, ProjectPage, User, WorkspaceMember


@pytest.fixture(autouse=True)
def _no_side_effects(db):
    with mock.patch("plane.api.views.workspace_page.page_transaction"):
        yield


def _ws(workspace, suffix=""):
    return f"/api/v1/workspaces/{workspace.slug}{suffix}"


@pytest.fixture
def other_user(workspace):
    user = User.objects.create(email=f"o-{uuid4().hex[:8]}@plane.so", username=uuid4().hex[:8])
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    return user


@pytest.mark.contract
@pytest.mark.django_db
@pytest.mark.parametrize("slash", ["", "/"])
def test_workspace_page_lifecycle(api_key_client, workspace, create_user, slash):
    created = api_key_client.post(
        _ws(workspace, "/pages") + slash, {"name": "Handbook", "description_html": "<p>Hi</p>"}, format="json"
    )
    assert created.status_code == status.HTTP_201_CREATED, created.data
    page_id = created.data["id"]
    assert created.data["projects"] == [] and created.data["collection_id"] is None

    project = Project.objects.create(name="P", identifier="PRJ", workspace=workspace)
    project_page = Page.objects.create(workspace=workspace, owned_by=create_user, name="Project doc")
    ProjectPage.objects.create(project=project, page=project_page, workspace=workspace)
    listed = api_key_client.get(_ws(workspace, "/pages") + slash).data["results"]
    assert [p["name"] for p in listed] == ["Handbook"]  # project pages are not workspace pages

    updated = api_key_client.put(_ws(workspace, f"/pages/{page_id}") + slash, {"name": "Team handbook"}, format="json")
    assert updated.status_code == 200 and updated.data["name"] == "Team handbook"
    child = api_key_client.post(_ws(workspace, "/pages"), {"name": "Onboarding", "parent_id": page_id}, format="json")
    assert child.data["parent_id"] == page_id

    assert api_key_client.delete(_ws(workspace, f"/pages/{page_id}") + slash).status_code == 400
    assert api_key_client.post(_ws(workspace, f"/pages/{page_id}/archive") + slash).status_code == 204
    assert api_key_client.get(_ws(workspace, "/pages"), {"archived": "true"}).data["results"][0]["archived_at"]
    assert api_key_client.delete(_ws(workspace, f"/pages/{page_id}") + slash).status_code == 204


@pytest.mark.contract
@pytest.mark.django_db
def test_collections_file_and_move_pages(api_key_client, workspace):
    first = api_key_client.post(_ws(workspace, "/collections"), {"name": "Engineering"}, format="json")
    assert first.status_code == 201, first.data
    assert first.data["access"] == 0 and first.data["current_user_access"] == 2
    second = api_key_client.post(_ws(workspace, "/collections"), {"name": "Ops"}, format="json").data

    filed = api_key_client.post(
        _ws(workspace, "/pages"), {"name": "Runbook", "collection_id": first.data["id"]}, format="json"
    ).data
    assert filed["collection_id"] == first.data["id"] and filed["page_collection_id"]
    loose = api_key_client.post(_ws(workspace, "/pages"), {"name": "Notes"}, format="json").data

    added = api_key_client.post(
        _ws(workspace, f"/collections/{first.data['id']}/pages"), {"page_ids": [loose["id"]]}, format="json"
    )
    assert added.status_code == 201 and added.data[0]["page"] == loose["id"]
    branch = api_key_client.get(_ws(workspace, f"/collections/{first.data['id']}/pages")).data["results"]
    assert {row["page"]["name"] for row in branch} == {"Runbook", "Notes"}
    found = api_key_client.get(_ws(workspace, f"/collections/{first.data['id']}/pages-search"), {"search": "run"})
    assert [p["name"] for p in found.data] == ["Runbook"]

    # Move the Runbook to Ops by patching its membership.
    moved = api_key_client.patch(
        _ws(workspace, f"/collections/{first.data['id']}/pages/{filed['page_collection_id']}"),
        {"collection": second["id"]},
        format="json",
    )
    assert moved.status_code == 200 and moved.data["collection"] == second["id"]
    assert api_key_client.get(_ws(workspace, f"/pages/{filed['id']}")).data["collection_id"] == second["id"]

    unfiled = api_key_client.delete(_ws(workspace, f"/collections/{second['id']}/pages/{filed['page_collection_id']}"))
    assert unfiled.status_code == 204
    assert Page.objects.filter(pk=filed["id"]).exists()

    # Deleting a collection archives its pages by default, or leaves them unfiled.
    api_key_client.delete(_ws(workspace, f"/collections/{first.data['id']}?archive_pages=false"))
    assert Page.objects.get(pk=loose["id"]).archived_at is None
    assert not PageCollectionPage.objects.filter(page_id=loose["id"]).exists()


@pytest.mark.contract
@pytest.mark.django_db
def test_private_collections_and_members(api_key_client, workspace, create_user, other_user):
    from plane.db.models import PageCollection

    hidden = PageCollection.objects.create(workspace=workspace, name="Secret", owned_by=other_user, access=1)
    page = Page.objects.create(workspace=workspace, owned_by=other_user, name="Secret plan")
    PageCollectionPage.objects.create(workspace=workspace, collection=hidden, page=page)
    assert hidden.name not in {c["name"] for c in api_key_client.get(_ws(workspace, "/collections")).data}
    assert api_key_client.get(_ws(workspace, f"/pages/{page.id}")).status_code == 404

    mine = api_key_client.post(_ws(workspace, "/collections"), {"name": "Mine", "access": 1}, format="json").data
    member = api_key_client.post(
        _ws(workspace, f"/collections/{mine['id']}/members"), {"member": str(other_user.id), "access": 0}, format="json"
    )
    assert member.status_code == 201, member.data
    assert api_key_client.get(_ws(workspace, f"/collections/{mine['id']}/members")).data[0]["access"] == 0
    changed = api_key_client.patch(
        _ws(workspace, f"/collections/{mine['id']}/members/{member.data['id']}"), {"access": 2}, format="json"
    )
    assert changed.data["access"] == 2
    assert (
        api_key_client.patch(_ws(workspace, f"/collections/{mine['id']}"), {"access": 0}, format="json").status_code
        == 400
    )
    assert (
        api_key_client.delete(_ws(workspace, f"/collections/{mine['id']}/members/{member.data['id']}")).status_code
        == 204
    )
    assert (
        api_key_client.post(
            _ws(workspace, f"/collections/{mine['id']}/members"), {"member": str(uuid4()), "access": 0}, format="json"
        ).status_code
        == 400
    )


@pytest.mark.contract
@pytest.mark.django_db
def test_wiki_app_api(session_client, workspace):
    base = f"/api/workspaces/{workspace.slug}/wiki"
    collection = session_client.post(f"{base}/collections/", {"name": "Guides"}, format="json")
    assert collection.status_code == 201, collection.data
    page = session_client.post(
        f"{base}/pages/", {"name": "Style guide", "collection_id": collection.data["id"]}, format="json"
    )
    assert page.status_code == 201, page.data
    listed = session_client.get(f"{base}/pages/").data["results"]
    assert [(p["name"], p["collection_id"]) for p in listed] == [("Style guide", collection.data["id"])]
    saved = session_client.patch(
        f"{base}/pages/{page.data['id']}/", {"description_html": "<p>Use plain words.</p>"}, format="json"
    )
    assert saved.status_code == 200 and "plain words" in saved.data["description_html"]
    assert session_client.post(f"{base}/pages/{page.data['id']}/archive/").status_code == 204
