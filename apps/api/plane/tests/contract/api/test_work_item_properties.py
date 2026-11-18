# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Custom work item properties through the external API (the routes the SDK/MCP call)."""

from uuid import uuid4

import pytest
from rest_framework import status

from plane.db.models import Issue, IssuePropertyValue, IssueType, Project, ProjectMember


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Props", identifier="PRP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def task_type(workspace):
    return IssueType.objects.create(workspace=workspace, name="Task")


@pytest.fixture
def issue(project, task_type):
    return Issue.objects.create(name="Item", project=project, workspace=project.workspace, type=task_type)


def _ws(workspace, suffix=""):
    return f"/api/v1/workspaces/{workspace.slug}{suffix}"


def _p(workspace, project, suffix=""):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}{suffix}"


def _value_url(workspace, project, issue, prop_id):
    return _p(workspace, project, f"/work-items/{issue.id}/work-item-properties/{prop_id}/values")


@pytest.mark.contract
@pytest.mark.django_db
def test_workspace_property_with_options_and_type_link(api_key_client, workspace, project, task_type, issue):
    created = api_key_client.post(
        _ws(workspace, "/work-item-properties/"),
        {
            "display_name": "Severity",
            "property_type": "OPTION",
            "is_multi": True,
            "options": [{"name": "Low"}, {"name": "High", "color": "#f00"}],
        },
        format="json",
    )
    assert created.status_code == status.HTTP_201_CREATED, created.data
    prop = created.data
    assert [o["name"] for o in prop["options"]] == ["Low", "High"]
    assert prop["options"][1]["logo_props"]["color"] == "#f00"

    added = api_key_client.post(
        _ws(workspace, f"/work-item-properties/{prop['id']}/options/"), {"name": "Mid"}, format="json"
    )
    assert added.status_code == 201
    dupe = api_key_client.post(
        _ws(workspace, f"/work-item-properties/{prop['id']}/options/"), {"name": "mid"}, format="json"
    )
    assert dupe.status_code == 400

    link = api_key_client.post(
        _ws(workspace, f"/work-item-types/{task_type.id}/properties/"), {"properties": [prop["id"]]}, format="json"
    )
    assert link.status_code == 201 and link.data == {"properties": [prop["id"]]}
    assert api_key_client.get(_ws(workspace, f"/work-item-types/{task_type.id}/properties/")).data == [prop["id"]]

    low, high = prop["options"][0]["id"], prop["options"][1]["id"]
    url = _value_url(workspace, project, issue, prop["id"])
    multi = api_key_client.post(url, {"value": [low, high]}, format="json")
    assert multi.status_code == 201, multi.data
    assert sorted(v["value"] for v in multi.data) == sorted([low, high])
    # Setting again replaces every value.
    api_key_client.post(url, {"value": [high]}, format="json")
    assert [v["value"] for v in api_key_client.get(url).data] == [high]
    assert api_key_client.post(url, {"value": str(uuid4())}, format="json").status_code == 400

    assert (
        api_key_client.delete(_ws(workspace, f"/work-item-types/{task_type.id}/properties/{prop['id']}/")).status_code
        == 204
    )
    assert api_key_client.get(_ws(workspace, f"/work-item-types/{task_type.id}/properties/")).data == []


@pytest.mark.contract
@pytest.mark.django_db
@pytest.mark.parametrize(
    "property_type, extra, value, expected",
    [
        ("TEXT", {}, "Hello", "Hello"),
        ("DECIMAL", {}, 4.5, 4.5),
        ("BOOLEAN", {}, True, True),
        ("DATETIME", {}, "2026-12-20", "2026-12-20T00:00:00+00:00"),
        ("URL", {}, "https://plane.so", "https://plane.so"),
        ("EMAIL", {}, "a@b.co", "a@b.co"),
    ],
)
def test_type_scoped_values(
    api_key_client, workspace, project, task_type, issue, property_type, extra, value, expected
):
    created = api_key_client.post(
        _p(workspace, project, f"/work-item-types/{task_type.id}/work-item-properties"),
        {"display_name": f"P {property_type}", "property_type": property_type, **extra},
        format="json",
    )
    assert created.status_code == 201, created.data
    assert created.data["issue_type"] == str(task_type.id)
    listed = api_key_client.get(_p(workspace, project, f"/work-item-types/{task_type.id}/work-item-properties"))
    assert [p["id"] for p in listed.data] == [created.data["id"]]

    url = _value_url(workspace, project, issue, created.data["id"])
    assert api_key_client.get(url).status_code == 404
    stored = api_key_client.post(url, {"value": value}, format="json")
    assert stored.status_code == 201, stored.data
    assert stored.data["value"] == expected
    assert api_key_client.get(url).data["value"] == expected
    assert api_key_client.delete(url).status_code == 204
    assert not IssuePropertyValue.objects.filter(issue=issue).exists()


@pytest.mark.contract
@pytest.mark.django_db
def test_value_validation(api_key_client, workspace, project, issue, create_user):
    def make(**data):
        response = api_key_client.post(_p(workspace, project, "/work-item-properties"), data, format="json")
        assert response.status_code == 201, response.data
        return response.data["id"]

    number = make(display_name="Points", property_type="DECIMAL")
    flag = make(display_name="Flag", property_type="BOOLEAN")
    link = make(display_name="Site", property_type="URL")
    owner = make(display_name="Owner", property_type="RELATION", relation_type="USER")
    blocker = make(display_name="Blocker", property_type="RELATION", relation_type="ISSUE")

    assert (
        api_key_client.post(_value_url(workspace, project, issue, number), {"value": "7"}, format="json").status_code
        == 400
    )
    assert (
        api_key_client.post(_value_url(workspace, project, issue, flag), {"value": 1}, format="json").status_code == 400
    )
    assert (
        api_key_client.post(_value_url(workspace, project, issue, link), {"value": "nope"}, format="json").status_code
        == 400
    )
    assert (
        api_key_client.post(_value_url(workspace, project, issue, number), {"value": [1, 2]}, format="json").status_code
        == 400
    )
    user_ok = api_key_client.post(
        _value_url(workspace, project, issue, owner), {"value": str(create_user.id)}, format="json"
    )
    assert user_ok.status_code == 201 and user_ok.data["value"] == str(create_user.id)
    assert (
        api_key_client.post(
            _value_url(workspace, project, issue, owner), {"value": str(uuid4())}, format="json"
        ).status_code
        == 400
    )
    other = Issue.objects.create(name="Other", project=project, workspace=workspace)
    assert (
        api_key_client.post(
            _value_url(workspace, project, issue, blocker), {"value": str(other.id)}, format="json"
        ).status_code
        == 201
    )


@pytest.mark.contract
@pytest.mark.django_db
def test_definition_validation(api_key_client, workspace, project, issue):
    url = _p(workspace, project, "/work-item-properties")
    assert api_key_client.post(url, {"property_type": "TEXT"}, format="json").status_code == 400
    assert api_key_client.post(url, {"display_name": "F", "property_type": "FORMULA"}, format="json").status_code == 400
    assert (
        api_key_client.post(
            url, {"display_name": "R", "property_type": "RELATION", "relation_type": "RICH_TEXT"}, format="json"
        ).status_code
        == 400
    )
    assert (
        api_key_client.post(
            url, {"display_name": "M", "property_type": "TEXT", "is_multi": True}, format="json"
        ).status_code
        == 400
    )
    assert (
        api_key_client.post(
            url, {"display_name": "T", "property_type": "TEXT", "settings": {"display_format": "bold"}}, format="json"
        ).status_code
        == 400
    )
    first = api_key_client.post(url, {"display_name": "Area", "property_type": "TEXT"}, format="json")
    assert first.data["settings"] == {"display_format": "single-line"}
    assert api_key_client.post(url, {"display_name": "area", "property_type": "TEXT"}, format="json").status_code == 400

    api_key_client.post(_value_url(workspace, project, issue, first.data["id"]), {"value": "North"}, format="json")
    changed = api_key_client.patch(f"{url}/{first.data['id']}", {"property_type": "DECIMAL"}, format="json")
    assert changed.status_code == 400
    renamed = api_key_client.patch(f"{url}/{first.data['id']}", {"display_name": "Region"}, format="json")
    assert renamed.status_code == 200 and renamed.data["display_name"] == "Region"
    assert api_key_client.delete(f"{url}/{first.data['id']}").status_code == 204


@pytest.mark.contract
@pytest.mark.django_db
def test_project_type_links_and_scope(api_key_client, workspace, project, task_type, issue):
    prop = api_key_client.post(
        _p(workspace, project, "/work-item-properties"), {"display_name": "Env", "property_type": "TEXT"}, format="json"
    ).data
    linked = api_key_client.post(
        _p(workspace, project, f"/work-item-types/{task_type.id}/properties"),
        {"properties": [prop["id"]]},
        format="json",
    )
    assert linked.status_code == 201 and linked.data == {"properties": [prop["id"]]}
    listed = api_key_client.get(_p(workspace, project, f"/work-item-types/{task_type.id}/work-item-properties"))
    assert [p["id"] for p in listed.data] == [prop["id"]]

    other_project = Project.objects.create(name="Else", identifier="ELS", workspace=workspace)
    foreign = Issue.objects.create(name="X", project=other_project, workspace=workspace)
    assert (
        api_key_client.post(
            _p(workspace, project, f"/work-item-types/{task_type.id}/properties"),
            {"properties": [str(uuid4())]},
            format="json",
        ).status_code
        == 400
    )
    # A property of this project can't be read or set through another project's work item.
    assert api_key_client.get(_p(workspace, other_project, f"/work-item-properties/{prop['id']}")).status_code in (
        403,
        404,
    )
    assert foreign.id


@pytest.mark.contract
@pytest.mark.django_db
def test_app_api(session_client, workspace, project, task_type, issue):
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}"
    created = session_client.post(
        f"{base}/issue-properties/",
        {"display_name": "Stage", "property_type": "OPTION", "issue_type_id": str(task_type.id), "options": ["A", "B"]},
        format="json",
    )
    assert created.status_code == 201, created.data
    assert created.data["issue_type"] == str(task_type.id)
    untyped = session_client.post(
        f"{base}/issue-properties/", {"display_name": "Note", "property_type": "TEXT"}, format="json"
    ).data

    values = session_client.get(f"{base}/issues/{issue.id}/property-values/").data
    assert {row["property"]["display_name"] for row in values} == {"Stage", "Note"}

    option_b = created.data["options"][1]["id"]
    after = session_client.put(
        f"{base}/issues/{issue.id}/property-values/",
        {"property_id": created.data["id"], "value": option_b},
        format="json",
    ).data
    stage = next(row for row in after if row["property"]["id"] == created.data["id"])
    assert stage["values"] == [option_b]
    cleared = session_client.put(
        f"{base}/issues/{issue.id}/property-values/", {"property_id": untyped["id"], "value": None}, format="json"
    )
    assert cleared.status_code == 200

    # A work item of another type doesn't get the type's property.
    other = Issue.objects.create(name="Plain", project=project, workspace=workspace)
    names = {
        row["property"]["display_name"] for row in session_client.get(f"{base}/issues/{other.id}/property-values/").data
    }
    assert names == {"Note"}

    assert session_client.delete(f"{base}/issue-properties/{untyped['id']}/").status_code == 204


@pytest.mark.contract
@pytest.mark.django_db
def test_pql_custom_property_filters(api_key_client, workspace, project, issue):
    props = _p(workspace, project, "/work-item-properties")
    stage = api_key_client.post(
        props, {"display_name": "Stage", "property_type": "OPTION", "options": ["Draft", "Live"]}, format="json"
    ).data
    flag = api_key_client.post(props, {"display_name": "Flag", "property_type": "BOOLEAN"}, format="json").data
    points = api_key_client.post(props, {"display_name": "Points", "property_type": "DECIMAL"}, format="json").data
    other = Issue.objects.create(name="Other", project=project, workspace=workspace)
    live = stage["options"][1]["id"]
    api_key_client.post(_value_url(workspace, project, issue, stage["id"]), {"value": live}, format="json")
    api_key_client.post(_value_url(workspace, project, issue, flag["id"]), {"value": True}, format="json")
    api_key_client.post(_value_url(workspace, project, other, points["id"]), {"value": 3}, format="json")

    def ids(pql):
        response = api_key_client.get(_p(workspace, project, "/work-items/"), {"pql": pql})
        assert response.status_code == 200, response.data
        return {str(row["id"]) for row in response.data["results"]}

    assert ids(f'cf["{stage["id"]}"] = "{live}"') == {str(issue.id)}
    assert ids(f'cf["{stage["id"]}"] IN ("{live}", "{stage["options"][0]["id"]}")') == {str(issue.id)}
    assert ids(f'cf["{flag["id"]}"] = true') == {str(issue.id)}
    assert ids(f'cf["{points["id"]}"] = 3') == {str(other.id)}
    assert ids(f'cf["{flag["id"]}"] = true AND cf["{points["id"]}"] = 3') == set()
    bad = api_key_client.get(_p(workspace, project, "/work-items/"), {"pql": f'cf["{uuid4()}"] = "x"'})
    assert bad.status_code == 400
