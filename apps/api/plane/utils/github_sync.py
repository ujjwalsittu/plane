# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Links GitHub pull requests, branches and commits to work items.

A work item is referenced by its identifier (e.g. PLAT-12, or plat-12 in a branch name) in a PR's
title, body or head branch, a branch name, or a commit message. Only projects linked to the
repository are considered, so an identifier-like string in an unrelated repository is ignored."""

# Python imports
import re

# Django imports
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.text import slugify

# Module imports
from plane.db.models import (
    GitHubInstallation,
    GitHubPullRequest,
    GitHubRepositoryLink,
    GitHubWorkItemLink,
    Issue,
)
from plane.utils import github_app

# PROJ-12, proj-12, proj_12 is not matched; the identifier can't be glued to a preceding letter/digit.
IDENTIFIER_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{0,11})-(\d{1,9})(?!\d)")
MAX_REFERENCES = 20


def _dt(value):
    return parse_datetime(value) if value else None


# --- references -----------------------------------------------------------------------------------


def references(*texts):
    """(IDENTIFIER, sequence) pairs mentioned in the texts, in order, without repeats."""
    seen = []
    for text in texts:
        for prefix, number in IDENTIFIER_RE.findall(text or ""):
            key = (prefix.upper(), int(number))
            if key not in seen:
                seen.append(key)
    return seen[:MAX_REFERENCES]


def linked_projects(installation_id, repository_id):
    """{IDENTIFIER: project} for projects the repository is linked to under this installation."""
    links = GitHubRepositoryLink.objects.filter(
        installation__installation_id=installation_id,
        repository_id=repository_id,
        project__archived_at__isnull=True,
    ).select_related("project")
    return {link.project.identifier.upper(): link.project for link in links}


def referenced_issues(projects, *texts):
    issues = []
    for identifier, sequence in references(*texts):
        project = projects.get(identifier)
        if not project:
            continue
        issue = Issue.issue_objects.filter(project=project, sequence_id=sequence).first()
        if issue and issue not in issues:
            issues.append(issue)
    return issues


def _link(issue, kind, repository, ref, **fields):
    """Create or refresh the link of ``issue`` to a PR/branch/commit."""
    lookup = {"issue": issue, "kind": kind, "repository_id": repository["id"], "ref": str(ref)[:255]}
    defaults = {"repository_full_name": repository["full_name"], **fields}
    try:
        with transaction.atomic():
            link, created = GitHubWorkItemLink.objects.get_or_create(
                **lookup, defaults={**defaults, "project": issue.project}
            )
    except IntegrityError:
        link, created = GitHubWorkItemLink.objects.get(**lookup), False
    if not created:
        changed = [name for name, value in defaults.items() if getattr(link, name) != value]
        for name in changed:
            setattr(link, name, defaults[name])
        if changed:
            link.save(update_fields=[*changed, "updated_at"])
    return link


# --- pull requests --------------------------------------------------------------------------------


def upsert_pull_request(workspace_id, repository, data):
    pull_request = GitHubPullRequest.objects.filter(
        workspace_id=workspace_id, repository_id=repository["id"], number=data["number"]
    ).first() or GitHubPullRequest(workspace_id=workspace_id, repository_id=repository["id"], number=data["number"])
    head = data.get("head") or {}
    if pull_request.head_sha and head.get("sha") and pull_request.head_sha != head.get("sha"):
        # New commits: earlier checks no longer apply.
        pull_request.checks = {}
    pull_request.repository_full_name = repository["full_name"]
    pull_request.title = (data.get("title") or "")[:1024]
    pull_request.html_url = data.get("html_url") or ""
    pull_request.state = data.get("state") or "open"
    pull_request.is_draft = bool(data.get("draft"))
    pull_request.merged_at = _dt(data.get("merged_at"))
    pull_request.closed_at = _dt(data.get("closed_at"))
    pull_request.head_ref = (head.get("ref") or "")[:255]
    pull_request.head_sha = head.get("sha") or pull_request.head_sha
    pull_request.base_ref = ((data.get("base") or {}).get("ref") or "")[:255]
    pull_request.author_login = ((data.get("user") or {}).get("login") or "")[:255]
    pull_request.github_updated_at = _dt(data.get("updated_at")) or timezone.now()
    pull_request.save()
    return pull_request


def link_pull_request(pull_request, projects, data):
    for issue in referenced_issues(projects, data.get("title"), data.get("body"), (data.get("head") or {}).get("ref")):
        _link(
            issue,
            GitHubWorkItemLink.PULL_REQUEST,
            {"id": pull_request.repository_id, "full_name": pull_request.repository_full_name},
            pull_request.number,
            pull_request=pull_request,
            title=pull_request.title,
            url=pull_request.html_url,
            author_login=pull_request.author_login,
            github_created_at=_dt(data.get("created_at")),
        )


def pull_request_status(pull_request):
    if pull_request.merged_at:
        return "merged"
    if pull_request.state == "closed":
        return "closed"
    return "draft" if pull_request.is_draft else "open"


def checks_status(checks):
    states = set((checks or {}).values())
    if not states:
        return ""
    if "failure" in states:
        return "failure"
    if "pending" in states:
        return "pending"
    return "success"


# --- webhook handlers -----------------------------------------------------------------------------


def _context(payload):
    """(installation, repository, projects) for a delivery about a linked repository, else None."""
    installation = GitHubInstallation.objects.filter(
        installation_id=(payload.get("installation") or {}).get("id")
    ).first()
    repository = payload.get("repository") or {}
    if not installation or not repository.get("id"):
        return None
    projects = linked_projects(installation.installation_id, repository["id"])
    if not projects:
        return None
    return installation, repository, projects


def handle_pull_request(delivery, payload):
    context = _context(payload)
    if not context or not payload.get("pull_request"):
        return
    installation, repository, projects = context
    pull_request = upsert_pull_request(installation.workspace_id, repository, payload["pull_request"])
    link_pull_request(pull_request, projects, payload["pull_request"])
    from plane.utils.github_automation import apply_pull_request_event

    apply_pull_request_event(delivery.action, payload["pull_request"], repository, projects)


def handle_pull_request_review(delivery, payload):
    context = _context(payload)
    if not context or not payload.get("pull_request"):
        return
    installation, repository, projects = context
    pull_request = upsert_pull_request(installation.workspace_id, repository, payload["pull_request"])
    review = payload.get("review") or {}
    state = (review.get("state") or "").lower()
    if delivery.action == "dismissed":
        pull_request.review_state = ""
    elif state in ("approved", "changes_requested"):
        pull_request.review_state = state
    pull_request.save(update_fields=["review_state", "updated_at"])
    link_pull_request(pull_request, projects, payload["pull_request"])


def _record_check(workspace_id, repository_id, sha, key, state):
    if not sha:
        return
    for pull_request in GitHubPullRequest.objects.filter(
        workspace_id=workspace_id, repository_id=repository_id, head_sha=sha
    ):
        pull_request.checks = {**(pull_request.checks or {}), key: state}
        pull_request.save(update_fields=["checks", "updated_at"])


def _conclusion_state(status, conclusion):
    if status != "completed":
        return "pending"
    return "success" if conclusion in ("success", "neutral", "skipped") else "failure"


def handle_check_suite(delivery, payload):
    context = _context(payload)
    suite = payload.get("check_suite") or {}
    if not context or not suite:
        return
    installation, repository, _ = context
    app_slug = (suite.get("app") or {}).get("slug") or suite.get("id")
    _record_check(
        installation.workspace_id,
        repository["id"],
        suite.get("head_sha"),
        f"suite:{app_slug}",
        _conclusion_state(suite.get("status"), suite.get("conclusion")),
    )


def handle_status(delivery, payload):
    context = _context(payload)
    if not context:
        return
    installation, repository, _ = context
    state = {"success": "success", "pending": "pending"}.get(payload.get("state"), "failure")
    _record_check(
        installation.workspace_id, repository["id"], payload.get("sha"), f"status:{payload.get('context')}", state
    )


def _branch_url(repository, branch):
    return f"{repository.get('html_url', '')}/tree/{branch}" if repository.get("html_url") else ""


def _link_branch(repository, projects, branch, author=""):
    for issue in referenced_issues(projects, branch):
        _link(
            issue,
            GitHubWorkItemLink.BRANCH,
            repository,
            branch,
            title=branch,
            url=_branch_url(repository, branch),
            author_login=author,
            github_created_at=timezone.now(),
        )


def handle_push(delivery, payload):
    context = _context(payload)
    if not context:
        return
    _, repository, projects = context
    ref = payload.get("ref") or ""
    if not ref.startswith("refs/heads/") or payload.get("deleted"):
        return
    branch = ref[len("refs/heads/") :]
    pusher = (payload.get("pusher") or {}).get("name") or ""
    if payload.get("created"):
        _link_branch(repository, projects, branch, pusher)
    commits = payload.get("commits") or []
    if not commits and payload.get("head_commit"):
        # A push that creates a branch can list no commits and carry only head_commit.
        commits = [payload["head_commit"]]
    for commit in commits:
        message = commit.get("message") or ""
        author = commit.get("author") or {}
        for issue in referenced_issues(projects, message):
            _link(
                issue,
                GitHubWorkItemLink.COMMIT,
                repository,
                commit.get("id"),
                title=message.splitlines()[0][:1024] if message else "",
                url=commit.get("url") or "",
                author_login=(author.get("username") or author.get("name") or "")[:255],
                github_created_at=_dt(commit.get("timestamp")),
            )


def handle_create(delivery, payload):
    context = _context(payload)
    if not context or payload.get("ref_type") != "branch":
        return
    _, repository, projects = context
    _link_branch(repository, projects, payload.get("ref") or "", (payload.get("sender") or {}).get("login") or "")


def handle_delete(delivery, payload):
    context = _context(payload)
    if not context or payload.get("ref_type") != "branch":
        return
    _, repository, _ = context
    GitHubWorkItemLink.objects.filter(
        kind=GitHubWorkItemLink.BRANCH, repository_id=repository["id"], ref=payload.get("ref") or ""
    ).delete()


EVENT_HANDLERS = {
    "pull_request": handle_pull_request,
    "pull_request_review": handle_pull_request_review,
    "check_suite": handle_check_suite,
    "status": handle_status,
    "push": handle_push,
    "create": handle_create,
    "delete": handle_delete,
}


# --- backfill -------------------------------------------------------------------------------------


def backfill_repository(link):
    """Link the open pull requests of a newly linked repository."""
    installation = link.installation
    projects = linked_projects(installation.installation_id, link.repository_id)
    if not projects:
        return 0
    repository = {"id": link.repository_id, "full_name": link.full_name, "html_url": link.html_url}
    pulls = github_app.repository_pull_requests(installation.installation_id, link.full_name)
    for data in pulls:
        pull_request = upsert_pull_request(installation.workspace_id, repository, data)
        link_pull_request(pull_request, projects, data)
    return len(pulls)


# --- payloads -------------------------------------------------------------------------------------


def branch_name(issue):
    """A suggested branch name, e.g. plat-12-deploy-script."""
    title = slugify(issue.name or "")
    if len(title) > 40:
        # Cut at a word boundary rather than mid-word.
        cut = title[:41].rfind("-")
        title = title[: cut if cut > 0 else 40]
    title = title.strip("-")
    base = f"{issue.project.identifier.lower()}-{issue.sequence_id}"
    return f"{base}-{title}" if title else base


def work_item_payload(issue):
    links = list(GitHubWorkItemLink.objects.filter(issue=issue).select_related("pull_request"))
    pull_requests, branches, commits = [], [], []
    for link in links:
        if link.kind == GitHubWorkItemLink.PULL_REQUEST and link.pull_request:
            pr = link.pull_request
            pull_requests.append(
                {
                    "id": str(link.id),
                    "repository": pr.repository_full_name,
                    "number": pr.number,
                    "title": pr.title,
                    "url": pr.html_url,
                    "status": pull_request_status(pr),
                    "review_state": pr.review_state,
                    "checks_state": checks_status(pr.checks),
                    "author": pr.author_login,
                    "head_ref": pr.head_ref,
                    "base_ref": pr.base_ref,
                    "updated_at": pr.github_updated_at.isoformat() if pr.github_updated_at else None,
                }
            )
        elif link.kind == GitHubWorkItemLink.BRANCH:
            branches.append(
                {"id": str(link.id), "repository": link.repository_full_name, "name": link.ref, "url": link.url}
            )
        elif link.kind == GitHubWorkItemLink.COMMIT:
            commits.append(
                {
                    "id": str(link.id),
                    "repository": link.repository_full_name,
                    "sha": link.ref,
                    "message": link.title,
                    "url": link.url,
                    "author": link.author_login,
                    "committed_at": link.github_created_at.isoformat() if link.github_created_at else None,
                }
            )
    from plane.utils.github_issue_sync import issue_link_payload

    return {
        "issue": issue_link_payload(issue),
        "enabled": GitHubRepositoryLink.objects.filter(project_id=issue.project_id).exists(),
        "branch_name": branch_name(issue),
        "pull_requests": pull_requests,
        "branches": branches,
        "commits": commits,
    }
