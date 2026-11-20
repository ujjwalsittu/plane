# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Priority inbox: the "Needs action" tab of the notifications list."""

from datetime import timedelta

import pytest
from django.utils import timezone

from plane.db.models import Issue, Notification, Project, ProjectMember, State, User


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Alpha", identifier="ALP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def issue(project):
    state = State.objects.create(name="Todo", group="backlog", project=project, workspace=project.workspace)
    return Issue.objects.create(name="Item", project=project, workspace=project.workspace, state=state)


def _note(workspace, project, issue, user, minutes_ago, **kwargs):
    fields = {
        "workspace": workspace,
        "project": project,
        "entity_identifier": issue.id,
        "entity_name": "issue",
        "title": "t",
        "sender": "in_app:issue_activities:subscribed",
        "receiver": user,
    }
    fields.update(kwargs)
    note = Notification.objects.create(**fields)
    Notification.objects.filter(pk=note.pk).update(created_at=timezone.now() - timedelta(minutes=minutes_ago))
    return note


def _assignment(user, field="assignees"):
    return {"issue_activity": {"field": field, "new_identifier": str(user.id)}}


@pytest.mark.contract
@pytest.mark.django_db
def test_action_tab_lists_mentions_assignments_decisions_only(session_client, workspace, project, issue, create_user):
    now = timezone.now()
    other = User.objects.create(email="other@example.com", username="other")
    mention = _note(workspace, project, issue, create_user, 5, sender="in_app:issue_activities:mentioned")
    assignment = _note(
        workspace,
        project,
        issue,
        create_user,
        3,
        sender="in_app:issue_activities:assigned",
        data=_assignment(create_user),
    )
    decision = _note(workspace, project, issue, create_user, 1, entity_name="decision", sender="decision")
    # excluded: state change, read, currently snoozed, archived, someone else's
    _note(workspace, project, issue, create_user, 2, data=_assignment(create_user, field="state"))
    _note(workspace, project, issue, create_user, 2, sender="in_app:issue_activities:mentioned", read_at=now)
    _note(
        workspace,
        project,
        issue,
        create_user,
        2,
        sender="in_app:issue_activities:mentioned",
        snoozed_till=now + timedelta(days=1),
    )
    _note(workspace, project, issue, create_user, 2, sender="in_app:issue_activities:mentioned", archived_at=now)
    _note(workspace, project, issue, other, 2, sender="in_app:issue_activities:mentioned")
    _note(workspace, project, issue, other, 2, entity_name="decision", sender="decision")
    # an expired snooze counts as unsnoozed
    expired = _note(
        workspace,
        project,
        issue,
        create_user,
        4,
        sender="in_app:issue_activities:mentioned",
        snoozed_till=now - timedelta(days=1),
    )

    response = session_client.get(f"/api/workspaces/{workspace.slug}/users/notifications/?priority=action")

    assert response.status_code == 200, response.data
    assert [str(row["id"]) for row in response.data] == [
        str(decision.id),
        str(assignment.id),
        str(expired.id),
        str(mention.id),
    ]
