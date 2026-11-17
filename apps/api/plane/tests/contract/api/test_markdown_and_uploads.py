# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Markdown in and out of the external API, and direct inline image upload."""

import base64
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status

from plane.db.models import FileAsset, Issue, IssueComment, Page, Project, ProjectMember
from plane.utils.markdown import html_to_markdown, looks_like_markdown, markdown_to_html

ASSET = "35e8b958-1111-2222-3333-444455556666"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


# --- conversion ------------------------------------------------------------


@pytest.mark.unit
def test_markdown_to_editor_html():
    html = markdown_to_html(
        f"# Title\n\n- [x] done\n- [ ] todo\n\n![diagram](asset:{ASSET})\n\n```mermaid\ngraph TD; A-->B\n```\n"
    )
    assert "<h1>Title</h1>" in html
    assert 'data-type="taskList"' in html and 'data-checked="true"' in html
    assert f'<image-component alignment="left" alt="diagram" src="{ASSET}" status="uploaded">' in html
    assert "<p><image-component" not in html
    assert 'class="language-mermaid"' in html


@pytest.mark.unit
def test_round_trip_back_to_markdown():
    markdown = html_to_markdown(
        markdown_to_html(f"# Title\n\n- [x] done\n\n![d](asset:{ASSET})\n\n```mermaid\nA-->B\n```\n")
    )
    assert markdown.startswith("# Title")
    assert "- [x] done" in markdown
    assert f"![d](asset:{ASSET})" in markdown
    assert "```mermaid" in markdown


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,expected",
    [("# hi", True), ("plain words", True), ("<p>hi</p>", False), ("", False), (None, False), ("a < b", True)],
)
def test_looks_like_markdown(text, expected):
    assert looks_like_markdown(text) is expected


# --- API ---------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_side_effects(db):
    with (
        mock.patch("plane.api.views.issue.issue_activity"),
        mock.patch("plane.api.views.issue.base_host", return_value="http://testserver"),
        mock.patch("plane.api.views.page.page_transaction"),
    ):
        yield


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="MD", identifier="MD", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


def _base(workspace, project):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}"


@pytest.mark.contract
@pytest.mark.django_db
@pytest.mark.parametrize("field", ["description_html", "description_markdown"])
def test_work_item_accepts_markdown(api_key_client, workspace, project, field):
    response = api_key_client.post(
        f"{_base(workspace, project)}/work-items/",
        {"name": "MD item", field: "## Goal\n\n- [ ] ship it"},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    html = Issue.objects.get(pk=response.data["id"]).description_html
    assert "<h2>Goal</h2>" in html and 'data-type="taskList"' in html


@pytest.mark.contract
@pytest.mark.django_db
def test_html_is_left_as_html(api_key_client, workspace, project):
    response = api_key_client.post(
        f"{_base(workspace, project)}/work-items/",
        {"name": "HTML", "description_html": "<p># not a heading</p>"},
        format="json",
    )
    assert "<h1>" not in Issue.objects.get(pk=response.data["id"]).description_html


@pytest.mark.contract
@pytest.mark.django_db
def test_comment_markdown_and_sanitising(api_key_client, workspace, project):
    issue = Issue.objects.create(name="C", project=project, workspace=workspace)
    url = f"{_base(workspace, project)}/work-items/{issue.id}/comments/"
    markdown = api_key_client.post(url, {"comment_markdown": "**Looks good**"}, format="json")
    assert markdown.status_code == status.HTTP_201_CREATED, markdown.data
    assert "<strong>Looks good</strong>" in IssueComment.objects.get(pk=markdown.data["id"]).comment_html

    unsafe = api_key_client.post(url, {"comment_html": "<p>hi</p><script>alert(1)</script>"}, format="json")
    assert unsafe.status_code == status.HTTP_201_CREATED, unsafe.data
    assert "<script" not in IssueComment.objects.get(pk=unsafe.data["id"]).comment_html


@pytest.mark.contract
@pytest.mark.django_db
def test_page_accepts_markdown(api_key_client, workspace, project):
    response = api_key_client.post(
        f"{_base(workspace, project)}/pages", {"name": "Doc", "description_html": "# Doc\n\nBody"}, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    assert "<h1>Doc</h1>" in Page.objects.get(pk=response.data["id"]).description_html


@pytest.mark.contract
@pytest.mark.django_db
def test_markdown_on_read(api_key_client, workspace, project):
    issue = Issue.objects.create(
        name="R", project=project, workspace=workspace, description_html="<h2>Read me</h2><p><strong>bold</strong></p>"
    )
    plain = api_key_client.get(f"{_base(workspace, project)}/work-items/{issue.id}/")
    assert "description_markdown" not in plain.data
    with_md = api_key_client.get(f"{_base(workspace, project)}/work-items/{issue.id}/", {"markdown": "true"})
    assert with_md.data["description_markdown"].startswith("## Read me")
    listed = api_key_client.get(f"{_base(workspace, project)}/work-items/", {"markdown": "true"})
    assert listed.data["results"][0]["description_markdown"].startswith("## Read me")


# --- inline upload --------------------------------------------------------------


@pytest.mark.contract
@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["multipart", "base64", "data-uri"])
def test_inline_upload(api_key_client, workspace, project, mode):
    issue = Issue.objects.create(name="U", project=project, workspace=workspace)
    url = f"{_base(workspace, project)}/assets/inline"
    with mock.patch("plane.api.views.inline_asset.S3Storage.upload_file", return_value=True) as upload:
        if mode == "multipart":
            response = api_key_client.post(
                url,
                {
                    "file": SimpleUploadedFile("chart.png", PNG, content_type="image/png"),
                    "entity_type": "ISSUE_DESCRIPTION",
                    "entity_id": str(issue.id),
                },
                format="multipart",
            )
        elif mode == "base64":
            response = api_key_client.post(
                url, {"name": "chart.png", "type": "image/png", "data": base64.b64encode(PNG).decode()}, format="json"
            )
        else:
            data_uri = "data:image/png;base64," + base64.b64encode(PNG).decode()
            response = api_key_client.post(url, {"name": "chart.png", "data": data_uri}, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.data
    asset = FileAsset.objects.get(pk=response.data["id"])
    assert asset.is_uploaded and asset.project_id == project.id and asset.size == len(PNG)
    assert response.data["html"].startswith(f'<image-component src="{asset.id}"')
    assert response.data["markdown"].endswith(f"(asset:{asset.id})")
    assert upload.call_args.args[2] == "image/png"
    if mode == "multipart":
        assert asset.issue_id == issue.id


@pytest.mark.contract
@pytest.mark.django_db
@pytest.mark.parametrize(
    "body,expected",
    [
        ({"name": "x.svg", "type": "image/svg+xml", "data": base64.b64encode(b"<svg/>").decode()}, 400),
        ({"name": "x.png", "type": "image/png", "data": "not base64!!"}, 400),
        ({"name": "x.png", "type": "image/png"}, 400),
        (
            {
                "name": "x.png",
                "type": "image/png",
                "data": base64.b64encode(PNG).decode(),
                "entity_type": "ISSUE_DESCRIPTION",
                "entity_id": ASSET,
            },
            404,
        ),
    ],
)
def test_inline_upload_rejections(api_key_client, workspace, project, body, expected):
    with mock.patch("plane.api.views.inline_asset.S3Storage.upload_file", return_value=True):
        response = api_key_client.post(f"{_base(workspace, project)}/assets/inline", body, format="json")
    assert response.status_code == expected, response.data
    assert not FileAsset.objects.filter(project=project).exists()
