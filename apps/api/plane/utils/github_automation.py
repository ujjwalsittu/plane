# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Pull request events move work items between states, per project rules.

Only work items the pull request is *about* move: those named in its title or head branch, or
after a closing keyword ("Fixes PLAT-12") in its body. Items merely mentioned elsewhere in the body
are linked but not moved. Items only move forward (backlog -> unstarted -> started -> completed)
and never leave a completed or cancelled state. Each move is recorded in the work item's activity
as the "GitHub" bot user."""

# Python imports
import json
import re
import uuid

# Django imports
from django.conf import settings
from django.utils import timezone

# Module imports
from plane.db.models import GitHubProjectAutomation, Issue, State, User

CLOSING_KEYWORD_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[:\s]+([A-Za-z][A-Za-z0-9]{0,11}-\d{1,9})", re.IGNORECASE
)
GROUP_RANK = {"backlog": 0, "unstarted": 1, "started": 2, "completed": 3, "cancelled": 3}
BOT_USERNAME = "plane-github-bot"
RULE_FIELDS = ("draft_state", "open_state", "review_requested_state", "merge_state")


class GitHubAutomationError(ValueError):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# --- rules ----------------------------------------------------------------------------------------


def default_rules(project):
    states = list(State.objects.filter(project=project).order_by("sequence"))
    started = [s for s in states if s.group == "started"]
    completed = [s for s in states if s.group == "completed"]
    review = next((s for s in started if "review" in s.name.lower()), None)
    return {
        "draft_state": started[0] if started else None,
        "open_state": started[0] if started else None,
        "review_requested_state": review,
        "merge_state": completed[0] if completed else None,
    }


def rules_for(project):
    """The project's saved rules, or defaults derived from its states (not saved)."""
    saved = GitHubProjectAutomation.objects.filter(project=project).select_related(*RULE_FIELDS).first()
    if saved:
        return saved
    rules = GitHubProjectAutomation(project=project, workspace_id=project.workspace_id)
    for field, state in default_rules(project).items():
        setattr(rules, field, state)
    return rules


def rules_payload(rules):
    return {
        "project": str(rules.project_id),
        "enabled": rules.enabled,
        "close_keywords": rules.close_keywords,
        "is_default": rules.pk is None or rules._state.adding,
        **{
            field: (str(getattr(rules, f"{field}_id")) if getattr(rules, f"{field}_id") else None)
            for field in RULE_FIELDS
        },
    }


def update_rules(project, data):
    rules = GitHubProjectAutomation.objects.filter(project=project).first() or rules_for(project)
    for flag in ("enabled", "close_keywords"):
        if flag in data:
            if not isinstance(data[flag], bool):
                raise GitHubAutomationError(f"{flag} must be true or false")
            setattr(rules, flag, data[flag])
    for field in RULE_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if value in (None, ""):
            setattr(rules, field, None)
            continue
        state = State.objects.filter(project=project, pk=value).first() if _is_uuid(value) else None
        if not state:
            raise GitHubAutomationError(f"{field} is not a state of this project")
        setattr(rules, field, state)
    rules.save()
    return rules


def _is_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


# --- which items a PR is about --------------------------------------------------------------------


def primary_references(data, close_keywords=True):
    """Identifiers the PR is about: in its title or head branch, or after a closing keyword."""
    from plane.utils.github_sync import references

    texts = [data.get("title"), (data.get("head") or {}).get("ref")]
    if close_keywords:
        texts.append(" ".join(CLOSING_KEYWORD_RE.findall(data.get("body") or "")))
    return references(*texts)


# --- moving items ---------------------------------------------------------------------------------


def bot_user():
    user = User.objects.filter(username=BOT_USERNAME).first()
    if user:
        return user
    user = User(
        username=BOT_USERNAME,
        email="github-bot@plane.invalid",
        display_name="GitHub",
        first_name="GitHub",
        is_bot=True,
        bot_type="GITHUB",
    )
    user.set_unusable_password()
    user.save()
    return user


def _rule_field(event_action, data, default_branch):
    if event_action == "review_requested":
        return "review_requested_state"
    if event_action == "closed":
        merged = bool(data.get("merged") or data.get("merged_at"))
        base = (data.get("base") or {}).get("ref")
        return "merge_state" if merged and (not default_branch or base == default_branch) else None
    if event_action in ("opened", "reopened", "ready_for_review", "converted_to_draft", "edited", "synchronize"):
        return "draft_state" if data.get("draft") else "open_state"
    return None


def _position(state):
    """Workflow position: the state group first, then the state's order within the group."""
    return (GROUP_RANK.get(state.group, 0), state.sequence)


def move_issue(issue, state, actor):
    """Move ``issue`` to ``state`` if that is a step forward; returns True when it moved."""
    current = issue.state
    if not state or (current and current.id == state.id):
        return False
    if current and (current.group in ("completed", "cancelled") or _position(state) < _position(current)):
        return False
    old_state_id = str(current.id) if current else None
    issue.state = state
    issue.save()
    from plane.bgtasks.issue_activities_task import issue_activity

    issue_activity.delay(
        type="issue.activity.updated",
        requested_data=json.dumps({"state_id": str(state.id)}),
        actor_id=str(actor.id),
        issue_id=str(issue.id),
        project_id=str(issue.project_id),
        current_instance=json.dumps({"state_id": old_state_id}),
        epoch=int(timezone.now().timestamp()),
        # The bot shouldn't subscribe itself to the work item.
        subscriber=False,
        notification=True,
        origin=settings.WEB_URL,
    )
    return True


def apply_pull_request_event(action, data, repository, projects):
    """Move the work items a PR is about, per their projects' rules. Returns the moved issues."""
    field = _rule_field(action, data, repository.get("default_branch"))
    # Opening edits and new commits re-apply the open/draft rule only when the PR is new to us;
    # otherwise a hand-moved item would be pulled back on every push.
    if not field or action in ("edited", "synchronize"):
        return []
    moved = []
    actor = None
    for project in projects.values():
        rules = rules_for(project)
        state = getattr(rules, field) if rules.enabled else None
        if not state:
            continue
        for identifier, sequence in primary_references(data, rules.close_keywords):
            if identifier != project.identifier.upper():
                continue
            issue = Issue.issue_objects.filter(project=project, sequence_id=sequence).select_related("state").first()
            if not issue:
                continue
            actor = actor or bot_user()
            if move_issue(issue, state, actor):
                moved.append(issue)
    return moved
