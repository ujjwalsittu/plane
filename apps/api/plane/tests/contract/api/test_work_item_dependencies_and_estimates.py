# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""v1 routes the Plane SDK / MCP server call for dependencies, built-in
relation definitions, custom relations and estimates."""

from unittest import mock
from uuid import uuid4

import pytest
from django.db.models import Q
from rest_framework import status

from plane.db.models import (
    Estimate,
    EstimatePoint,
    Issue,
    IssueRelation,
    Project,
    ProjectMember,
    User,
    WorkspaceMember,
)


@pytest.fixture(autouse=True)
def _no_side_effects(db):
    with (
        mock.patch("plane.api.views.work_item_relation.issue_activity"),
        mock.patch("plane.api.views.work_item_relation.base_host", return_value="http://testserver"),
        mock.patch("plane.api.views.issue.issue_activity"),
        mock.patch("plane.api.views.issue.base_host", return_value="http://testserver"),
        mock.patch("plane.api.views.project.base_host", return_value="http://testserver", create=True),
    ):
        yield


def _project(workspace, owner, identifier):
    project = Project.objects.create(name=identifier, identifier=identifier, workspace=workspace, created_by=owner)
    ProjectMember.objects.create(project=project, member=owner, workspace=workspace, role=20)
    return project


@pytest.fixture
def project(workspace, create_user):
    return _project(workspace, create_user, "DEP")


def _issue(project, name):
    return Issue.objects.create(name=name, project=project, workspace=project.workspace)


@pytest.fixture
def a(project):
    return _issue(project, "A")


@pytest.fixture
def b(project):
    return _issue(project, "B")


@pytest.fixture
def c(project):
    return _issue(project, "C")


def _base(workspace, project, issue):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/{issue.id}"


def _ids(items):
    return {str(item["id"]) for item in items}


# --- dependencies ---------------------------------------------------------


@pytest.mark.contract
@pytest.mark.django_db
def test_create_blocked_by_and_list_from_both_sides(api_key_client, workspace, project, a, b, c):
    response = api_key_client.post(
        f"{_base(workspace, project, a)}/dependencies/",
        {"relation_type": "blocked_by", "work_item_ids": [str(b.id), str(c.id)]},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert _ids(response.data) == {str(b.id), str(c.id)}
    assert all(item["relation_type"] == "blocked_by" for item in response.data)
    assert IssueRelation.objects.filter(issue=a, related_issue=b, relation_type="blocked_by").exists()

    listed = api_key_client.get(f"{_base(workspace, project, a)}/dependencies/").data
    assert set(listed) == {"blocking", "blocked_by", "start_before", "start_after", "finish_before", "finish_after"}
    assert _ids(listed["blocked_by"]) == {str(b.id), str(c.id)}
    assert listed["blocking"] == []
    first = listed["blocked_by"][0]
    for field in ("id", "name", "sequence_id", "project_id", "state_id", "priority", "label_ids", "assignee_ids"):
        assert field in first

    other_side = api_key_client.get(f"{_base(workspace, project, b)}/dependencies/").data
    assert _ids(other_side["blocking"]) == {str(a.id)}


@pytest.mark.contract
@pytest.mark.django_db
@pytest.mark.parametrize(
    "relation_type,stored,reverse",
    [
        ("blocking", "blocked_by", True),
        ("start_before", "start_before", False),
        ("start_after", "start_before", True),
        ("finish_before", "finish_before", False),
        ("finish_after", "finish_before", True),
    ],
)
def test_each_direction_is_stored_like_the_app(
    api_key_client, workspace, project, a, b, relation_type, stored, reverse
):
    response = api_key_client.post(
        f"{_base(workspace, project, a)}/dependencies/",
        {"relation_type": relation_type, "work_item_ids": [str(b.id)]},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    issue, related = (b, a) if reverse else (a, b)
    assert IssueRelation.objects.filter(issue=issue, related_issue=related, relation_type=stored).exists()
    listed = api_key_client.get(f"{_base(workspace, project, a)}/dependencies/").data
    assert _ids(listed[relation_type]) == {str(b.id)}


@pytest.mark.contract
@pytest.mark.django_db
def test_create_is_idempotent(api_key_client, workspace, project, a, b):
    url = f"{_base(workspace, project, a)}/dependencies/"
    body = {"relation_type": "blocked_by", "work_item_ids": [str(b.id)]}
    api_key_client.post(url, body, format="json")
    response = api_key_client.post(url, body, format="json")
    assert response.status_code == status.HTTP_201_CREATED
    assert IssueRelation.objects.filter(issue=a, related_issue=b).count() == 1


@pytest.mark.contract
@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        {"relation_type": "relates_to", "work_item_ids": ["00000000-0000-0000-0000-000000000000"]},
        {"relation_type": "blocked_by", "work_item_ids": []},
        {"relation_type": "blocked_by", "work_item_ids": ["not-a-uuid"]},
        {"relation_type": "blocked_by"},
    ],
)
def test_invalid_bodies_are_400(api_key_client, workspace, project, a, body):
    response = api_key_client.post(f"{_base(workspace, project, a)}/dependencies/", body, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert IssueRelation.objects.filter(Q(issue=a) | Q(related_issue=a)).count() == 0


@pytest.mark.contract
@pytest.mark.django_db
def test_target_the_caller_cannot_see_is_404_and_writes_nothing(api_key_client, workspace, project, a):
    colleague = User.objects.create(email=f"c-{uuid4().hex[:8]}@plane.so", username=uuid4().hex[:8])
    WorkspaceMember.objects.create(workspace=workspace, member=colleague, role=20)
    hidden = _issue(_project(workspace, colleague, "HID"), "Hidden")

    response = api_key_client.post(
        f"{_base(workspace, project, a)}/dependencies/",
        {"relation_type": "blocked_by", "work_item_ids": [str(hidden.id)]},
        format="json",
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert not IssueRelation.objects.filter(issue=a).exists()


@pytest.mark.contract
@pytest.mark.django_db
def test_url_work_item_outside_url_project_is_404(api_key_client, workspace, project, b):
    other_project = _project(workspace, project.created_by, "OTH")
    stray = _issue(other_project, "Stray")
    response = api_key_client.get(
        f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/{stray.id}/dependencies/"
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.contract
@pytest.mark.django_db
def test_remove_dependency_from_either_side(api_key_client, workspace, project, a, b):
    IssueRelation.objects.create(
        issue=a, related_issue=b, relation_type="blocked_by", project=project, workspace=workspace
    )
    url = f"{_base(workspace, project, b)}/dependencies/{a.id}/"
    assert api_key_client.delete(url).status_code == status.HTTP_204_NO_CONTENT
    assert not IssueRelation.objects.filter(issue=a, related_issue=b).exists()
    assert api_key_client.delete(url).status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.contract
@pytest.mark.django_db
def test_dependency_remove_does_not_touch_relates_to(api_key_client, workspace, project, a, b):
    IssueRelation.objects.create(
        issue=a, related_issue=b, relation_type="relates_to", project=project, workspace=workspace
    )
    response = api_key_client.delete(f"{_base(workspace, project, a)}/dependencies/{b.id}/")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert IssueRelation.objects.filter(issue=a, related_issue=b, relation_type="relates_to").exists()


# --- relation definitions and custom relations ----------------------------


def _definitions(client, workspace, **params):
    return client.get(f"/api/v1/workspaces/{workspace.slug}/work-item-relation-definitions/", params)


@pytest.mark.contract
@pytest.mark.django_db
def test_built_in_definitions_are_listed(api_key_client, workspace):
    response = _definitions(api_key_client, workspace)
    assert response.status_code == status.HTTP_200_OK
    assert response.data["next_page_results"] is False
    labels = {(d["outward"], d["inward"]) for d in response.data["results"]}
    assert labels == {("relates to", "relates to"), ("duplicates", "duplicated by")}
    assert all(d["is_default"] and d["is_active"] for d in response.data["results"])
    # Stable ids: a second call returns the same ones.
    again = _definitions(api_key_client, workspace)
    assert [d["id"] for d in again.data["results"]] == [d["id"] for d in response.data["results"]]
    assert _definitions(api_key_client, workspace, is_default="false").data["results"] == []


@pytest.mark.contract
@pytest.mark.django_db
def test_custom_definitions_crud(api_key_client, workspace):
    base = f"/api/v1/workspaces/{workspace.slug}/work-item-relation-definitions/"
    created = api_key_client.post(
        base,
        {"name": "Implements", "outward": "implements", "inward": "implemented by", "color": "#5E6AD2"},
        format="json",
    )
    assert created.status_code == status.HTTP_201_CREATED, created.data
    assert created.data["is_default"] is False and created.data["is_active"] is True
    custom_id = created.data["id"]

    assert api_key_client.post(base, {"name": "implements"}, format="json").status_code == 400
    assert api_key_client.post(base, {"name": "Dupe", "outward": "duplicates"}, format="json").status_code == 400
    assert api_key_client.post(base, {}, format="json").status_code == 400

    listed = _definitions(api_key_client, workspace).data["results"]
    assert {d["name"] for d in listed} == {"Relates to", "Duplicate", "Implements"}
    assert [d["name"] for d in _definitions(api_key_client, workspace, is_default="false").data["results"]] == [
        "Implements"
    ]

    patched = api_key_client.patch(f"{base}{custom_id}/", {"inward": "is implemented by"}, format="json")
    assert patched.status_code == 200 and patched.data["inward"] == "is implemented by"
    built_in = next(d["id"] for d in listed if d["is_default"])
    assert api_key_client.patch(f"{base}{built_in}/", {"name": "x"}, format="json").status_code == 400
    assert api_key_client.delete(f"{base}{built_in}/").status_code == 400
    assert api_key_client.delete(f"{base}{custom_id}/").status_code == 204
    assert api_key_client.get(f"{base}{custom_id}/").status_code == 404


@pytest.mark.contract
@pytest.mark.django_db
def test_custom_relation_between_work_items(api_key_client, workspace, project, a, b):
    from plane.db.models import IssueCustomRelation

    base = f"/api/v1/workspaces/{workspace.slug}/work-item-relation-definitions/"
    definition = api_key_client.post(
        base, {"name": "Implements", "outward": "implements", "inward": "implemented by"}, format="json"
    ).data
    created = api_key_client.post(
        f"{_base(workspace, project, a)}/work-item-relations/",
        {
            "relation_definition_id": definition["id"],
            "relation_definition_type": "implemented by",
            "work_item_ids": [str(b.id)],
        },
        format="json",
    )
    assert created.status_code == status.HTTP_201_CREATED, created.data
    assert _ids(created.data) == {str(b.id)}
    # "a implemented by b" is stored as b -> a.
    assert IssueCustomRelation.objects.filter(issue=b, related_issue=a).exists()
    assert _ids(api_key_client.get(f"{_base(workspace, project, a)}/work-item-relations/").data["implemented by"]) == {
        str(b.id)
    }
    assert _ids(api_key_client.get(f"{_base(workspace, project, b)}/work-item-relations/").data["implements"]) == {
        str(a.id)
    }
    assert IssueRelation.objects.filter(Q(issue=a) | Q(related_issue=a)).count() == 0

    wrong = api_key_client.post(
        f"{_base(workspace, project, a)}/work-item-relations/",
        {
            "relation_definition_id": definition["id"],
            "relation_definition_type": "relates to",
            "work_item_ids": [str(b.id)],
        },
        format="json",
    )
    assert wrong.status_code == 400

    removed = api_key_client.delete(f"{_base(workspace, project, a)}/work-item-relations/{b.id}/")
    assert removed.status_code == status.HTTP_204_NO_CONTENT
    assert not IssueCustomRelation.objects.filter(issue=b, related_issue=a).exists()


def _definition(client, workspace, outward):
    return next(d for d in _definitions(client, workspace).data["results"] if d["outward"] == outward)


@pytest.mark.contract
@pytest.mark.django_db
def test_relates_to_via_definition(api_key_client, workspace, project, a, b):
    definition = _definition(api_key_client, workspace, "relates to")
    response = api_key_client.post(
        f"{_base(workspace, project, a)}/work-item-relations/",
        {
            "relation_definition_id": definition["id"],
            "relation_definition_type": "relates to",
            "work_item_ids": [str(b.id)],
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert _ids(response.data) == {str(b.id)}
    assert IssueRelation.objects.filter(issue=a, related_issue=b, relation_type="relates_to").exists()

    assert _ids(api_key_client.get(f"{_base(workspace, project, a)}/work-item-relations/").data["relates to"]) == {
        str(b.id)
    }
    assert _ids(api_key_client.get(f"{_base(workspace, project, b)}/work-item-relations/").data["relates to"]) == {
        str(a.id)
    }
    # Dependencies list stays empty.
    listed = api_key_client.get(f"{_base(workspace, project, a)}/dependencies/").data
    assert all(items == [] for items in listed.values())

    url = f"{_base(workspace, project, b)}/work-item-relations/{a.id}/"
    assert api_key_client.delete(url).status_code == status.HTTP_204_NO_CONTENT
    assert not IssueRelation.objects.filter(issue=a, related_issue=b).exists()


@pytest.mark.contract
@pytest.mark.django_db
def test_duplicated_by_label_stores_the_reverse_row(api_key_client, workspace, project, a, b):
    definition = _definition(api_key_client, workspace, "duplicates")
    response = api_key_client.post(
        f"{_base(workspace, project, a)}/work-item-relations/",
        {
            "relation_definition_id": definition["id"],
            "relation_definition_type": "duplicated by",
            "work_item_ids": [str(b.id)],
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert IssueRelation.objects.filter(issue=b, related_issue=a, relation_type="duplicate").exists()
    assert _ids(api_key_client.get(f"{_base(workspace, project, a)}/work-item-relations/").data["duplicated by"]) == {
        str(b.id)
    }
    assert _ids(api_key_client.get(f"{_base(workspace, project, b)}/work-item-relations/").data["duplicates"]) == {
        str(a.id)
    }


@pytest.mark.contract
@pytest.mark.django_db
@pytest.mark.parametrize("definition_id,label", [(str(uuid4()), "relates to"), (None, "wrong label")])
def test_bad_definition_or_label_is_400(api_key_client, workspace, project, a, b, definition_id, label):
    if definition_id is None:
        definition_id = _definition(api_key_client, workspace, "relates to")["id"]
    response = api_key_client.post(
        f"{_base(workspace, project, a)}/work-item-relations/",
        {"relation_definition_id": definition_id, "relation_definition_type": label, "work_item_ids": [str(b.id)]},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not IssueRelation.objects.filter(Q(issue=a) | Q(related_issue=a)).exists()


# --- estimates ------------------------------------------------------------


@pytest.mark.contract
@pytest.mark.django_db
@pytest.mark.parametrize("slash", ["", "/"])
def test_estimate_lifecycle_with_and_without_trailing_slash(api_key_client, workspace, project, a, slash):
    base = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/estimates"
    assert api_key_client.get(f"{base}{slash}").status_code == status.HTTP_404_NOT_FOUND

    created = api_key_client.post(f"{base}{slash}", {"name": "Points", "type": "points"}, format="json")
    assert created.status_code == status.HTTP_201_CREATED, created.data
    estimate_id = created.data["id"]
    assert api_key_client.get(f"{base}{slash}").data["id"] == estimate_id

    points = api_key_client.post(
        f"{base}/{estimate_id}/estimate-points{slash}",
        [{"value": "1", "key": 0}, {"value": "2", "key": 1}, {"value": "3", "key": 2}],
        format="json",
    )
    assert points.status_code == status.HTTP_201_CREATED, points.data
    assert EstimatePoint.objects.filter(estimate_id=estimate_id).count() == 3
    listed = api_key_client.get(f"{base}/{estimate_id}/estimate-points{slash}").data
    assert sorted(p["value"] for p in listed) == ["1", "2", "3"]

    point_id = next(p["id"] for p in listed if p["value"] == "2")
    updated = api_key_client.patch(
        f"{base}/{estimate_id}/estimate-points/{point_id}{slash}", {"value": "5"}, format="json"
    )
    assert updated.status_code == status.HTTP_200_OK
    assert updated.data["value"] == "5"


@pytest.mark.contract
@pytest.mark.django_db
def test_link_estimate_to_project_and_set_point_on_work_item(api_key_client, workspace, project, a):
    estimate = Estimate.objects.create(name="Points", type="points", project=project, workspace=workspace)
    point = EstimatePoint.objects.create(estimate=estimate, key=0, value="3", project=project, workspace=workspace)

    linked = api_key_client.patch(
        f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/", {"estimate": str(estimate.id)}, format="json"
    )
    assert linked.status_code == status.HTTP_200_OK, linked.data
    project.refresh_from_db()
    assert project.estimate_id == estimate.id

    updated = api_key_client.patch(
        f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/{a.id}/",
        {"estimate_point": str(point.id)},
        format="json",
    )
    assert updated.status_code == status.HTTP_200_OK, updated.data
    a.refresh_from_db()
    assert a.estimate_point_id == point.id


@pytest.mark.contract
@pytest.mark.django_db
def test_custom_relations_app_api(session_client, workspace, project, a, b):
    definitions = f"/api/workspaces/{workspace.slug}/relation-definitions/"
    definition = session_client.post(
        definitions, {"name": "Tests", "outward": "tests", "inward": "tested by"}, format="json"
    )
    assert definition.status_code == 201, definition.data
    assert {d["name"] for d in session_client.get(definitions).data["results"]} >= {"Tests", "Relates to"}

    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{a.id}/custom-relations/"
    created = session_client.post(
        base,
        {
            "relation_definition_id": definition.data["id"],
            "relation_definition_type": "tests",
            "work_item_ids": [str(b.id)],
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    assert [str(i["id"]) for i in session_client.get(base).data["tests"]] == [str(b.id)]
    assert session_client.delete(f"{base}{b.id}/").status_code == 204
    assert session_client.delete(f"{definitions}{definition.data['id']}/").status_code == 204
