# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Releases, tags and labels through the external API (SDK/MCP paths) and the app API."""

import pytest
from rest_framework import status

from plane.db.models import Issue, Project, ProjectMember, Release, ReleaseLabelLink, State, User, WorkspaceMember


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Alpha", identifier="ALP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


def _base(workspace):
    return f"/api/v1/workspaces/{workspace.slug}/releases"


PAGE_KEYS = {"results", "total_count", "next_cursor", "prev_cursor", "count", "total_pages", "total_results"}


@pytest.mark.contract
@pytest.mark.django_db
def test_tags_and_labels(api_key_client, workspace):
    base = _base(workspace)
    tag = api_key_client.post(f"{base}/tags/", {"version": "v1.0.0", "git_tag": "v1.0.0"}, format="json")
    assert tag.status_code == status.HTTP_201_CREATED and tag.data["version"] == "v1.0.0"
    assert api_key_client.post(f"{base}/tags/", {"version": "V1.0.0"}, format="json").status_code == 409
    assert api_key_client.post(f"{base}/tags/", {}, format="json").status_code == 400
    listed = api_key_client.get(f"{base}/tags/")
    assert PAGE_KEYS <= set(listed.data) and listed.data["results"][0]["id"] == tag.data["id"]
    updated = api_key_client.patch(f"{base}/tags/{tag.data['id']}/", {"commit_hash": "abc123"}, format="json")
    assert updated.data["commit_hash"] == "abc123" and updated.data["version"] == "v1.0.0"

    label = api_key_client.post(f"{base}/labels/", {"name": "backend", "color": "#4E5355"}, format="json")
    assert label.status_code == 201 and label.data["color"] == "#4E5355"
    assert api_key_client.get(f"{base}/labels").data["results"][0]["name"] == "backend"
    assert (
        api_key_client.patch(f"{base}/labels/{label.data['id']}/", {"name": "api"}, format="json").data["name"] == "api"
    )
    assert api_key_client.delete(f"{base}/labels/{label.data['id']}/").status_code == 204
    assert api_key_client.delete(f"{base}/tags/{tag.data['id']}/").status_code == 204


@pytest.mark.contract
@pytest.mark.django_db
def test_release_lifecycle(api_key_client, workspace, project, create_user):
    base = _base(workspace)
    tag = api_key_client.post(f"{base}/tags/", {"version": "v2.0.0"}, format="json").data
    label = api_key_client.post(f"{base}/labels/", {"name": "major"}, format="json").data
    created = api_key_client.post(
        f"{base}/",
        {
            "name": "Spring release",
            "description_html": "<p>Big <b>one</b></p>",
            "release_date": "2026-12-15",
            "tag": tag["id"],
            "lead": str(create_user.id),
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    release = created.data
    assert release["status"] == "unreleased" and release["tag_version"] == "v2.0.0"
    assert release["description"]["description_stripped"] == "Big one" and release["is_latest"] is False
    one = f"{base}/{release['id']}"

    for bad in ({"status": "shipped"}, {"release_date": "soon"}, {"tag": "00000000-0000-0000-0000-000000000000"}):
        assert api_key_client.patch(f"{one}/", bad, format="json").status_code == 400, bad
    outsider = User.objects.create(email="out@plane.so", username="out")
    assert api_key_client.patch(f"{one}/", {"lead": str(outsider.id)}, format="json").status_code == 400

    # Changelog: created empty with the release.
    changelog = api_key_client.get(f"{one}/changelog/")
    assert changelog.status_code == 200 and changelog.data["changelog"]["description_html"] == "<p></p>"
    saved = api_key_client.patch(f"{one}/changelog/", {"description_html": "<ul><li>Fixed X</li></ul>"}, format="json")
    assert saved.data["changelog"]["description_stripped"] == "Fixed X"

    # Labels attached to the release.
    assert api_key_client.post(f"{one}/labels/", {"label_ids": [label["id"]]}, format="json").status_code == 201
    api_key_client.post(f"{one}/labels/", {"label_ids": [label["id"]]}, format="json")
    assert ReleaseLabelLink.objects.count() == 1
    assert api_key_client.get(f"{one}/labels/").data["results"][0]["id"] == label["id"]

    # Work items and progress.
    done = State.objects.create(name="Done", group="completed", project=project, workspace=workspace)
    todo = State.objects.create(name="Todo", group="unstarted", project=project, workspace=workspace)
    items = [
        Issue.objects.create(name=f"Item {n}", project=project, workspace=workspace, state=state)
        for n, state in enumerate((done, todo))
    ]
    ids = [str(item.id) for item in items]
    assert api_key_client.post(f"{one}/work-items/", {"work_item_ids": ids}, format="json").status_code == 201
    page = api_key_client.get(f"{one}/work-items/").data
    assert PAGE_KEYS <= set(page)
    assert {row["id"] for row in page["results"]} == set(ids)
    assert page["results"][0]["project_identifier"] == "ALP"
    assert api_key_client.get(f"{one}/").data["progress"] == {"total": 2, "completed": 1, "cancelled": 0, "percent": 50}

    # Releasing stamps today's date if none is set, and the latest release is flagged.
    api_key_client.patch(f"{one}/", {"release_date": None}, format="json")
    released = api_key_client.patch(f"{one}/", {"status": "released"}, format="json").data
    assert released["status"] == "released" and released["release_date"] and released["is_latest"] is True
    listed = api_key_client.get(f"{base}/").data
    assert PAGE_KEYS <= set(listed) and listed["results"][0]["is_latest"] is True

    assert api_key_client.delete(f"{one}/work-items/", {"work_item_ids": ids[:1]}, format="json").status_code == 204
    assert api_key_client.delete(f"{one}/labels/", {"label_ids": [label["id"]]}, format="json").status_code == 204
    assert api_key_client.delete(f"{one}/").status_code == 204
    assert not Release.objects.exists()


@pytest.mark.contract
@pytest.mark.django_db
def test_app_api_and_guest_access(session_client, api_client, workspace):
    created = session_client.post(f"/api/workspaces/{workspace.slug}/releases/", {"name": "Web"}, format="json")
    assert created.status_code == 201
    guest = User.objects.create(email="guest@plane.so", username="guest")
    WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
    api_client.force_authenticate(user=guest)
    url = f"/api/workspaces/{workspace.slug}/releases/{created.data['id']}/"
    assert api_client.get(url).status_code == 200
    assert api_client.patch(url, {"name": "x"}, format="json").status_code == 403
