# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Triage suggestions: on request, Claude suggests an assignee, labels, a better project and likely duplicates
for a new work item (intake items included).

The model only chooses among candidates the asking person could see or act on in the app, and every id it
returns is checked against them; anything else is dropped."""

import json
from datetime import timedelta

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone

from plane.app.permissions import ROLE
from plane.utils.ai_calls import ai_message
from plane.utils.brief import _visible_issues
from plane.utils.supervision import OPEN_GROUPS

DUPLICATE_DAYS = 180
DUPLICATE_LIMIT = 15
MIN_RANK = 0.05
MEMBER_LABEL_DAYS = 90
MEMBER_TOP_LABELS = 5
PROJECT_DESCRIPTION_CHARS = 300
ISSUE_DESCRIPTION_CHARS = 3000
DUPLICATE_DESCRIPTION_CHARS = 300
REASON_CHARS = 300
MAX_LABELS = 3
MAX_DUPLICATES = 3
MAX_TOKENS = 1024
CACHE_SECONDS = 24 * 60 * 60

SYSTEM_PROMPT = """You triage a new work item in Plane. You get the item and candidates as JSON.
Suggest, using only ids from the candidates:
- assignee: the one member best placed to own it (open_items shows their current load), or null.
- labels: up to 3 labels that clearly apply.
- project: another project only when it clearly fits better than the current one, otherwise null.
- duplicates: up to 3 candidates that describe the same problem or request, not merely a similar topic.
Give each suggestion a short reason (one sentence). Suggest nothing rather than guess.
Record the result with the record_suggestions tool."""

_PICK = {
    "type": "object",
    "properties": {"id": {"type": "string"}, "reason": {"type": "string"}},
    "required": ["id", "reason"],
}

TOOL = {
    "name": "record_suggestions",
    "description": "Record the triage suggestions for the work item.",
    "input_schema": {
        "type": "object",
        "properties": {
            "assignee": {"anyOf": [_PICK, {"type": "null"}], "description": "A member id, or null."},
            "labels": {"type": "array", "items": _PICK, "maxItems": MAX_LABELS},
            "project": {"anyOf": [_PICK, {"type": "null"}], "description": "Another project id, or null."},
            "duplicates": {"type": "array", "items": _PICK, "maxItems": MAX_DUPLICATES},
        },
        "required": ["assignee", "labels", "project", "duplicates"],
    },
}


def cache_key(issue):
    return f"triage:{issue.id}:{int(issue.updated_at.timestamp())}"


def _identifier(issue):
    return f"{issue.project.identifier}-{issue.sequence_id}"


def _clip(text, limit):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# --- what the person can see ------------------------------------------------------------------------


def _memberships(user, workspace_id):
    """The person's live memberships of live projects (the default managers skip soft-deleted rows)."""
    from plane.db.models import ProjectMember

    return ProjectMember.objects.filter(
        workspace_id=workspace_id,
        member=user,
        is_active=True,
        project__archived_at__isnull=True,
        project__deleted_at__isnull=True,
    )


def _visible(user, workspace_id):
    """Work items `user` can open, as the app decides it: ``visible_issue_q``, narrowed to live memberships so a
    soft-deleted membership row never grants access. Restricted guests see only what they created."""
    full, restricted = [], []
    for project_id, role, guest_view_all in _memberships(user, workspace_id).values_list(
        "project_id", "role", "project__guest_view_all_features"
    ):
        (full if role > ROLE.GUEST.value or guest_view_all else restricted).append(project_id)
    return _visible_issues(user, workspace_id).filter(
        Q(project_id__in=full) | Q(project_id__in=restricted, created_by=user)
    )


def duplicate_candidates(issue, user, limit=DUPLICATE_LIMIT):
    """Work items that may duplicate `issue`, best match first: visible to `user`, created in the last 180 days,
    not `issue` itself and not already related to it."""
    from plane.db.models import IssueRelation

    if not (issue.name or "").strip():
        return []
    related = IssueRelation.objects.filter(Q(issue=issue) | Q(related_issue=issue)).values_list(
        "issue_id", "related_issue_id"
    )
    excluded = {issue.id} | {pk for pair in related for pk in pair}
    vector = SearchVector("name", weight="A") + SearchVector("description_stripped", weight="B")
    query = SearchQuery(issue.name, search_type="websearch")
    return list(
        _visible(user, issue.workspace_id)
        .filter(created_at__gte=timezone.now() - timedelta(days=DUPLICATE_DAYS))
        .exclude(id__in=excluded)
        .annotate(rank=SearchRank(vector, query))
        .filter(rank__gt=MIN_RANK)
        .select_related("project", "state")
        .order_by("-rank", "-created_at")[:limit]
    )


# --- candidates -------------------------------------------------------------------------------------


def _people(project):
    """Active people who can be assigned in the project (role member or admin, as the work item serializer
    requires); agents never."""
    from plane.db.models import ProjectMember

    return (
        ProjectMember.objects.filter(
            project=project,
            is_active=True,
            role__gte=ROLE.MEMBER.value,
            member__is_bot=False,
            member__is_active=True,
        )
        .select_related("member")
        .order_by("member__display_name")
    )


def _labels(project):
    from plane.db.models import Label

    return Label.objects.filter(project=project).order_by("name")


def _member_rows(project, label_names):
    from plane.db.models import IssueAssignee, IssueLabel

    people = [row.member for row in _people(project)]
    ids = [person.id for person in people]
    open_counts = dict(
        IssueAssignee.objects.filter(
            assignee_id__in=ids,
            project=project,
            issue__deleted_at__isnull=True,
            issue__archived_at__isnull=True,
            issue__is_draft=False,
            issue__state__group__in=OPEN_GROUPS,
        )
        .values("assignee_id")
        .annotate(count=Count("issue_id", distinct=True))
        .values_list("assignee_id", "count")
    )
    since = timezone.now() - timedelta(days=MEMBER_LABEL_DAYS)
    usage = {}
    for assignee_id, label_id, count in (
        IssueLabel.objects.filter(
            project=project,
            label_id__in=label_names.keys(),
            issue__deleted_at__isnull=True,
            issue__created_at__gte=since,
            issue__issue_assignee__assignee_id__in=ids,
            issue__issue_assignee__deleted_at__isnull=True,
        )
        .values("issue__issue_assignee__assignee_id", "label_id")
        .annotate(count=Count("issue_id", distinct=True))
        .values_list("issue__issue_assignee__assignee_id", "label_id", "count")
    ):
        usage.setdefault(assignee_id, []).append((count, label_names[label_id]))
    return [
        {
            "id": str(person.id),
            "name": person.display_name,
            "open_items": open_counts.get(person.id, 0),
            "top_labels": [name for _, name in sorted(usage.get(person.id, []), key=lambda u: -u[0])][
                :MEMBER_TOP_LABELS
            ],
        }
        for person in people
    ]


def _projects(user, workspace_id):
    from plane.db.models import Project

    return Project.objects.filter(
        id__in=_memberships(user, workspace_id).values("project_id"), workspace_id=workspace_id
    ).order_by("name")


def _candidates(issue, user):
    """Everything the model may pick from, keyed by id, plus the payload sent to it."""
    labels = {str(label.id): label for label in _labels(issue.project)}
    members = _member_rows(issue.project, {label.id: label.name for label in labels.values()})
    projects = {str(project.id): project for project in _projects(user, issue.workspace_id)}
    duplicates = {str(item.id): item for item in duplicate_candidates(issue, user)}
    assigned, labelled = _current(issue)
    payload = {
        "work_item": {
            "identifier": _identifier(issue),
            "title": issue.name,
            "description": _clip(issue.description_stripped, ISSUE_DESCRIPTION_CHARS),
            "project": {"id": str(issue.project_id), "name": issue.project.name},
            "assignees": list(assigned.values()),
            "labels": list(labelled.values()),
        },
        "members": members,
        "labels": [{"id": pk, "name": label.name} for pk, label in labels.items()],
        "projects": [
            {
                "id": pk,
                "name": project.name,
                "identifier": project.identifier,
                "description": _clip(project.description, PROJECT_DESCRIPTION_CHARS),
                "current": project.id == issue.project_id,
            }
            for pk, project in projects.items()
        ],
        "duplicate_candidates": [
            {
                "id": pk,
                "identifier": _identifier(item),
                "title": item.name,
                "state": item.state.name if item.state else None,
                "description": _clip(item.description_stripped, DUPLICATE_DESCRIPTION_CHARS),
            }
            for pk, item in duplicates.items()
        ],
    }
    allowed = {
        "members": {row["id"]: row["name"] for row in members},
        "labels": {pk: label.name for pk, label in labels.items()},
        "projects": {pk: project.name for pk, project in projects.items()},
        "duplicates": {pk: (_identifier(item), item.name) for pk, item in duplicates.items()},
    }
    return payload, allowed


def _current(issue):
    """({assignee id: display name}, {label id: name}) already on the item, ignoring soft-deleted links."""
    assigned = {
        str(row.assignee_id): row.assignee.display_name
        for row in issue.issue_assignee.filter(deleted_at__isnull=True).select_related("assignee")
    }
    labelled = {
        str(row.label_id): row.label.name
        for row in issue.label_issue.filter(deleted_at__isnull=True, label__deleted_at__isnull=True).select_related(
            "label"
        )
    }
    return assigned, labelled


# --- checking what the model returned ---------------------------------------------------------------


def _pick(value):
    """(id, reason) from one model pick, or None when it isn't a well-formed pick."""
    if not isinstance(value, dict):
        return None
    pk, reason = value.get("id"), value.get("reason")
    if not isinstance(pk, str) or not pk:
        return None
    return pk, _clip(reason if isinstance(reason, str) else "", REASON_CHARS)


def _picks(value):
    seen, picks = set(), []
    for item in value if isinstance(value, list) else []:
        pick = _pick(item)
        if pick is not None and pick[0] not in seen:
            seen.add(pick[0])
            picks.append(pick)
    return picks


def _checked(raw, allowed, issue):
    """The model's answer with every id it wasn't offered dropped, and the limits applied."""
    raw = raw if isinstance(raw, dict) else {}
    assigned, labelled = _current(issue)

    assignee = None
    pick = _pick(raw.get("assignee"))
    if pick and pick[0] in allowed["members"] and pick[0] not in assigned:
        assignee = {"id": pick[0], "display_name": allowed["members"][pick[0]], "reason": pick[1]}

    labels = [
        {"id": pk, "name": allowed["labels"][pk], "reason": reason}
        for pk, reason in _picks(raw.get("labels"))
        if pk in allowed["labels"] and pk not in labelled
    ][:MAX_LABELS]

    project = None
    pick = _pick(raw.get("project"))
    if pick and pick[0] in allowed["projects"] and pick[0] != str(issue.project_id):
        project = {"id": pick[0], "name": allowed["projects"][pick[0]], "reason": pick[1]}

    duplicates = [
        {"id": pk, "identifier": allowed["duplicates"][pk][0], "name": allowed["duplicates"][pk][1], "reason": reason}
        for pk, reason in _picks(raw.get("duplicates"))
        if pk in allowed["duplicates"]
    ][:MAX_DUPLICATES]

    return {"assignee": assignee, "labels": labels, "project": project, "duplicates": duplicates}


def _for_viewer(result, issue, user):
    """A cached answer, re-checked for the person viewing it now: the cache is per item, not per person."""
    project_ids = {str(pk) for pk in _projects(user, issue.workspace_id).values_list("id", flat=True)}
    member_ids = {str(row.member_id) for row in _people(issue.project)}
    label_ids = {str(pk) for pk in _labels(issue.project).values_list("id", flat=True)}
    duplicate_ids = [row["id"] for row in result["duplicates"]]
    visible_ids = {
        str(pk) for pk in _visible(user, issue.workspace_id).filter(id__in=duplicate_ids).values_list("id", flat=True)
    }
    assignee, project = result["assignee"], result["project"]
    return {
        **result,
        "assignee": assignee if assignee and assignee["id"] in member_ids else None,
        "labels": [row for row in result["labels"] if row["id"] in label_ids],
        "project": project if project and project["id"] in project_ids else None,
        "duplicates": [row for row in result["duplicates"] if row["id"] in visible_ids],
    }


def _tool_input(response):
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL["name"]:
            return block.input
    return {}


def suggest(issue, user, refresh=False):
    """Suggestions for `issue` as `user` may see them. Cached for 24 hours until the item changes; `refresh`
    asks Claude again. Raises AgentError when AI isn't set up, the monthly limit is reached, or the call fails."""
    key = cache_key(issue)
    if not refresh:
        cached = cache.get(key)
        if cached is not None:
            return _for_viewer(cached, issue, user)
    payload, allowed = _candidates(issue, user)
    response = ai_message(
        issue.workspace,
        user,
        "triage",
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload)}],
        tools=[TOOL],
        tool_choice={"type": "tool", "name": TOOL["name"]},
    )
    result = _checked(_tool_input(response), allowed, issue)
    result["generated_at"] = timezone.now().isoformat()
    cache.set(key, result, CACHE_SECONDS)
    return result
