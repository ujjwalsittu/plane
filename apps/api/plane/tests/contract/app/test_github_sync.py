# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Linking GitHub pull requests, branches and commits to work items."""

import pytest

from plane.db.models import (
    GitHubInstallation,
    GitHubPullRequest,
    GitHubRepositoryLink,
    GitHubWebhookDelivery,
    GitHubWorkItemLink,
    Issue,
    Project,
    ProjectMember,
)
from plane.utils import github_app, github_sync
from plane.utils.github_integration import process_delivery

REPO = {"id": 501, "full_name": "acme/api", "html_url": "https://github.com/acme/api"}


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Platform", identifier="PLAT", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def other_project(workspace, create_user):
    return Project.objects.create(name="Other", identifier="OTH", workspace=workspace, created_by=create_user)


@pytest.fixture
def installation(workspace):
    return GitHubInstallation.objects.create(workspace=workspace, installation_id=77, account_login="acme")


@pytest.fixture
def repo_link(project, installation):
    return GitHubRepositoryLink.objects.create(
        project=project, installation=installation, repository_id=501, full_name="acme/api", html_url=REPO["html_url"]
    )


@pytest.fixture
def issues(project, other_project):
    first = Issue.objects.create(name="Deploy script", project=project, workspace=project.workspace)
    second = Issue.objects.create(name="Second", project=project, workspace=project.workspace)
    foreign = Issue.objects.create(name="Elsewhere", project=other_project, workspace=project.workspace)
    return first, second, foreign


def deliver(event, payload, action=""):
    payload = {"installation": {"id": 77}, "repository": REPO, **payload}
    process_delivery(GitHubWebhookDelivery(delivery_id="x", event=event, action=action, payload=payload))


def pr_payload(number=7, title="Add deploy script", body="", head="main", sha="abc", **extra):
    return {
        "number": number,
        "title": title,
        "body": body,
        "html_url": f"https://github.com/acme/api/pull/{number}",
        "state": "open",
        "draft": False,
        "merged_at": None,
        "closed_at": None,
        "head": {"ref": head, "sha": sha},
        "base": {"ref": "main"},
        "user": {"login": "dev"},
        "created_at": "2026-11-19T10:00:00Z",
        "updated_at": "2026-11-19T10:00:00Z",
        **extra,
    }


@pytest.mark.unit
def test_reference_parsing():
    assert github_sync.references("Fixes PLAT-12 and plat-3", "plat-12-deploy-script") == [("PLAT", 12), ("PLAT", 3)]
    assert github_sync.references("XPLAT-1 v2-3 PLAT-") == [("XPLAT", 1), ("V2", 3)]
    assert github_sync.references("") == []


@pytest.mark.django_db
def test_pull_request_links_and_status(repo_link, issues):
    first, second, foreign = issues
    deliver(
        "pull_request",
        {
            "pull_request": pr_payload(
                title=f"PLAT-{first.sequence_id}: deploy",
                body=f"Also OTH-{foreign.sequence_id}",
                head=f"plat-{second.sequence_id}-x",
            )
        },
        "opened",
    )
    linked = set(GitHubWorkItemLink.objects.values_list("issue_id", flat=True))
    # Both PLAT items; OTH isn't linked to the repository.
    assert linked == {first.id, second.id}

    payload = github_sync.work_item_payload(first)
    assert payload["enabled"] is True
    assert payload["pull_requests"][0]["status"] == "open" and payload["pull_requests"][0]["number"] == 7

    deliver("pull_request_review", {"pull_request": pr_payload(), "review": {"state": "APPROVED"}}, "submitted")
    deliver(
        "check_suite",
        {"check_suite": {"head_sha": "abc", "status": "completed", "conclusion": "failure", "app": {"slug": "ci"}}},
        "completed",
    )
    deliver("status", {"sha": "abc", "state": "success", "context": "lint"})
    pr = github_sync.work_item_payload(first)["pull_requests"][0]
    assert pr["review_state"] == "approved" and pr["checks_state"] == "failure"

    # New commits drop earlier check results.
    deliver("pull_request", {"pull_request": pr_payload(title=f"PLAT-{first.sequence_id}", sha="def")}, "synchronize")
    assert github_sync.work_item_payload(first)["pull_requests"][0]["checks_state"] == ""

    merged = pr_payload(title=f"PLAT-{first.sequence_id}", sha="def", state="closed", merged_at="2026-11-19T12:00:00Z")
    deliver("pull_request", {"pull_request": merged}, "closed")
    assert github_sync.work_item_payload(first)["pull_requests"][0]["status"] == "merged"
    assert GitHubPullRequest.objects.count() == 1
    assert GitHubWorkItemLink.objects.filter(issue=first).count() == 1


@pytest.mark.django_db
def test_branches_and_commits(repo_link, issues):
    first, second, _ = issues
    branch = f"plat-{first.sequence_id}-deploy"
    deliver("create", {"ref_type": "branch", "ref": branch, "sender": {"login": "dev"}})
    deliver(
        "push",
        {
            "ref": f"refs/heads/{branch}",
            "created": False,
            "pusher": {"name": "dev"},
            "commits": [
                {
                    "id": "c1",
                    "message": f"Wire it up (PLAT-{second.sequence_id})\n\nDetails",
                    "url": "https://x/c1",
                    "author": {"username": "dev"},
                    "timestamp": "2026-11-19T10:00:00Z",
                },
                {"id": "c2", "message": "No reference", "url": "https://x/c2", "author": {"name": "Dev"}},
            ],
        },
    )
    payload = github_sync.work_item_payload(first)
    assert payload["branches"] == [
        {
            "id": payload["branches"][0]["id"],
            "repository": "acme/api",
            "name": branch,
            "url": f"{REPO['html_url']}/tree/{branch}",
        }
    ]
    commits = github_sync.work_item_payload(second)["commits"]
    assert [(c["sha"], c["message"]) for c in commits] == [("c1", f"Wire it up (PLAT-{second.sequence_id})")]

    # Redelivery doesn't duplicate; deleting the branch drops its link.
    deliver("create", {"ref_type": "branch", "ref": branch})
    assert GitHubWorkItemLink.objects.filter(kind="branch").count() == 1
    deliver("delete", {"ref_type": "branch", "ref": branch})
    assert not GitHubWorkItemLink.objects.filter(kind="branch").exists()


@pytest.mark.django_db
def test_unlinked_repository_is_ignored(installation, issues):
    first, _, _ = issues
    deliver("pull_request", {"pull_request": pr_payload(title=f"PLAT-{first.sequence_id}")}, "opened")
    assert not GitHubPullRequest.objects.exists() and not GitHubWorkItemLink.objects.exists()


@pytest.mark.django_db
def test_backfill_links_open_pull_requests(repo_link, issues, monkeypatch):
    first, _, _ = issues
    monkeypatch.setattr(
        github_app,
        "repository_pull_requests",
        lambda installation_id, full_name: [pr_payload(number=3, title=f"PLAT-{first.sequence_id} wip")],
    )
    assert github_sync.backfill_repository(repo_link) == 1
    assert github_sync.work_item_payload(first)["pull_requests"][0]["number"] == 3


@pytest.mark.unit
def test_branch_name():
    issue = Issue(name="Deploy script: verify & restart!", sequence_id=12)
    issue.project = Project(identifier="PLAT")
    assert github_sync.branch_name(issue) == "plat-12-deploy-script-verify-restart"
    issue.name = "Link PRs, branches and commits to work items; GitHub panel"
    assert github_sync.branch_name(issue) == "plat-12-link-prs-branches-and-commits-to-work"


@pytest.mark.contract
@pytest.mark.django_db
def test_work_item_endpoints(session_client, api_key_client, workspace, project, repo_link, issues):
    first, _, _ = issues
    deliver("pull_request", {"pull_request": pr_payload(title=f"PLAT-{first.sequence_id}")}, "opened")
    app = session_client.get(f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{first.id}/github/")
    assert app.status_code == 200 and app.data["pull_requests"][0]["number"] == 7
    external = api_key_client.get(
        f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/{first.id}/github"
    )
    assert external.status_code == 200 and external.data["branch_name"].startswith(f"plat-{first.sequence_id}")
