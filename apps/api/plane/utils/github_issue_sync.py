# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Two-way sync between GitHub issues and work items, per linked repository (opt-in).

Synced: title, description (Markdown on GitHub, HTML in Plane), open/closed, labels (by name),
assignees (through GitHubUserMapping) and comments.

Loops are avoided by origin: changes Plane receives from GitHub are written as the GitHub bot
user, and the outgoing hook ignores that user; webhooks GitHub sends for the app's own writes
(sender "<app>[bot]") are ignored. A hash of the synced fields also skips pushes with nothing new.
Conflicts resolve as last write wins; every incoming change is in the work item's activity."""

# Python imports
import hashlib
import json

# Django imports
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

# Module imports
from plane.db.models import (
    GitHubCommentLink,
    GitHubIssueLink,
    GitHubRepositoryLink,
    GitHubUserMapping,
    IssueComment,
    Label,
    ProjectMember,
    State,
)
from plane.utils import github_app
from plane.utils.github_automation import BOT_USERNAME, bot_user
from plane.utils.markdown import html_to_markdown, markdown_to_html

EMPTY_HTML = "<p></p>"


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, cls=DjangoJSONEncoder).encode()).hexdigest()


# --- people ---------------------------------------------------------------------------------------


def logins_for_users(workspace_id, user_ids):
    mappings = GitHubUserMapping.objects.filter(workspace_id=workspace_id, user_id__in=list(user_ids))
    return sorted(mapping.github_login for mapping in mappings)


def users_for_logins(workspace_id, project_id, logins):
    """Mapped users among ``logins`` who are active members of the project."""
    lowered = [login.lower() for login in logins]
    mapped = [
        mapping.user_id
        for mapping in GitHubUserMapping.objects.filter(workspace_id=workspace_id)
        if mapping.github_login.lower() in lowered
    ]
    return list(
        ProjectMember.objects.filter(project_id=project_id, member_id__in=mapped, is_active=True).values_list(
            "member_id", flat=True
        )
    )


def mappings_payload(workspace_id):
    return [
        {"user": str(mapping.user_id), "github_login": mapping.github_login}
        for mapping in GitHubUserMapping.objects.filter(workspace_id=workspace_id).order_by("github_login")
    ]


@transaction.atomic
def set_mapping(workspace, user_id, github_login):
    """Map a workspace member to a GitHub login; an empty login removes the mapping."""
    login = (github_login or "").strip().lstrip("@")
    GitHubUserMapping.objects.filter(workspace=workspace, user_id=user_id).delete()
    if login:
        GitHubUserMapping.objects.filter(workspace=workspace, github_login__iexact=login).delete()
        GitHubUserMapping.objects.create(workspace=workspace, user_id=user_id, github_login=login[:255])


# --- snapshots ------------------------------------------------------------------------------------


def plane_snapshot(issue):
    """The synced fields of a work item, in GitHub's terms."""
    group = issue.state.group if issue.state_id else ""
    return {
        "title": issue.name,
        "body": html_to_markdown(issue.description_html or ""),
        "state": "closed" if group in ("completed", "cancelled") else "open",
        "state_reason": "not_planned" if group == "cancelled" else ("completed" if group == "completed" else None),
        "labels": sorted(issue.labels.values_list("name", flat=True)),
        "assignees": logins_for_users(issue.workspace_id, issue.assignees.values_list("id", flat=True)),
    }


def is_app_sender(payload):
    return ((payload.get("sender") or {}).get("login") or "").lower() == github_app.app_bot_login().lower()


# --- GitHub -> Plane ------------------------------------------------------------------------------


def _target_state(project, current, data):
    states = list(State.objects.filter(project=project).order_by("sequence"))
    current_group = current.group if current else None
    if data.get("state") == "closed":
        group = "cancelled" if data.get("state_reason") == "not_planned" else "completed"
        if current_group == group:
            return current
        return next((s for s in states if s.group == group), current)
    if current_group in ("completed", "cancelled") or current is None:
        return next((s for s in states if s.default), None) or next(
            (s for s in states if s.group in ("backlog", "unstarted")), current
        )
    return current


def _label_ids(project, names):
    ids = []
    for name in names:
        label = Label.objects.filter(project=project, name__iexact=name).first()
        if not label:
            label = Label.objects.create(project=project, workspace_id=project.workspace_id, name=name[:255])
        ids.append(label.id)
    return ids


def _record_activity(kind, issue, actor, requested, current=None):
    from plane.bgtasks.issue_activities_task import issue_activity
    from django.conf import settings

    issue_activity.delay(
        type=kind,
        requested_data=json.dumps(requested, cls=DjangoJSONEncoder),
        actor_id=str(actor.id),
        issue_id=str(issue.id),
        project_id=str(issue.project_id),
        current_instance=json.dumps(current, cls=DjangoJSONEncoder) if current is not None else None,
        epoch=int(timezone.now().timestamp()),
        subscriber=False,
        notification=True,
        origin=settings.WEB_URL,
    )


def apply_github_issue(repository_link, data):
    """Create or update the work item for a GitHub issue; returns its link."""
    from plane.api.serializers import IssueSerializer

    project = repository_link.project
    link = (
        GitHubIssueLink.objects.filter(repository_link=repository_link, number=data["number"])
        .select_related("issue__state")
        .first()
    )
    issue = link.issue if link else None
    fields = {
        "name": (data.get("title") or f"GitHub issue #{data['number']}")[:255],
        "description_html": markdown_to_html(data.get("body") or "") or EMPTY_HTML,
        "labels": _label_ids(project, [label["name"] for label in data.get("labels") or []]),
        "assignees": users_for_logins(
            project.workspace_id, project.id, [user["login"] for user in data.get("assignees") or []]
        ),
    }
    state = _target_state(project, issue.state if issue else None, data)
    if state:
        fields["state"] = state.id
    actor = bot_user()
    context = {
        "project_id": project.id,
        "workspace_id": project.workspace_id,
        "default_assignee_id": project.default_assignee_id,
    }

    if issue is None:
        serializer = IssueSerializer(data=fields, context=context)
        serializer.is_valid(raise_exception=True)
        issue = serializer.save()
        link = GitHubIssueLink.objects.create(
            project=project,
            issue=issue,
            repository_link=repository_link,
            github_issue_id=data["id"],
            number=data["number"],
            html_url=data.get("html_url") or "",
        )
        _record_activity("issue.activity.created", issue, actor, {**fields, "id": str(issue.id)})
    else:
        current = IssueSerializer(issue).data
        changed = {}
        for key, value in fields.items():
            before = current.get(key)
            if key in ("labels", "assignees"):
                if sorted(map(str, before or [])) != sorted(map(str, value)):
                    changed[key] = value
            elif str(before) != str(value):
                changed[key] = value
        if changed:
            serializer = IssueSerializer(issue, data=changed, context=context, partial=True)
            serializer.is_valid(raise_exception=True)
            issue = serializer.save()
            _record_activity("issue.activity.updated", issue, actor, changed, current)

    issue.refresh_from_db()
    link.synced_hash = _hash(plane_snapshot(issue))
    link.save(update_fields=["synced_hash", "updated_at"])
    return link


def _comment_html(data):
    login = (data.get("user") or {}).get("login") or "someone"
    return f"<p><strong>{login}</strong> on GitHub:</p>" + (markdown_to_html(data.get("body") or "") or EMPTY_HTML)


def apply_github_comment(link, action, data):
    comment_link = GitHubCommentLink.objects.filter(issue_link=link, github_comment_id=data["id"]).first()
    if action == "deleted":
        if comment_link:
            comment_link.comment.delete()
            comment_link.delete()
        return
    html = _comment_html(data)
    if comment_link:
        comment = comment_link.comment
        if comment.comment_html != html:
            comment.comment_html = html
            comment.edited_at = timezone.now()
            comment.save(update_fields=["comment_html", "edited_at", "updated_at"])
        comment_link.synced_hash = _hash(html)
        comment_link.save(update_fields=["synced_hash", "updated_at"])
        return
    actor = bot_user()
    comment = IssueComment.objects.create(
        issue=link.issue,
        project_id=link.project_id,
        workspace_id=link.workspace_id,
        actor=actor,
        comment_html=html,
    )
    GitHubCommentLink.objects.create(
        project_id=link.project_id,
        issue_link=link,
        comment=comment,
        github_comment_id=data["id"],
        synced_hash=_hash(html),
    )
    _record_activity("comment.activity.created", link.issue, actor, {"comment_html": html, "id": str(comment.id)})


def _repository_link(payload):
    installation_id = (payload.get("installation") or {}).get("id")
    repository_id = (payload.get("repository") or {}).get("id")
    return (
        GitHubRepositoryLink.objects.filter(
            installation__installation_id=installation_id, repository_id=repository_id, issue_sync=True
        )
        .select_related("project", "installation")
        .first()
    )


def handle_issues(delivery, payload):
    data = payload.get("issue") or {}
    if not data or "pull_request" in data or is_app_sender(payload):
        return
    repository_link = _repository_link(payload)
    if not repository_link:
        return
    if delivery.action in ("deleted", "transferred"):
        GitHubIssueLink.objects.filter(repository_link=repository_link, number=data["number"]).delete()
        return
    exists = GitHubIssueLink.objects.filter(repository_link=repository_link, number=data["number"]).exists()
    # Closed issues that were never synced stay out of Plane.
    if not exists and data.get("state") != "open":
        return
    apply_github_issue(repository_link, data)


def handle_issue_comment(delivery, payload):
    issue_data = payload.get("issue") or {}
    comment = payload.get("comment") or {}
    if not comment or "pull_request" in issue_data or is_app_sender(payload):
        return
    repository_link = _repository_link(payload)
    if not repository_link:
        return
    link = GitHubIssueLink.objects.filter(repository_link=repository_link, number=issue_data.get("number")).first()
    if link:
        apply_github_comment(link, delivery.action, comment)


EVENT_HANDLERS = {"issues": handle_issues, "issue_comment": handle_issue_comment}


def import_open_issues(repository_link):
    """Create work items for the repository's open issues, with their comments. Returns the count."""
    installation_id = repository_link.installation.installation_id
    issues = github_app.repository_open_issues(installation_id, repository_link.full_name)
    for data in issues:
        link = apply_github_issue(repository_link, data)
        if data.get("comments"):
            for comment in github_app.issue_comments(installation_id, repository_link.full_name, data["number"]):
                if (comment.get("user") or {}).get("login", "").lower() != github_app.app_bot_login().lower():
                    apply_github_comment(link, "created", comment)
    repository_link.issue_sync_imported_at = timezone.now()
    repository_link.save(update_fields=["issue_sync_imported_at", "updated_at"])
    return len(issues)


# --- Plane -> GitHub ------------------------------------------------------------------------------


def wants_push(activity_type, issue_id, project_id, actor_id):
    """Whether a Plane change should be pushed to GitHub (called from the activity task)."""
    if not activity_type.startswith(("issue.activity.created", "issue.activity.updated", "comment.activity")):
        return False
    from plane.db.models import User

    if User.objects.filter(pk=actor_id, username=BOT_USERNAME).exists():
        return False
    if GitHubIssueLink.objects.filter(issue_id=issue_id).exists():
        return True
    return activity_type == "issue.activity.created" and _sync_target(project_id) is not None


def _sync_target(project_id):
    """The one repository new work items of the project are created in, if exactly one syncs."""
    links = list(
        GitHubRepositoryLink.objects.filter(project_id=project_id, issue_sync=True).select_related("installation")[:2]
    )
    return links[0] if len(links) == 1 else None


def _github_fields(snapshot):
    fields = {
        "title": snapshot["title"],
        "body": snapshot["body"],
        "state": snapshot["state"],
        "labels": snapshot["labels"],
        "assignees": snapshot["assignees"],
    }
    if snapshot["state"] == "closed":
        fields["state_reason"] = snapshot["state_reason"]
    return fields


def push_issue(issue):
    """Send the work item's fields and comments to its GitHub issue, creating it if needed."""
    link = GitHubIssueLink.objects.filter(issue=issue).select_related("repository_link__installation").first()
    snapshot = plane_snapshot(issue)
    new_hash = _hash(snapshot)
    if link is None:
        target = _sync_target(issue.project_id)
        if not target:
            return None
        fields = {key: snapshot[key] for key in ("title", "body", "labels", "assignees")}
        data = github_app.create_issue(target.installation.installation_id, target.full_name, fields)
        link = GitHubIssueLink.objects.create(
            project_id=issue.project_id,
            issue=issue,
            repository_link=target,
            github_issue_id=data["id"],
            number=data["number"],
            html_url=data.get("html_url") or "",
        )
        if snapshot["state"] == "closed":
            github_app.update_issue(
                target.installation.installation_id,
                target.full_name,
                data["number"],
                {"state": "closed", "state_reason": snapshot["state_reason"]},
            )
        link.synced_hash = new_hash
        link.save(update_fields=["synced_hash", "updated_at"])
    elif link.synced_hash != new_hash:
        repository_link = link.repository_link
        github_app.update_issue(
            repository_link.installation.installation_id,
            repository_link.full_name,
            link.number,
            _github_fields(snapshot),
        )
        link.synced_hash = new_hash
        link.save(update_fields=["synced_hash", "updated_at"])
    push_comments(link)
    return link


def _outgoing_comment_body(comment):
    author = comment.actor.display_name if comment.actor_id else "Someone"
    return f"**{author}** commented in Plane:\n\n{html_to_markdown(comment.comment_html or '')}"


def push_comments(link):
    repository_link = link.repository_link
    installation_id = repository_link.installation.installation_id
    linked = {cl.comment_id: cl for cl in GitHubCommentLink.objects.filter(issue_link=link).select_related("comment")}

    # Comments deleted in Plane.
    for comment_link in list(linked.values()):
        if comment_link.comment.deleted_at is not None:
            try:
                github_app.delete_issue_comment(
                    installation_id, repository_link.full_name, comment_link.github_comment_id
                )
            except github_app.GitHubAppError as exc:
                if exc.github_status != 404:
                    raise
            comment_link.delete()

    comments = IssueComment.objects.filter(issue_id=link.issue_id).select_related("actor").order_by("created_at")
    for comment in comments:
        if comment.actor and comment.actor.username == BOT_USERNAME:
            continue  # came from GitHub
        html_hash = _hash(comment.comment_html)
        comment_link = linked.get(comment.id)
        body = _outgoing_comment_body(comment)
        if comment_link is None:
            data = github_app.create_issue_comment(installation_id, repository_link.full_name, link.number, body)
            GitHubCommentLink.objects.create(
                project_id=link.project_id,
                issue_link=link,
                comment=comment,
                github_comment_id=data["id"],
                synced_hash=html_hash,
            )
        elif comment_link.deleted_at is None and comment_link.synced_hash != html_hash:
            github_app.update_issue_comment(
                installation_id, repository_link.full_name, comment_link.github_comment_id, body
            )
            comment_link.synced_hash = html_hash
            comment_link.save(update_fields=["synced_hash", "updated_at"])


# --- payloads -------------------------------------------------------------------------------------


def issue_link_payload(issue):
    link = GitHubIssueLink.objects.filter(issue=issue).select_related("repository_link").first()
    if not link:
        return None
    return {"repository": link.repository_link.full_name, "number": link.number, "url": link.html_url}
