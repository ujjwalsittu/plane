# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""GET /api/v1/workspaces/<slug>/work-items/count: the SDK count_workspace / MCP workitem count."""

import pytest

from plane.db.models import (
    Issue,
    IssueAssignee,
    IssueLabel,
    Label,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)


@pytest.fixture
def data(workspace, create_user):
    alpha = Project.objects.create(name="Alpha", identifier="ALP", workspace=workspace, created_by=create_user)
    beta = Project.objects.create(name="Beta", identifier="BET", workspace=workspace, created_by=create_user)
    hidden = Project.objects.create(name="Hidden", identifier="HID", workspace=workspace, created_by=create_user)
    for project in (alpha, beta):
        ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    other = User.objects.create(email="o@plane.so", username="o")
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)

    def state(project, group):
        return State.objects.create(name=group.title(), group=group, project=project, workspace=workspace)

    todo, done = state(alpha, "unstarted"), state(alpha, "completed")
    beta_todo = state(beta, "unstarted")
    bug = Label.objects.create(name="bug", project=alpha, workspace=workspace)
    items = {
        "a1": Issue.objects.create(name="a1", project=alpha, workspace=workspace, state=todo, priority="high"),
        "a2": Issue.objects.create(name="a2", project=alpha, workspace=workspace, state=done, priority="high"),
        "a3": Issue.objects.create(name="a3", project=alpha, workspace=workspace, state=todo, priority="low"),
        "b1": Issue.objects.create(name="b1", project=beta, workspace=workspace, state=beta_todo, priority="high"),
    }
    Issue.objects.create(name="h1", project=hidden, workspace=workspace, state=state(hidden, "unstarted"))
    IssueAssignee.objects.create(issue=items["a1"], assignee=create_user, project=alpha, workspace=workspace)
    IssueAssignee.objects.create(issue=items["a1"], assignee=other, project=alpha, workspace=workspace)
    removed = IssueAssignee.objects.create(issue=items["a2"], assignee=other, project=alpha, workspace=workspace)
    removed.delete()  # soft-deleted: must not count
    IssueLabel.objects.create(issue=items["a3"], label=bug, project=alpha, workspace=workspace)
    return {"alpha": alpha, "beta": beta, "user": create_user, "other": other, **items}


def _count(client, workspace, **params):
    return client.get(f"/api/v1/workspaces/{workspace.slug}/work-items/count", params)


@pytest.mark.contract
@pytest.mark.django_db
def test_total_and_project_scope(api_key_client, workspace, data):
    whole = _count(api_key_client, workspace)
    assert whole.status_code == 200, whole.data
    # Only projects the caller belongs to: Hidden is left out.
    assert whole.data == {"grouped_by": None, "sub_grouped_by": None, "total_count": 4, "grouped_counts": {}}
    assert api_key_client.get(f"/api/v1/workspaces/{workspace.slug}/work-items/count/").data["total_count"] == 4
    # The MCP narrows to one project by wrapping the filter in parentheses.
    scoped = _count(api_key_client, workspace, pql=f'project = "{data["alpha"].id}"')
    assert scoped.data["total_count"] == 3
    nested_pql = f'(project = "{data["alpha"].id}") AND project = "{data["alpha"].id}"'
    assert _count(api_key_client, workspace, pql=nested_pql).data["total_count"] == 3


@pytest.mark.contract
@pytest.mark.django_db
def test_grouped_counts(api_key_client, workspace, data):
    by_priority = _count(api_key_client, workspace, group_by="priority").data
    assert by_priority["grouped_counts"] == {"high": {"count": 3}, "low": {"count": 1}}
    by_group = _count(api_key_client, workspace, group_by="state__group").data["grouped_counts"]
    assert by_group == {"unstarted": {"count": 3}, "completed": {"count": 1}}

    # Assignees: a1 has two, a2's only assignee was removed (counts as None).
    by_assignee = _count(api_key_client, workspace, group_by="assignees__id").data["grouped_counts"]
    assert by_assignee == {
        str(data["user"].id): {"count": 1},
        str(data["other"].id): {"count": 1},
        "None": {"count": 3},
    }
    by_label = _count(api_key_client, workspace, group_by="labels__id").data["grouped_counts"]
    assert by_label[str(Label.objects.get(name="bug").id)] == {"count": 1} and by_label["None"] == {"count": 3}

    nested = _count(api_key_client, workspace, group_by="project_id", sub_group_by="priority").data
    alpha = nested["grouped_counts"][str(data["alpha"].id)]
    assert alpha == {"count": 3, "sub_grouped_counts": {"high": {"count": 2}, "low": {"count": 1}}}
    assert nested["total_count"] == 4


@pytest.mark.contract
@pytest.mark.django_db
def test_team_filter_and_errors(api_key_client, workspace, data):
    team = api_key_client.post(
        f"/api/v1/workspaces/{workspace.slug}/teamspaces", {"name": "T", "lead": str(data["other"].id)}, format="json"
    ).data
    pql = f'(team = "{team["id"]}") AND project = "{data["alpha"].id}"'
    assert _count(api_key_client, workspace, pql=pql).data["total_count"] == 1  # only a1 is live-assigned to other

    assert _count(api_key_client, workspace, group_by="nope").status_code == 400
    assert _count(api_key_client, workspace, sub_group_by="priority").status_code == 400
    assert _count(api_key_client, workspace, pql="assignee = currentUser()").status_code == 400
    assert _count(api_key_client, workspace, filters='{"priority": "high"}').status_code == 400
