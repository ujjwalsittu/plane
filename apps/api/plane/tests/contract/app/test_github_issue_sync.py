# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Two-way sync of GitHub issues and work items."""

import pytest

from plane.db.models import (
    GitHubCommentLink,
    GitHubInstallation,
    GitHubIssueLink,
    GitHubRepositoryLink,
    GitHubWebhookDelivery,
    Issue,
    IssueComment,
    Label,
    Project,
    ProjectMember,
    State,
    User,
)
from plane.utils import github_app, github_issue_sync
from plane.utils.github_automation import bot_user
from plane.utils.github_integration import process_delivery

REPO = {"id": 501, "full_name": "acme/api", "html_url": "https://github.com/acme/api", "default_branch": "main"}


@pytest.fixture(autouse=True)
def app_settings(settings):
    settings.GITHUB_APP_SLUG = "plane-test"


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Platform", identifier="PLAT", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    for name, group, sequence, default in [
        ("Backlog", "backlog", 1, True),
        ("In Progress", "started", 2, False),
        ("Done", "completed", 3, False),
        ("Cancelled", "cancelled", 4, False),
    ]:
        State.objects.create(
            name=name, group=group, sequence=sequence, default=default, project=project, workspace=workspace
        )
    return project


@pytest.fixture
def repo_link(project, workspace):
    installation = GitHubInstallation.objects.create(workspace=workspace, installation_id=77, account_login="acme")
    return GitHubRepositoryLink.objects.create(
        project=project, installation=installation, repository_id=501, full_name="acme/api", issue_sync=True
    )


@pytest.fixture
def github(monkeypatch):
    """Records what Plane sends to GitHub."""
    calls = []
    counter = {"issue": 100, "comment": 900}

    def create_issue(installation_id, full_name, data):
        counter["issue"] += 1
        calls.append(("create_issue", data))
        return {"id": counter["issue"], "number": counter["issue"] - 100, "html_url": "https://github.com/x"}

    def update_issue(installation_id, full_name, number, data):
        calls.append(("update_issue", number, data))
        return {}

    def create_comment(installation_id, full_name, number, body):
        counter["comment"] += 1
        calls.append(("create_comment", number, body))
        return {"id": counter["comment"]}

    def update_comment(installation_id, full_name, comment_id, body):
        calls.append(("update_comment", comment_id, body))

    def delete_comment(installation_id, full_name, comment_id):
        calls.append(("delete_comment", comment_id))

    monkeypatch.setattr(github_app, "create_issue", create_issue)
    monkeypatch.setattr(github_app, "update_issue", update_issue)
    monkeypatch.setattr(github_app, "create_issue_comment", create_comment)
    monkeypatch.setattr(github_app, "update_issue_comment", update_comment)
    monkeypatch.setattr(github_app, "delete_issue_comment", delete_comment)
    return calls


def gh_issue(
    number=5, title="Crash on save", body="It **crashes**.", state="open", labels=(), assignees=(), reason=None
):
    return {
        "id": 5000 + number,
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "state_reason": reason,
        "html_url": f"https://github.com/acme/api/issues/{number}",
        "labels": [{"name": name} for name in labels],
        "assignees": [{"login": login} for login in assignees],
    }


def deliver(event, action, sender="octocat", **payload):
    payload = {"installation": {"id": 77}, "repository": REPO, "sender": {"login": sender}, "action": action, **payload}
    process_delivery(GitHubWebhookDelivery(delivery_id="x", event=event, action=action, payload=payload))


@pytest.mark.django_db
def test_github_issue_creates_and_updates_work_item(project, repo_link, create_user, workspace):
    github_issue_sync.set_mapping(workspace, create_user.id, "@dev")
    deliver("issues", "opened", issue=gh_issue(labels=["bug"], assignees=["dev", "stranger"]))
    link = GitHubIssueLink.objects.get(number=5)
    issue = Issue.objects.get(pk=link.issue_id)
    assert issue.name == "Crash on save" and "<strong>crashes</strong>" in issue.description_html
    assert list(issue.labels.values_list("name", flat=True)) == ["bug"]
    assert list(issue.assignees.values_list("id", flat=True)) == [create_user.id]  # stranger isn't mapped
    assert issue.state.name == "Backlog"

    deliver("issues", "closed", issue=gh_issue(state="closed", reason="completed", labels=["bug"], assignees=["dev"]))
    issue.refresh_from_db()
    assert issue.state.name == "Done"
    deliver("issues", "reopened", issue=gh_issue(labels=["bug"], assignees=["dev"]))
    issue.refresh_from_db()
    assert issue.state.name == "Backlog"
    deliver("issues", "closed", issue=gh_issue(state="closed", reason="not_planned"))
    issue.refresh_from_db()
    assert issue.state.name == "Cancelled"

    # The app's own writes come back as webhooks from "<app>[bot]"; they are ignored.
    deliver("issues", "edited", sender="plane-test[bot]", issue=gh_issue(title="Echo"))
    issue.refresh_from_db()
    assert issue.name == "Crash on save"


@pytest.mark.django_db
def test_closed_and_unsynced_repositories_are_ignored(project, repo_link):
    deliver("issues", "closed", issue=gh_issue(number=9, state="closed"))
    repo_link.issue_sync = False
    repo_link.save()
    deliver("issues", "opened", issue=gh_issue(number=10))
    assert not GitHubIssueLink.objects.exists()


@pytest.mark.django_db
def test_github_comments(project, repo_link):
    deliver("issues", "opened", issue=gh_issue())
    link = GitHubIssueLink.objects.get()
    comment = {"id": 77, "body": "Same here", "user": {"login": "octocat"}}
    deliver("issue_comment", "created", issue=gh_issue(), comment=comment)
    synced = IssueComment.objects.get(issue_id=link.issue_id)
    assert "<strong>octocat</strong> on GitHub" in synced.comment_html and synced.actor.username == "plane-github-bot"
    deliver("issue_comment", "edited", issue=gh_issue(), comment={**comment, "body": "Same here, v2"})
    synced.refresh_from_db()
    assert "v2" in synced.comment_html
    deliver("issue_comment", "deleted", issue=gh_issue(), comment=comment)
    assert not IssueComment.objects.filter(issue_id=link.issue_id).exists()


@pytest.mark.django_db
def test_plane_changes_push_to_github(project, repo_link, create_user, workspace, github):
    github_issue_sync.set_mapping(workspace, create_user.id, "dev")
    done = State.objects.get(project=project, name="Done")
    label = Label.objects.create(name="ui", project=project, workspace=workspace)
    issue = Issue.objects.create(
        name="From Plane", description_html="<p>Hello <em>there</em></p>", project=project, workspace=workspace
    )
    issue.labels.add(label, through_defaults={"project": project, "workspace": workspace})

    # A new work item in a project with exactly one syncing repository becomes a GitHub issue.
    assert github_issue_sync.wants_push("issue.activity.created", issue.id, project.id, create_user.id)
    github_issue_sync.push_issue(issue)
    kind, data = github[0]
    assert kind == "create_issue" and data["title"] == "From Plane" and data["labels"] == ["ui"]
    assert "*there*" in data["body"] or "_there_" in data["body"]

    # Nothing changed: nothing is sent.
    github_issue_sync.push_issue(issue)
    assert len(github) == 1

    issue.state = done
    issue.save()
    issue.refresh_from_db()
    github_issue_sync.push_issue(issue)
    assert github[-1][0] == "update_issue" and github[-1][2]["state"] == "closed"
    assert github[-1][2]["state_reason"] == "completed"

    comment = IssueComment.objects.create(
        issue=issue, project=project, workspace=workspace, actor=create_user, comment_html="<p>Shipped</p>"
    )
    github_issue_sync.push_issue(issue)
    assert github[-1][0] == "create_comment" and "commented in Plane" in github[-1][2] and "Shipped" in github[-1][2]
    comment.comment_html = "<p>Shipped!</p>"
    comment.save()
    github_issue_sync.push_issue(issue)
    assert github[-1][0] == "update_comment"
    comment.delete()
    github_issue_sync.push_issue(issue)
    assert github[-1][0] == "delete_comment" and not GitHubCommentLink.objects.exists()


@pytest.mark.django_db
def test_bot_changes_are_not_pushed(project, repo_link, create_user):
    issue = Issue.objects.create(name="X", project=project, workspace=project.workspace)
    assert not github_issue_sync.wants_push("issue.activity.created", issue.id, project.id, bot_user().id)
    assert not github_issue_sync.wants_push("issue.activity.deleted", issue.id, project.id, create_user.id)
    # Two syncing repositories: no single place to create the issue.
    GitHubRepositoryLink.objects.create(
        project=project, installation=repo_link.installation, repository_id=502, full_name="acme/web", issue_sync=True
    )
    assert not github_issue_sync.wants_push("issue.activity.created", issue.id, project.id, create_user.id)


@pytest.mark.django_db
def test_import_open_issues(project, repo_link, monkeypatch):
    monkeypatch.setattr(
        github_app,
        "repository_open_issues",
        lambda i, n: [gh_issue(1, title="One"), {**gh_issue(2, title="Two"), "comments": 1}],
    )
    monkeypatch.setattr(
        github_app,
        "issue_comments",
        lambda i, n, number: [
            {"id": 1, "body": "hi", "user": {"login": "octocat"}},
            {"id": 2, "body": "from plane", "user": {"login": "plane-test[bot]"}},
        ],
    )
    assert github_issue_sync.import_open_issues(repo_link) == 2
    assert sorted(Issue.objects.filter(project=project).values_list("name", flat=True)) == ["One", "Two"]
    assert IssueComment.objects.count() == 1  # the app's own comment isn't imported back
    repo_link.refresh_from_db()
    assert repo_link.issue_sync_imported_at is not None


@pytest.mark.contract
@pytest.mark.django_db
def test_endpoints(session_client, workspace, project, repo_link, create_user, monkeypatch):
    from plane.bgtasks import github_webhook_task

    queued = []
    monkeypatch.setattr(github_webhook_task.import_github_issues, "delay", lambda link_id: queued.append(link_id))
    repo_link.issue_sync = False
    repo_link.save()
    url = f"/api/workspaces/{workspace.slug}/github/links/{repo_link.id}/"
    assert session_client.patch(url, {"issue_sync": "yes"}, format="json").status_code == 400
    response = session_client.patch(url, {"issue_sync": True}, format="json")
    assert response.status_code == 200 and response.data["issue_sync"] is True

    people = f"/api/workspaces/{workspace.slug}/github/people/"
    saved = session_client.put(people, {"user": str(create_user.id), "github_login": "@Dev"}, format="json")
    assert saved.data == [{"user": str(create_user.id), "github_login": "Dev"}]
    outsider = User.objects.create(email="out@plane.so", username="out")
    assert session_client.put(people, {"user": str(outsider.id), "github_login": "x"}, format="json").status_code == 400
    assert session_client.put(people, {"user": str(create_user.id), "github_login": ""}, format="json").data == []
