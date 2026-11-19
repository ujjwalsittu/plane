# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Pull request events moving work items between states."""

import pytest

from plane.db.models import (
    GitHubInstallation,
    GitHubRepositoryLink,
    GitHubWebhookDelivery,
    Issue,
    IssueActivity,
    Project,
    ProjectMember,
    State,
)
from plane.utils import github_automation
from plane.utils.github_integration import process_delivery

REPO = {"id": 501, "full_name": "acme/api", "html_url": "https://github.com/acme/api", "default_branch": "main"}


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Platform", identifier="PLAT", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def states(project):
    def make(name, group, sequence):
        return State.objects.create(
            name=name, group=group, sequence=sequence, project=project, workspace=project.workspace
        )

    return {
        "backlog": make("Backlog", "backlog", 1),
        "todo": make("Todo", "unstarted", 2),
        "progress": make("In Progress", "started", 3),
        "review": make("In Review", "started", 4),
        "done": make("Done", "completed", 5),
        "cancelled": make("Cancelled", "cancelled", 6),
    }


@pytest.fixture
def linked(project, workspace):
    installation = GitHubInstallation.objects.create(workspace=workspace, installation_id=77, account_login="acme")
    return GitHubRepositoryLink.objects.create(
        project=project, installation=installation, repository_id=501, full_name="acme/api"
    )


def make_issue(project, state, name="Item"):
    return Issue.objects.create(name=name, project=project, workspace=project.workspace, state=state)


def pr(number=7, title="", body="", head="feature", draft=False, merged=False, base="main", state="open"):
    return {
        "number": number,
        "title": title,
        "body": body,
        "html_url": f"https://github.com/acme/api/pull/{number}",
        "state": state,
        "draft": draft,
        "merged": merged,
        "merged_at": "2026-11-19T12:00:00Z" if merged else None,
        "head": {"ref": head, "sha": "abc"},
        "base": {"ref": base},
        "user": {"login": "dev"},
    }


def deliver(action, data):
    payload = {"installation": {"id": 77}, "repository": REPO, "action": action, "pull_request": data}
    process_delivery(GitHubWebhookDelivery(delivery_id="x", event="pull_request", action=action, payload=payload))


@pytest.mark.unit
def test_primary_references():
    data = {"title": "Tidy up", "head": {"ref": "plat-3-x"}, "body": "Fixes PLAT-4, closes: plat-5. See PLAT-6."}
    assert github_automation.primary_references(data) == [("PLAT", 3), ("PLAT", 4), ("PLAT", 5)]
    assert github_automation.primary_references(data, close_keywords=False) == [("PLAT", 3)]


@pytest.mark.django_db
def test_default_rules(project, states):
    rules = github_automation.rules_for(project)
    assert rules.draft_state == states["progress"] and rules.open_state == states["progress"]
    assert rules.review_requested_state == states["review"] and rules.merge_state == states["done"]


@pytest.mark.django_db
def test_pull_request_lifecycle_moves_items(project, states, linked, monkeypatch):
    from plane.bgtasks import issue_activities_task

    task = issue_activities_task.issue_activity
    monkeypatch.setattr(task, "delay", lambda **kwargs: task(**kwargs))
    item = make_issue(project, states["todo"])
    mentioned = make_issue(project, states["todo"], "Only mentioned")
    title = f"PLAT-{item.sequence_id}: deploy"
    body = f"See PLAT-{mentioned.sequence_id}"

    deliver("opened", pr(title=title, body=body, draft=True))
    item.refresh_from_db()
    mentioned.refresh_from_db()
    assert item.state == states["progress"]
    assert mentioned.state == states["todo"]  # linked, not moved

    deliver("review_requested", pr(title=title, body=body))
    item.refresh_from_db()
    assert item.state == states["review"]

    # Re-marking ready doesn't pull it back from review (forward only).
    deliver("ready_for_review", pr(title=title, body=body))
    item.refresh_from_db()
    assert item.state == states["review"]

    deliver("closed", pr(title=title, body=body, merged=True, state="closed"))
    item.refresh_from_db()
    assert item.state == states["done"] and item.completed_at is not None

    activity = IssueActivity.objects.filter(issue=item, field="state").order_by("created_at")
    assert [a.new_value for a in activity] == ["In Progress", "In Review", "Done"]
    assert {a.actor.display_name for a in activity} == {"GitHub"}
    assert activity.first().actor.is_bot


@pytest.mark.django_db
def test_merge_rules(project, states, linked):
    fixed = make_issue(project, states["progress"])
    other_branch = make_issue(project, states["progress"])
    closed_only = make_issue(project, states["progress"])
    done = make_issue(project, states["cancelled"])

    deliver("closed", pr(title="Cleanup", body=f"Fixes PLAT-{fixed.sequence_id}", merged=True, state="closed"))
    deliver(
        "closed", pr(number=8, title=f"PLAT-{other_branch.sequence_id}", merged=True, base="release", state="closed")
    )
    deliver("closed", pr(number=9, title=f"PLAT-{closed_only.sequence_id}", state="closed"))
    deliver("opened", pr(number=10, title=f"PLAT-{done.sequence_id}"))
    for issue in (fixed, other_branch, closed_only, done):
        issue.refresh_from_db()
    assert fixed.state == states["done"]
    assert other_branch.state == states["progress"]  # merged into a non-default branch
    assert closed_only.state == states["progress"]  # closed without merging
    assert done.state == states["cancelled"]  # never leaves cancelled


@pytest.mark.contract
@pytest.mark.django_db
def test_rules_endpoints_and_disabling(session_client, workspace, project, states, linked):
    listed = session_client.get(f"/api/workspaces/{workspace.slug}/github/automations/")
    assert listed.status_code == 200
    assert listed.data[0]["is_default"] is True and listed.data[0]["merge_state"] == str(states["done"].id)

    url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/github/automation/"
    bad = session_client.patch(
        url, {"open_state": str(states["done"].id), "review_requested_state": "nope"}, format="json"
    )
    assert bad.status_code == 400
    saved = session_client.patch(url, {"enabled": False}, format="json")
    assert saved.status_code == 200 and saved.data["enabled"] is False and saved.data["is_default"] is False

    item = make_issue(project, states["todo"])
    deliver("opened", pr(title=f"PLAT-{item.sequence_id}"))
    item.refresh_from_db()
    assert item.state == states["todo"]

    session_client.patch(url, {"enabled": True, "open_state": None}, format="json")
    deliver("reopened", pr(title=f"PLAT-{item.sequence_id}"))
    item.refresh_from_db()
    assert item.state == states["todo"]  # no rule for opened PRs
