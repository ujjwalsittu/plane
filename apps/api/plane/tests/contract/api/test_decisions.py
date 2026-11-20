# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Decision requests: an agent asks a person, the person answers on the work item."""

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from plane.db.models import (
    DecisionRequest,
    Issue,
    IssueActivity,
    IssueComment,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)
from plane.utils.decisions import decisions_for


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Alpha", identifier="ALP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def issue(project):
    state = State.objects.create(name="Started", group="started", project=project, workspace=project.workspace)
    return Issue.objects.create(name="Item", project=project, workspace=project.workspace, state=state)


def _person(workspace, email, project=None, role=15):
    user = User.objects.create(email=email, username=email.split("@")[0], first_name=email.split("@")[0].title())
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    if project is not None:
        ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=role)
    return user


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _url(workspace, project, issue, suffix=""):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/{issue.id}/decisions/{suffix}"


def _ask(client, workspace, project, issue, asked, **extra):
    body = {"asked_user": str(asked.id), "question": "Ship <it>?", "options": ["Yes", "No"], **extra}
    return client.post(_url(workspace, project, issue), body, format="json")


@pytest.mark.contract
@pytest.mark.django_db
def test_agent_asks_and_person_answers(api_key_client, workspace, project, issue):
    person = _person(workspace, "alice@example.com", project)
    with patch("plane.utils.decisions.on_decision_created") as hook:
        created = _ask(api_key_client, workspace, project, issue, person)
    assert created.status_code == 201
    assert created.data["status"] == "open" and created.data["options"] == ["Yes", "No"]
    assert created.data["source"] == "api"
    hook.assert_called_once()
    assert hook.call_args.args[0].pk is not None and str(hook.call_args.args[0].id) == created.data["id"]

    listed = _client(person).get(f"/api/workspaces/{workspace.slug}/decisions/?status=open")
    assert listed.status_code == 200 and [d["id"] for d in listed.data] == [created.data["id"]]
    assert listed.data[0]["issue"]["identifier"] == f"ALP-{issue.sequence_id}"

    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/decisions"
    twin = f"{base}/{created.data['id']}/answer/"
    answered = _client(person).post(twin, {"answer": "Yes"}, format="json")
    assert answered.status_code == 200 and answered.data["status"] == "answered"
    assert answered.data["answer"] == "Yes" and answered.data["answered_by"] == str(person.id)

    comment = IssueComment.objects.get(issue=issue)
    assert comment.actor_id == person.id
    assert comment.comment_html == "<p>Decision: <strong>Yes</strong></p><p>Ship &lt;it&gt;?</p>"
    activity = IssueActivity.objects.get(issue=issue, field="decision")
    assert activity.source == "app" and activity.actor_id == person.id and activity.issue_comment_id == comment.id
    assert _client(person).get(f"/api/workspaces/{workspace.slug}/decisions/?status=open").data == []
    assert len(decisions_for(workspace.id, person, status="answered")) == 1


@pytest.mark.contract
@pytest.mark.django_db
def test_answer_rules(api_key_client, workspace, project, issue):
    person = _person(workspace, "alice@example.com", project)
    other = _person(workspace, "bob@example.com", project)
    decision_id = _ask(api_key_client, workspace, project, issue, person).data["id"]
    answer_url = _url(workspace, project, issue, f"{decision_id}/answer/")

    assert _client(other).post(answer_url, {"answer": "Yes"}, format="json").status_code == 403
    assert _client(person).post(answer_url, {"answer": "Maybe"}, format="json").status_code == 400
    assert _client(person).post(answer_url, {"answer": ""}, format="json").status_code == 400
    assert _client(person).post(answer_url, {"answer": "No"}, format="json").status_code == 200
    assert _client(person).post(answer_url, {"answer": "Yes"}, format="json").status_code == 409
    assert _client(person).post(_url(workspace, project, issue, f"{decision_id}/withdraw/")).status_code == 409
    assert DecisionRequest.objects.get(pk=decision_id).answer == "No"

    second = _ask(api_key_client, workspace, project, issue, person).data["id"]
    Issue.objects.filter(pk=issue.pk).update(deleted_at="2020-01-01T00:00:00Z")
    gone = _client(person).post(_url(workspace, project, issue, f"{second}/answer/"), {"answer": "Yes"}, format="json")
    assert gone.status_code == 404


@pytest.mark.contract
@pytest.mark.django_db
def test_free_text_answer_and_withdraw(api_key_client, workspace, project, issue):
    person = _person(workspace, "alice@example.com", project)
    free = _ask(api_key_client, workspace, project, issue, person, options=[]).data["id"]
    ok = _client(person).post(_url(workspace, project, issue, f"{free}/answer/"), {"answer": "Use blue"}, format="json")
    assert ok.status_code == 200

    withdrawn = _ask(api_key_client, workspace, project, issue, person).data["id"]
    assert _client(person).post(_url(workspace, project, issue, f"{withdrawn}/withdraw/")).data["status"] == "withdrawn"
    assert (
        _client(person)
        .post(_url(workspace, project, issue, f"{withdrawn}/answer/"), {"answer": "Yes"}, format="json")
        .status_code
        == 409
    )
    listing = api_key_client.get(_url(workspace, project, issue) + "?status=withdrawn")
    assert [d["id"] for d in listing.data] == [withdrawn]


@pytest.mark.contract
@pytest.mark.django_db
def test_create_validation(api_key_client, workspace, project, issue):
    outsider = _person(workspace, "out@example.com")
    member = _person(workspace, "alice@example.com", project)
    assert _ask(api_key_client, workspace, project, issue, outsider).status_code == 400
    assert api_key_client.post(_url(workspace, project, issue), {"question": "Q"}, format="json").status_code == 400
    assert _ask(api_key_client, workspace, project, issue, member, question="  ").status_code == 400
    assert (
        _ask(api_key_client, workspace, project, issue, member, options=[str(i) for i in range(11)]).status_code == 400
    )
    assert _ask(api_key_client, workspace, project, issue, member, options=["ok", 3]).status_code == 400
    assert _ask(api_key_client, workspace, project, issue, member, options="Yes").status_code == 400
    assert not DecisionRequest.objects.exists()


@pytest.mark.contract
@pytest.mark.django_db
def test_decisions_for_respects_visibility(api_key_client, workspace, project, issue, create_user):
    person = _person(workspace, "alice@example.com", project)
    _ask(api_key_client, workspace, project, issue, person)
    assert len(decisions_for(workspace.id, person)) == 1
    # Once the person leaves the project they no longer see the item or its question.
    ProjectMember.objects.filter(project=project, member=person).update(is_active=False)
    assert decisions_for(workspace.id, person) == []
    # Nobody else sees someone else's decisions.
    assert decisions_for(workspace.id, create_user) == []
