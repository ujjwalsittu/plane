# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The Brief: what needs me, what is blocked, what got done since I last looked."""

from datetime import timedelta

import pytest
from django.utils import timezone

from plane.db.models import (
    BriefVisit,
    DecisionRequest,
    Issue,
    IssueActivity,
    IssueAssignee,
    Milestone,
    Notification,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Alpha", identifier="ALP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def states(project):
    return {
        group: State.objects.create(name=group.title(), group=group, project=project, workspace=project.workspace)
        for group in ("backlog", "started", "completed")
    }


def _issue(project, state, name="Item", **kwargs):
    return Issue.objects.create(name=name, project=project, workspace=project.workspace, state=state, **kwargs)


def _assign(issue, user):
    IssueAssignee.objects.create(issue=issue, assignee=user, project=issue.project, workspace=issue.workspace)


def _mention(workspace, project, issue, user):
    return Notification.objects.create(
        workspace=workspace,
        project=project,
        entity_identifier=issue.id,
        entity_name="issue",
        title="t",
        sender="in_app:issue_activities:mentioned",
        receiver=user,
    )


def _complete(issue, actor, states, source="app", when=None):
    issue.state = states["completed"]
    issue.save()
    activity = IssueActivity.objects.create(
        issue=issue,
        project=issue.project,
        workspace=issue.workspace,
        actor=actor,
        verb="updated",
        field="state",
        new_identifier=states["completed"].id,
        source=source,
    )
    if when is not None:
        IssueActivity.objects.filter(pk=activity.pk).update(created_at=when)
    return activity


def _url(workspace, suffix=""):
    return f"/api/workspaces/{workspace.slug}/brief/{suffix}"


@pytest.mark.contract
@pytest.mark.django_db
def test_needs_me_orders_overdue_first(session_client, workspace, project, states, create_user):
    today = timezone.now().date()
    milestone = Milestone.objects.create(
        title="M", project=project, workspace=workspace, target_date=today + timedelta(days=3)
    )
    later = _issue(project, states["started"], "later", target_date=today + timedelta(days=9))
    via_milestone = _issue(project, states["started"], "via milestone", milestone=milestone)
    undated = _issue(project, states["started"], "undated")
    overdue = _issue(project, states["started"], "overdue", target_date=today - timedelta(days=2))
    done = _issue(project, states["completed"], "finished", target_date=today - timedelta(days=5))
    for issue in (later, via_milestone, undated, overdue, done):
        _assign(issue, create_user)
    mentioned = _issue(project, states["backlog"], "mentioned", target_date=today + timedelta(days=1))
    _mention(workspace, project, mentioned, create_user)
    old = _issue(project, states["backlog"], "old mention")
    stale_note = _mention(workspace, project, old, create_user)
    Notification.objects.filter(pk=stale_note.pk).update(created_at=timezone.now() - timedelta(days=15))
    asker = User.objects.create(email="bot@example.com", username="bot", first_name="Bot")
    asked = _issue(project, states["started"], "asked", target_date=today + timedelta(days=2))
    decision = DecisionRequest.objects.create(
        issue=asked,
        project=project,
        workspace=workspace,
        asked_user=create_user,
        question="Ship?",
        created_by=asker,
    )

    response = session_client.get(_url(workspace))
    assert response.status_code == 200, response.data
    rows = [(r["issue"]["name"], r["why"], r["overdue"]) for r in response.data["needs_me"]]
    assert rows == [
        ("overdue", "assigned", True),
        ("mentioned", "mentioned", False),
        ("asked", "decision", False),
        ("via milestone", "assigned", False),
        ("later", "assigned", False),
        ("undated", "assigned", False),
    ]
    by_name = {r["issue"]["name"]: r for r in response.data["needs_me"]}
    assert by_name["asked"]["decision_id"] == str(decision.id)
    assert by_name["via milestone"]["due"] == (today + timedelta(days=3)).isoformat()
    assert by_name["undated"]["due"] is None and by_name["later"]["decision_id"] is None
    assert set(response.data) == {"since", "generated_at", "needs_me", "blocked", "done", "milestones_due", "projects"}


@pytest.mark.contract
@pytest.mark.django_db
def test_done_marks_agent_vs_person(session_client, workspace, project, states, create_user):
    by_agent = _issue(project, states["started"], "by agent")
    by_person = _issue(project, states["started"], "by person")
    _complete(by_agent, create_user, states, source="api")
    _complete(by_person, create_user, states)

    response = session_client.get(_url(workspace))
    assert response.status_code == 200
    (group,) = response.data["done"]
    assert group["project_identifier"] == "ALP" and group["project_id"] == str(project.id)
    flags = {i["issue"]["name"]: i["by"]["is_agent"] for i in group["items"]}
    assert flags == {"by agent": True, "by person": False}
    assert group["items"][0]["by"]["id"] == str(create_user.id)
    assert group["items"][0]["completed_at"]


@pytest.mark.contract
@pytest.mark.django_db
def test_done_defaults_to_last_24h_on_first_visit(session_client, workspace, project, states, create_user):
    recent = _issue(project, states["started"], "recent")
    old = _issue(project, states["started"], "old")
    _complete(recent, create_user, states, when=timezone.now() - timedelta(hours=2))
    _complete(old, create_user, states, when=timezone.now() - timedelta(hours=30))

    response = session_client.get(_url(workspace))
    names = [i["issue"]["name"] for g in response.data["done"] for i in g["items"]]
    assert names == ["recent"]


@pytest.mark.contract
@pytest.mark.django_db
def test_old_last_seen_is_clamped_to_a_week(session_client, workspace, project, states, create_user):
    now = timezone.now()
    BriefVisit.objects.create(workspace=workspace, user=create_user, last_seen_at=now - timedelta(days=30))
    within = _issue(project, states["started"], "within")
    too_old = _issue(project, states["started"], "too old")
    _complete(within, create_user, states, when=now - timedelta(days=6))
    _complete(too_old, create_user, states, when=now - timedelta(days=8))

    response = session_client.get(_url(workspace))
    names = [i["issue"]["name"] for g in response.data["done"] for i in g["items"]]
    assert names == ["within"]
    since = timezone.datetime.fromisoformat(response.data["since"])
    assert timedelta(days=7) - timedelta(minutes=1) < now - since <= timedelta(days=7) + timedelta(minutes=1)


@pytest.mark.contract
@pytest.mark.django_db
def test_seen_moves_the_window(session_client, workspace, project, states, create_user):
    item = _issue(project, states["started"], "item")
    _complete(item, create_user, states, when=timezone.now() - timedelta(hours=2))
    assert len(session_client.get(_url(workspace)).data["done"]) == 1

    seen = session_client.post(_url(workspace, "seen/"))
    assert seen.status_code == 200
    assert BriefVisit.objects.get(workspace=workspace, user=create_user).last_seen_at <= timezone.now()
    assert session_client.get(_url(workspace)).data["done"] == []
    session_client.post(_url(workspace, "seen/"))
    assert BriefVisit.objects.filter(workspace=workspace, user=create_user).count() == 1


@pytest.mark.contract
@pytest.mark.django_db
def test_milestones_due_within_week(session_client, workspace, project, states, create_user):
    today = timezone.now().date()

    def make(title, days):
        return Milestone.objects.create(
            title=title, project=project, workspace=workspace, target_date=today + timedelta(days=days)
        )

    soon, late, far, empty = make("Soon", 5), make("Late", -1), make("Far", 30), make("Empty", 2)
    for milestone in (soon, far):
        mine = _issue(project, states["started"], "mine", milestone=milestone)
        _assign(mine, create_user)
        _assign(mine, User.objects.create(email=f"x{milestone.title}@example.com", username=f"x{milestone.title}"))
        _issue(project, states["backlog"], "other", milestone=milestone)
        _issue(project, states["completed"], "done", milestone=milestone)
    _issue(project, states["started"], "late item", milestone=late)
    _issue(project, states["completed"], "only done", milestone=empty)

    response = session_client.get(_url(workspace))
    rows = {m["title"]: m for m in response.data["milestones_due"]}
    assert set(rows) == {"Soon", "Late"}
    assert rows["Soon"] == {
        "id": str(soon.id),
        "title": "Soon",
        "project_identifier": "ALP",
        "target_date": (today + timedelta(days=5)).isoformat(),
        "open": 2,
        "total": 3,
        "assigned_to_me_open": 1,
    }
    assert [m["title"] for m in response.data["milestones_due"]] == ["Late", "Soon"]


@pytest.mark.contract
@pytest.mark.django_db
def test_brief_hides_projects_user_is_not_in(session_client, workspace, project, states, create_user):
    other_owner = User.objects.create(email="o@example.com", username="owner", first_name="Owner")
    WorkspaceMember.objects.create(workspace=workspace, member=other_owner, role=20)
    hidden = Project.objects.create(name="Hidden", identifier="HID", workspace=workspace, created_by=other_owner)
    ProjectMember.objects.create(project=hidden, member=other_owner, workspace=workspace, role=20)
    hidden_state = State.objects.create(name="Started", group="started", project=hidden, workspace=workspace)
    hidden_done = State.objects.create(name="Done", group="completed", project=hidden, workspace=workspace)
    secret = _issue(hidden, hidden_state, "secret", target_date=timezone.now().date())
    _assign(secret, create_user)
    _mention(workspace, hidden, secret, create_user)
    finished = _issue(hidden, hidden_state, "secret done")
    _complete(finished, other_owner, {"completed": hidden_done})
    milestone = Milestone.objects.create(
        title="Hidden M", project=hidden, workspace=workspace, target_date=timezone.now().date()
    )
    _issue(hidden, hidden_state, "in milestone", milestone=milestone)
    visible = _issue(project, states["started"], "visible")
    _assign(visible, create_user)

    response = session_client.get(_url(workspace))
    assert [r["issue"]["name"] for r in response.data["needs_me"]] == ["visible"]
    assert response.data["done"] == [] and response.data["milestones_due"] == []


@pytest.mark.contract
@pytest.mark.django_db
def test_removed_assignee_is_not_counted(session_client, workspace, project, states, create_user):
    today = timezone.now().date()
    milestone = Milestone.objects.create(title="M", project=project, workspace=workspace, target_date=today)
    item = _issue(project, states["started"], "dropped", milestone=milestone)
    _assign(item, create_user)
    before = session_client.get(_url(workspace)).data
    assert [r["issue"]["name"] for r in before["needs_me"]] == ["dropped"]
    assert before["milestones_due"][0]["assigned_to_me_open"] == 1

    IssueAssignee.objects.get(issue=item, assignee=create_user).delete()
    after = session_client.get(_url(workspace)).data
    assert after["needs_me"] == []
    assert after["milestones_due"][0]["assigned_to_me_open"] == 0


@pytest.mark.contract
@pytest.mark.django_db
def test_one_row_per_item_with_priority(session_client, workspace, project, states, create_user):
    asker = User.objects.create(email="bot2@example.com", username="bot2", first_name="Bot")
    twice = _issue(project, states["started"], "twice mentioned")
    _mention(workspace, project, twice, create_user)
    _mention(workspace, project, twice, create_user)
    everything = _issue(project, states["started"], "everything")
    _assign(everything, create_user)
    _mention(workspace, project, everything, create_user)
    first = DecisionRequest.objects.create(
        issue=everything,
        project=project,
        workspace=workspace,
        asked_user=create_user,
        question="One?",
        created_by=asker,
    )
    DecisionRequest.objects.create(
        issue=everything,
        project=project,
        workspace=workspace,
        asked_user=create_user,
        question="Two?",
        created_by=asker,
    )
    mention_assigned = _issue(project, states["started"], "mention and assigned")
    _assign(mention_assigned, create_user)
    _mention(workspace, project, mention_assigned, create_user)

    rows = {r["issue"]["name"]: r for r in session_client.get(_url(workspace)).data["needs_me"]}
    assert len(session_client.get(_url(workspace)).data["needs_me"]) == 3
    assert rows["twice mentioned"]["why"] == "mentioned"
    assert rows["everything"]["why"] == "decision" and rows["everything"]["decision_id"] == str(first.id)
    assert rows["mention and assigned"]["why"] == "mentioned" and rows["mention and assigned"]["decision_id"] is None


@pytest.mark.contract
@pytest.mark.django_db
def test_today_uses_the_users_timezone(session_client, workspace, project, states, create_user):
    from datetime import datetime
    from unittest import mock
    from zoneinfo import ZoneInfo

    create_user.user_timezone = "Pacific/Auckland"
    create_user.save()
    fixed = datetime(2026, 5, 10, 20, 0, tzinfo=ZoneInfo("UTC"))  # already May 11 in Auckland
    item = _issue(project, states["started"], "due on utc day", target_date=fixed.date())
    _assign(item, create_user)
    soon = Milestone.objects.create(
        title="Edge", project=project, workspace=workspace, target_date=datetime(2026, 5, 18).date()
    )
    _issue(project, states["started"], "open", milestone=soon)
    with mock.patch("plane.utils.brief.timezone.now", return_value=fixed):
        data = session_client.get(_url(workspace)).data
    assert data["needs_me"][0]["overdue"] is True  # May 10 is yesterday for this person
    assert [m["title"] for m in data["milestones_due"]] == ["Edge"]  # May 11 + 7 reaches May 18

    create_user.user_timezone = "Europe/London"  # still May 10 there
    create_user.save()
    with mock.patch("plane.utils.brief.timezone.now", return_value=fixed):
        data = session_client.get(_url(workspace)).data
    assert data["needs_me"][0]["overdue"] is False and data["milestones_due"] == []


def test_untouched_utc_user_gets_kolkata_dates(session_client, workspace, project, states, create_user):
    from datetime import datetime
    from unittest import mock
    from zoneinfo import ZoneInfo

    assert create_user.user_timezone == "UTC"
    fixed = datetime(2026, 5, 10, 20, 0, tzinfo=ZoneInfo("UTC"))  # already May 11 in Kolkata
    item = _issue(project, states["started"], "due on utc day", target_date=fixed.date())
    _assign(item, create_user)
    soon = Milestone.objects.create(
        title="Edge", project=project, workspace=workspace, target_date=datetime(2026, 5, 18).date()
    )
    _issue(project, states["started"], "open", milestone=soon)
    with mock.patch("plane.utils.brief.timezone.now", return_value=fixed):
        data = session_client.get(_url(workspace)).data
    assert data["needs_me"][0]["overdue"] is True
    assert [m["title"] for m in data["milestones_due"]] == ["Edge"]
