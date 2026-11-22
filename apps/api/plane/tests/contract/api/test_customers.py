# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Customers through the external API, in the shapes the official Plane SDK (plane.models.customers,
v0.3.6 MCP image) parses. The SDK is not a test dependency, so responses are compared to its field
lists below."""

import json
import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import (
    APIToken,
    Customer,
    CustomerRequest,
    CustomerRequestIssue,
    Issue,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)
from plane.utils import agents

pytestmark = [pytest.mark.contract, pytest.mark.django_db]

# Field names of the SDK's pydantic models.
CUSTOMER_KEYS = {
    "id",
    "deleted_at",
    "customer_request_count",
    "logo_url",
    "created_at",
    "updated_at",
    "name",
    "description",
    "description_html",
    "description_stripped",
    "description_binary",
    "email",
    "website_url",
    "logo_props",
    "domain",
    "employees",
    "stage",
    "contract_status",
    "revenue",
    "external_source",
    "external_id",
    "archived_at",
    "created_by",
    "updated_by",
    "logo_asset",
    "workspace",
}
PROPERTY_KEYS = {
    "id",
    "deleted_at",
    "created_at",
    "updated_at",
    "name",
    "display_name",
    "description",
    "logo_props",
    "sort_order",
    "property_type",
    "relation_type",
    "is_required",
    "default_value",
    "settings",
    "is_active",
    "is_multi",
    "validation_rules",
    "external_source",
    "external_id",
    "created_by",
    "updated_by",
    "workspace",
    "options",
}
OPTION_KEYS = {
    "id",
    "deleted_at",
    "created_at",
    "updated_at",
    "name",
    "sort_order",
    "description",
    "logo_props",
    "is_active",
    "is_default",
    "external_source",
    "external_id",
    "created_by",
    "updated_by",
    "workspace",
    "property",
    "parent",
}
REQUEST_KEYS = {
    "id",
    "name",
    "description",
    "description_html",
    "link",
    "work_item_ids",
    "attachment_count",
    "created_at",
}
WORK_ITEM_KEYS = {
    "id",
    "name",
    "state_id",
    "priority",
    "sequence_id",
    "project_id",
    "project__identifier",
    "created_at",
    "updated_at",
}
LINKED_KEYS = {"id", "name", "sequence_id", "project_id", "project__identifier"}
PAGE_KEYS = {
    "grouped_by",
    "sub_grouped_by",
    "total_count",
    "next_cursor",
    "prev_cursor",
    "next_page_results",
    "prev_page_results",
    "count",
    "total_pages",
    "total_results",
    "extra_stats",
    "results",
}


def _json(response):
    return json.loads(response.content) if response.content else None


def _base(workspace):
    return f"/api/v1/workspaces/{workspace.slug}"


def _client_for(user, token):
    APIToken.objects.create(user=user, label=token, token=token)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=token)
    return client


def _member(workspace, email, role):
    user = User.objects.create(email=email, username=email.split("@")[0])
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    return user


def _project(workspace, owner, name, identifier):
    project = Project.objects.create(name=name, identifier=identifier, workspace=workspace, created_by=owner)
    ProjectMember.objects.create(project=project, member=owner, workspace=workspace, role=20)
    State.objects.create(name="Todo", project=project, workspace=workspace, group="backlog", default=True)
    return project


def _check_customer(data):
    assert set(data) == CUSTOMER_KEYS, set(data) ^ CUSTOMER_KEYS
    assert isinstance(data["id"], str) and isinstance(data["name"], str) and isinstance(data["workspace"], str)
    assert isinstance(data["customer_request_count"], int)
    assert data["employees"] is None or isinstance(data["employees"], int)


@pytest.mark.parametrize("slash", ["", "/"])
def test_customer_crud_matches_sdk_shape(api_key_client, workspace, slash):
    assert _json(api_key_client.get(f"{_base(workspace)}/features/"))["customers"] is True
    customers = f"{_base(workspace)}/customers"
    created = api_key_client.post(
        customers + slash,
        {
            "name": "Acme",
            "description_html": "<p>Big <b>one</b></p>",
            "email": "ops@acme.test",
            "website_url": "https://acme.test",
            "domain": "SaaS",
            "employees": 50,
            "stage": "lead",
            "contract_status": "active",
            "revenue": "1000000",
            "external_source": "hubspot",
            "external_id": "42",
        },
        format="json",
    )
    assert created.status_code == 201, created.content
    data = _json(created)
    _check_customer(data)
    assert data["description_stripped"] == "Big one" and data["customer_request_count"] == 0
    assert (data["stage"], data["contract_status"], data["employees"]) == ("lead", "active", 50)

    # Upsert: external_source + external_id match first, whatever the name.
    by_external = api_key_client.post(
        customers + slash,
        {"name": "Acme Corp", "external_source": "hubspot", "external_id": "42", "employees": 60},
        format="json",
    )
    assert by_external.status_code == 200, by_external.content
    assert _json(by_external)["id"] == data["id"] and _json(by_external)["name"] == "Acme Corp"
    # Then the name.
    by_name = api_key_client.post(customers + slash, {"name": "Acme Corp", "stage": "closed_won"}, format="json")
    assert by_name.status_code == 200 and _json(by_name)["id"] == data["id"]
    assert _json(by_name)["employees"] == 60 and _json(by_name)["stage"] == "closed_won"
    assert Customer.objects.filter(workspace=workspace).count() == 1

    beta = api_key_client.post(customers + slash, {"name": "Beta Ltd"}, format="json")
    assert beta.status_code == 201
    beta_id = _json(beta)["id"]

    listed = api_key_client.get(customers + slash, {"query": "acme"})
    assert listed.status_code == 200
    page = _json(listed)
    assert set(page) == PAGE_KEYS and [row["name"] for row in page["results"]] == ["Acme Corp"]
    _check_customer(page["results"][0])
    assert len(_json(api_key_client.get(customers + slash))["results"]) == 2

    for bad in (
        {},
        {"name": "   "},
        {"name": 123},
        {"name": "X", "employees": "many"},
        {"name": "X", "employees": True},
        {"name": "X", "employees": -1},
        {"name": "X", "email": "nope"},
        {"name": "X", "stage": ["lead"]},
        {"name": "X", "description": "text"},
        {"name": "X", "logo_asset": str(uuid.uuid4())},
    ):
        response = api_key_client.post(customers, bad, format="json")
        assert response.status_code == 400, bad
        assert "error" in _json(response)
    assert api_key_client.post(customers, ["not", "an", "object"], format="json").status_code == 400

    one = f"{customers}/{data['id']}"
    updated = api_key_client.patch(one + slash, {"contract_status": "signed", "revenue": "2000000"}, format="json")
    assert updated.status_code == 200
    _check_customer(_json(updated))
    assert _json(updated)["contract_status"] == "signed" and _json(updated)["name"] == "Acme Corp"
    duplicate = api_key_client.patch(f"{customers}/{beta_id}", {"name": "Acme Corp"}, format="json")
    assert duplicate.status_code == 400 and "name" in _json(duplicate)
    assert api_key_client.get(one + slash).status_code == 200
    assert api_key_client.get(f"{customers}/{uuid.uuid4()}").status_code == 404

    assert api_key_client.delete(one + slash).status_code == 204
    assert api_key_client.get(one).status_code == 404
    assert Customer.all_objects.get(pk=data["id"]).deleted_at is not None
    # A deleted customer's name and external id are free again.
    again = api_key_client.post(
        customers, {"name": "Acme Corp", "external_source": "hubspot", "external_id": "42"}, format="json"
    )
    assert again.status_code == 201 and _json(again)["id"] != data["id"]

    # Delete by external reference; no match still succeeds; half a reference is refused.
    by_ref = f"{customers}?external_source=hubspot&external_id=42"
    assert api_key_client.delete(by_ref).status_code == 204
    assert not Customer.objects.filter(external_id="42").exists()
    assert api_key_client.delete(by_ref).status_code == 204
    assert api_key_client.delete(f"{customers}?external_source=hubspot").status_code == 400
    assert Customer.objects.filter(pk=beta_id).exists()


def test_properties_and_values(api_key_client, workspace, create_user):
    properties = f"{_base(workspace)}/customer-properties"

    def create(body):
        response = api_key_client.post(properties, body, format="json")
        assert response.status_code == 201, response.content
        data = _json(response)
        assert set(data) == PROPERTY_KEYS, set(data) ^ PROPERTY_KEYS
        return data

    tier = create(
        {"name": "Tier", "display_name": "Tier", "property_type": "TEXT", "settings": {"display_format": "single-line"}}
    )
    assert tier["name"] == "tier" and tier["settings"] == {"display_format": "single-line"} and tier["options"] == []
    plan = create(
        {
            "name": "Plan",
            "display_name": "Plan",
            "property_type": "OPTION",
            "options": [{"name": "Gold", "is_default": True}, {"name": "Silver"}],
        }
    )
    assert [o["name"] for o in plan["options"]] == ["Gold", "Silver"]
    assert all(set(o) == OPTION_KEYS for o in plan["options"]) and plan["options"][0]["is_default"] is True
    gold = plan["options"][0]["id"]
    paying = create({"name": "Paying", "display_name": "Paying", "property_type": "BOOLEAN", "is_required": True})
    seats = create({"name": "Seats", "display_name": "Seats", "property_type": "DECIMAL"})
    renewal = create(
        {
            "name": "Renewal",
            "display_name": "Renewal",
            "property_type": "DATETIME",
            "settings": {"display_format": "MMM dd, yyyy"},
        }
    )
    owner = create(
        {
            "name": "Owner",
            "display_name": "Owner",
            "property_type": "RELATION",
            "relation_type": "USER",
            "is_multi": True,
        }
    )

    for bad in (
        {"display_name": "Note", "property_type": "TEXT"},
        {"display_name": "Note", "property_type": "TEXT", "settings": {"display_format": "huge"}},
        {"display_name": "Note", "property_type": "FORMULA"},
        {"display_name": "Link", "property_type": "RELATION"},
        {"display_name": "Tier", "property_type": "DECIMAL"},
        {"display_name": "Flag", "property_type": "BOOLEAN", "is_multi": "false"},
        {"display_name": "Flag", "property_type": "BOOLEAN", "is_required": "yes"},
        {"display_name": "", "property_type": "DECIMAL"},
        {"display_name": "Pick", "property_type": "OPTION", "options": "Gold"},
    ):
        response = api_key_client.post(properties, bad, format="json")
        assert response.status_code == 400, bad
        assert "error" in _json(response)

    listed = _json(api_key_client.get(properties))
    assert set(listed) == PAGE_KEYS and len(listed["results"]) == 6
    assert api_key_client.get(f"{properties}/{plan['id']}/").status_code == 200

    renamed = api_key_client.patch(
        f"{properties}/{plan['id']}", {"options": [{"id": gold, "name": "Gold+"}, {"name": "Bronze"}]}, format="json"
    )
    assert renamed.status_code == 200, renamed.content
    assert [o["name"] for o in _json(renamed)["options"]] == ["Gold+", "Silver", "Bronze"]
    assert api_key_client.patch(f"{properties}/{plan['id']}", {"is_active": "false"}, format="json").status_code == 400
    assert (
        api_key_client.patch(
            f"{properties}/{plan['id']}", {"options": [{"id": str(uuid.uuid4()), "name": "X"}]}, format="json"
        ).status_code
        == 400
    )

    customer = _json(api_key_client.post(f"{_base(workspace)}/customers", {"name": "Acme"}, format="json"))
    values_url = f"{_base(workspace)}/customers/{customer['id']}/property-values"
    good = {
        tier["id"]: ["Enterprise"],
        plan["id"]: [gold],
        paying["id"]: ["false"],
        seats["id"]: ["12.50"],
        renewal["id"]: ["2026-12-01"],
        owner["id"]: [str(create_user.id)],
    }
    saved = api_key_client.post(values_url, {"customer_property_values": good}, format="json")
    assert saved.status_code == 200, saved.content
    expected = {**good, paying["id"]: ["False"]}
    assert _json(api_key_client.get(values_url)) == expected

    for bad in (
        {paying["id"]: ["yes"]},
        {seats["id"]: ["abc"]},
        {seats["id"]: ["NaN"]},
        {renewal["id"]: ["2026-13-01"]},
        {plan["id"]: [str(uuid.uuid4())]},
        {tier["id"]: ["a", "b"]},
        {tier["id"]: [1]},
        {tier["id"]: "Enterprise"},
        {str(uuid.uuid4()): ["x"]},
        {"not-a-uuid": ["x"]},
        {owner["id"]: [str(uuid.uuid4())]},
        {paying["id"]: []},
        # One bad value refuses the whole call, so the good one isn't written either.
        {tier["id"]: ["SMB"], seats["id"]: ["lots"]},
    ):
        response = api_key_client.post(values_url, {"customer_property_values": bad}, format="json")
        assert response.status_code == 400, bad
        assert "error" in _json(response)
    assert api_key_client.post(values_url, {"customer_property_values": ["x"]}, format="json").status_code == 400
    assert _json(api_key_client.get(values_url)) == expected

    one_value = f"{values_url}/{tier['id']}"
    assert api_key_client.patch(one_value, {"values": ["SMB"]}, format="json").status_code == 200
    assert _json(api_key_client.get(one_value)) == {tier["id"]: ["SMB"]}
    assert api_key_client.patch(f"{values_url}/{paying['id']}", {"values": []}, format="json").status_code == 400
    assert api_key_client.get(f"{values_url}/{uuid.uuid4()}").status_code == 404
    assert (
        api_key_client.patch(
            f"{_base(workspace)}/customers/{uuid.uuid4()}/property-values/{tier['id']}",
            {"values": ["x"]},
            format="json",
        ).status_code
        == 404
    )

    # Inactive properties are left out of reads; deleted ones are gone.
    assert api_key_client.patch(f"{properties}/{seats['id']}", {"is_active": False}, format="json").status_code == 200
    assert seats["id"] not in _json(api_key_client.get(values_url))
    assert api_key_client.delete(f"{properties}/{tier['id']}").status_code == 204
    assert tier["id"] not in _json(api_key_client.get(values_url))
    assert api_key_client.get(f"{properties}/{tier['id']}").status_code == 404


def test_requests_and_work_item_links(api_key_client, workspace, create_user):
    alpha = _project(workspace, create_user, "Alpha", "ALP")
    stranger = _member(workspace, "stranger@plane.so", 15)
    secret = _project(workspace, stranger, "Secret", "SEC")
    first = Issue.objects.create(name="SSO login", project=alpha, workspace=workspace)
    second = Issue.objects.create(name="Audit log", project=alpha, workspace=workspace)
    hidden = Issue.objects.create(name="Secret thing", project=secret, workspace=workspace)

    customers = f"{_base(workspace)}/customers"
    customer = _json(api_key_client.post(customers, {"name": "Acme"}, format="json"))
    requests_url = f"{customers}/{customer['id']}/requests"
    issues_url = f"{customers}/{customer['id']}/issues"

    created = api_key_client.post(
        requests_url,
        {
            "name": "SSO please",
            "description_html": "<p>Okta</p>",
            "link": "https://support.acme.test/1",
            "work_item_ids": [str(first.id)],
        },
        format="json",
    )
    assert created.status_code == 201, created.content
    request_data = _json(created)
    assert set(request_data) == REQUEST_KEYS, set(request_data) ^ REQUEST_KEYS
    assert request_data["attachment_count"] == 0 and request_data["work_item_ids"] == [str(first.id)]

    for bad in (
        {"name": "Peek", "work_item_ids": [str(hidden.id)]},
        {"name": "Peek", "work_item_ids": str(first.id)},
        {"name": "Peek", "link": "not a url"},
        {"name": ""},
    ):
        assert api_key_client.post(requests_url, bad, format="json").status_code == 400, bad
    assert CustomerRequest.objects.filter(customer_id=customer["id"]).count() == 1

    listed = _json(api_key_client.get(requests_url, {"query": "sso"}))
    assert set(listed) == PAGE_KEYS and [r["id"] for r in listed["results"]] == [request_data["id"]]
    assert _json(api_key_client.get(requests_url, {"query": "billing"}))["results"] == []
    one_request = f"{requests_url}/{request_data['id']}"
    assert _json(api_key_client.patch(one_request + "/", {"name": "SSO via Okta"}, format="json"))["name"] == (
        "SSO via Okta"
    )
    assert _json(api_key_client.get(one_request))["name"] == "SSO via Okta"
    assert _json(api_key_client.get(f"{customers}/{customer['id']}"))["customer_request_count"] == 1

    linked = api_key_client.post(issues_url, {"issue_ids": [str(second.id)]}, format="json")
    assert linked.status_code == 201, linked.content
    body = _json(linked)
    assert set(body) == {"message", "linked_issues"}
    assert [set(row) for row in body["linked_issues"]] == [LINKED_KEYS]
    assert body["linked_issues"][0]["project__identifier"] == "ALP"
    # Re-linking is a no-op.
    assert api_key_client.post(issues_url, {"issue_ids": [str(second.id)]}, format="json").status_code == 201
    assert CustomerRequestIssue.objects.filter(issue=second).count() == 1

    # A work item in a project the caller isn't in can't be linked, and refuses the whole call.
    third = Issue.objects.create(name="Webhooks", project=alpha, workspace=workspace)
    refused = api_key_client.post(issues_url, {"issue_ids": [str(third.id), str(hidden.id)]}, format="json")
    assert refused.status_code == 400 and "error" in _json(refused)
    assert not CustomerRequestIssue.objects.filter(issue__in=[third, hidden]).exists()
    for bad in ({"issue_ids": str(third.id)}, {"issue_ids": ["nope"]}, {"issue_ids": []}, {}):
        assert api_key_client.post(issues_url, bad, format="json").status_code == 400, bad

    # A link someone else made to a hidden item isn't listed.
    CustomerRequestIssue.objects.create(workspace=workspace, customer_id=customer["id"], issue=hidden)
    rows = _json(api_key_client.get(issues_url))
    assert sorted(row["id"] for row in rows) == sorted([str(first.id), str(second.id)])
    assert all(set(row) == WORK_ITEM_KEYS for row in rows)
    assert [r["id"] for r in _json(api_key_client.get(issues_url, {"customer_request_id": request_data["id"]}))] == [
        str(first.id)
    ]
    assert [r["id"] for r in _json(api_key_client.get(issues_url, {"search": f"ALP-{second.sequence_id}"}))] == [
        str(second.id)
    ]
    assert [r["id"] for r in _json(api_key_client.get(issues_url, {"search": "audit"}))] == [str(second.id)]
    assert api_key_client.get(issues_url, {"customer_request_id": str(uuid.uuid4())}).status_code == 404

    # Soft-deleted work items drop out.
    Issue.all_objects.filter(pk=second.pk).update(deleted_at=timezone.now())
    assert [r["id"] for r in _json(api_key_client.get(issues_url))] == [str(first.id)]

    assert api_key_client.delete(f"{issues_url}/{first.id}").status_code == 204
    assert api_key_client.delete(f"{issues_url}/{first.id}").status_code == 404
    assert api_key_client.delete(f"{issues_url}/{hidden.id}").status_code == 404
    assert _json(api_key_client.get(one_request))["work_item_ids"] == []

    # Requests belong to their customer.
    other = _json(api_key_client.post(customers, {"name": "Other"}, format="json"))
    assert api_key_client.get(f"{customers}/{other['id']}/requests/{request_data['id']}").status_code == 404

    linked_via_request = api_key_client.post(
        f"{issues_url}?customer_request_id={request_data['id']}", {"issue_ids": [str(third.id)]}, format="json"
    )
    assert linked_via_request.status_code == 201
    assert api_key_client.delete(one_request).status_code == 204
    assert api_key_client.get(one_request).status_code == 404
    assert not CustomerRequestIssue.objects.filter(customer_request_id=request_data["id"]).exists()
    assert _json(api_key_client.get(f"{customers}/{customer['id']}"))["customer_request_count"] == 0


def test_guest_cannot_read_customers(api_key_client, workspace):
    customers = f"{_base(workspace)}/customers"
    customer = _json(api_key_client.post(customers, {"name": "Acme"}, format="json"))

    guest = _client_for(_member(workspace, "guest@plane.so", 5), "guest-token")
    for response in (
        guest.get(customers),
        guest.get(f"{customers}/{customer['id']}"),
        guest.get(f"{_base(workspace)}/customer-properties"),
        guest.get(f"{customers}/{customer['id']}/requests"),
        guest.get(f"{customers}/{customer['id']}/issues"),
        guest.post(customers, {"name": "Guest Co"}, format="json"),
    ):
        assert response.status_code == 403
    assert not Customer.objects.filter(name="Guest Co").exists()

    member = _client_for(_member(workspace, "member@plane.so", 15), "member-token")
    assert member.get(customers).status_code == 200
    assert member.post(customers, {"name": "Member Co"}, format="json").status_code == 201


def test_contribute_agent_cannot_write_customers(api_key_client, workspace, create_user):
    customers = f"{_base(workspace)}/customers"
    project = _project(workspace, create_user, "Alpha", "ALP")

    def agent_client(name, permission):
        _, token = agents.create_agent(
            workspace,
            {"name": name, "owner": str(create_user.id), "project_ids": [str(project.id)], "permission": permission},
            create_user,
        )
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=token)
        return client

    contribute = agent_client("Helper", "contribute")
    assert contribute.get(customers).status_code == 200
    refused = contribute.post(customers, {"name": "Agent Co"}, format="json")
    assert refused.status_code == 403
    assert not Customer.objects.filter(name="Agent Co").exists()

    manage = agent_client("Manager", "manage")
    assert manage.post(customers, {"name": "Agent Co"}, format="json").status_code == 201


def test_issue_values_respect_visibility(api_key_client, workspace, create_user):
    """ISSUE relation values: reads hide work items the caller can't see, the caller can't write them, and the
    caller's writes keep them."""
    alpha = _project(workspace, create_user, "Alpha", "ALP")
    secret = _project(workspace, create_user, "Secret", "SEC")
    member_user = _member(workspace, "member@plane.so", 15)
    ProjectMember.objects.create(project=alpha, member=member_user, workspace=workspace, role=15)
    member = _client_for(member_user, "member-token")
    shown = Issue.objects.create(name="Shown", project=alpha, workspace=workspace)
    other = Issue.objects.create(name="Other", project=alpha, workspace=workspace)
    hidden = Issue.objects.create(name="Hidden", project=secret, workspace=workspace)

    properties = f"{_base(workspace)}/customer-properties"
    related = _json(
        api_key_client.post(
            properties,
            {"display_name": "Related", "property_type": "RELATION", "relation_type": "ISSUE", "is_multi": True},
            format="json",
        )
    )["id"]
    blocker = _json(
        api_key_client.post(
            properties,
            {"display_name": "Blocker", "property_type": "RELATION", "relation_type": "ISSUE"},
            format="json",
        )
    )["id"]
    customer = _json(api_key_client.post(f"{_base(workspace)}/customers", {"name": "Acme"}, format="json"))["id"]
    values_url = f"{_base(workspace)}/customers/{customer}/property-values"
    saved = api_key_client.post(
        values_url,
        {"customer_property_values": {related: [str(shown.id), str(hidden.id)], blocker: [str(hidden.id)]}},
        format="json",
    )
    assert saved.status_code == 200, saved.content
    assert _json(saved)[related] == [str(shown.id), str(hidden.id)]

    # Reads leave out the hidden work item.
    assert _json(member.get(values_url)) == {related: [str(shown.id)]}
    assert _json(member.get(f"{values_url}/{related}")) == {related: [str(shown.id)]}
    assert _json(member.get(f"{values_url}/{blocker}")) == {blocker: []}

    # The caller can't write a hidden id.
    refused = member.patch(f"{values_url}/{related}", {"values": [str(hidden.id)]}, format="json")
    assert refused.status_code == 400 and "error" in _json(refused)

    # Replacing what the caller sees keeps the hidden value.
    patched = member.patch(f"{values_url}/{related}", {"values": [str(other.id)]}, format="json")
    assert patched.status_code == 200, patched.content
    assert _json(patched) == {related: [str(other.id)]}
    assert sorted(_json(api_key_client.get(values_url))[related]) == sorted([str(hidden.id), str(other.id)])
    cleared = member.post(values_url, {"customer_property_values": {related: []}}, format="json")
    assert cleared.status_code == 200
    assert _json(api_key_client.get(values_url))[related] == [str(hidden.id)]

    # A single-value property holding a hidden work item can't be overwritten by the caller.
    overwrite = member.patch(f"{values_url}/{blocker}", {"values": [str(shown.id)]}, format="json")
    assert overwrite.status_code == 400 and "error" in _json(overwrite)
    assert _json(api_key_client.get(values_url))[blocker] == [str(hidden.id)]
