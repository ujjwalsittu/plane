# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Ask the workspace: Claude answers a person's question with tools that read Plane data as that person.

Every tool reads through the same visibility rules the app uses (``visible_issue_q``, active project
membership, page access), so an answer can only draw on what the asking person could open themselves."""

import json
import re
from datetime import timedelta
from html import unescape

from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.html import strip_tags

from plane.utils.agents import AgentError
from plane.utils.ai_calls import ai_message
from plane.utils.brief import _local_date, _visible_issues
from plane.utils.supervision import OPEN_GROUPS, blocked_items as _blocked_items

MAX_TOOL_ROUNDS = 8
MAX_ROWS = 20
MAX_RESULT_CHARS = 8000
MAX_QUESTION_LENGTH = 2000
MAX_HISTORY_TURNS = 10
MAX_HISTORY_CONTENT = 4000
MAX_TOKENS = 1024
DESCRIPTION_CHARS = 3000
COMMENT_CHARS = 500
PAGE_EXCERPT_CHARS = 500
LAST_COMMENTS = 5
RATE_LIMIT = 20
RATE_WINDOW_SECONDS = 600
# A title shorter than this is too common a word to count as a mention.
MIN_TITLE_MENTION = 4

IDENTIFIER_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9]*)-(\d+)\s*$")

SYSTEM_PROMPT = """You answer questions about a Plane workspace for the person asking. Today is {today}.
Use the tools to look things up; they only return what this person can see.
Rules:
- Answer only from tool results. Never guess or use outside knowledge about the work.
- Cite every work item as its identifier in square brackets, for example [OSMG-12].
- When the tools find nothing relevant, say plainly that nothing was found.
- Keep the answer under 200 words, in plain text."""

_PROJECT = {"type": "string", "description": 'A project identifier ("OSMG") or name. Optional.'}
_IDENTIFIER = {"type": "string", "description": 'A work item identifier such as "OSMG-12".'}

TOOLS = [
    {
        "name": "search_work_items",
        "description": "Find work items by words in their title or description (or by identifier). Returns "
        "identifier, title, state, assignees, target date and project for up to 20 matches, most recently updated "
        "first. An empty query lists work items.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words to look for; may be empty."},
                "project": _PROJECT,
                "open_only": {"type": "boolean", "description": "Only work items that are not done or cancelled."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_work_item",
        "description": "One work item in detail: description, last 5 comments, what blocks it, who it waits on, "
        "open decisions and linked pull requests with their state.",
        "input_schema": {"type": "object", "properties": {"identifier": _IDENTIFIER}, "required": ["identifier"]},
    },
    {
        "name": "list_milestones",
        "description": "Milestones with their target date and how many of their work items are open.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project": _PROJECT,
                "due_within_days": {
                    "type": "integer",
                    "description": "Only milestones due within this many days from today (overdue ones included).",
                },
            },
        },
    },
    {
        "name": "blocked_items",
        "description": "Open work items that are blocked by another item, waiting on someone, or stale, with why.",
        "input_schema": {"type": "object", "properties": {"project": _PROJECT}},
    },
    {
        "name": "search_pages",
        "description": "Find pages (docs and wiki) by words in their title or text. Returns title, project and "
        "the first 500 characters.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "github_activity",
        "description": "Pull requests, branches and commits linked to a work item, with pull request state.",
        "input_schema": {"type": "object", "properties": {"identifier": _IDENTIFIER}, "required": ["identifier"]},
    },
]


class AskContext:
    """The asking person and the entities the tools showed them (the answer's possible sources)."""

    def __init__(self, workspace, user):
        self.workspace = workspace
        self.user = user
        self.slug = workspace.slug
        # {(kind, id): source}, in the order tools first returned them
        self.sources = {}

    def add_source(self, kind, pk, identifier, title, url):
        self.sources.setdefault(
            (kind, str(pk)),
            {"kind": kind, "id": str(pk), "identifier": identifier, "title": title, "url": url},
        )

    def add_issue(self, issue):
        identifier = _issue_identifier(issue)
        self.add_source("work_item", issue.id, identifier, issue.name, f"/{self.slug}/browse/{identifier}/")


# --- helpers ---------------------------------------------------------------------------------------


def _issue_identifier(issue):
    return f"{issue.project.identifier}-{issue.sequence_id}"


def _iso(value):
    return value.isoformat() if value else None


def _plain(html, limit):
    text = " ".join(unescape(strip_tags(html or "")).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _name(user):
    if user is None:
        return None
    return user.display_name or user.email.split("@")[0]


def _member_projects(context):
    from plane.db.models import Project, ProjectMember

    member_of = ProjectMember.objects.filter(
        workspace_id=context.workspace.id, member=context.user, is_active=True
    ).values("project_id")
    return Project.objects.filter(workspace_id=context.workspace.id, id__in=member_of, archived_at__isnull=True)


def _project(context, value):
    """The project ``value`` names (identifier or name) among the person's projects, or None."""
    value = (value or "").strip()
    projects = _member_projects(context)
    exact = projects.filter(Q(identifier__iexact=value) | Q(name__iexact=value)).first()
    if exact is not None:
        return exact
    partial = list(projects.filter(name__icontains=value)[:2])
    return partial[0] if len(partial) == 1 else None


class _ToolError(Exception):
    pass


def _project_filter(context, tool_input):
    value = tool_input.get("project")
    if not value:
        return None
    project = _project(context, str(value))
    if project is None:
        raise _ToolError(f"No project of yours matches {value!r}")
    return project


def _visible_issue(context, identifier):
    match = IDENTIFIER_RE.match(str(identifier or ""))
    if match is None:
        raise _ToolError(f"{identifier!r} is not a work item identifier like OSMG-12")
    issue = (
        _visible_issues(context.user, context.workspace.id)
        .filter(project__identifier__iexact=match.group(1), sequence_id=int(match.group(2)))
        .select_related("project", "state")
        .first()
    )
    if issue is None:
        raise _ToolError(f"No work item {identifier} that you can see")
    return issue


def _assignees(issue_ids):
    from plane.db.models import IssueAssignee

    names = {}
    for row in IssueAssignee.objects.filter(issue_id__in=issue_ids).select_related("assignee").order_by("created_at"):
        names.setdefault(row.issue_id, []).append(_name(row.assignee))
    return names


def _pr_state(pull):
    if pull.merged_at:
        return "merged"
    if pull.state == "closed":
        return "closed"
    return "draft" if pull.is_draft else "open"


def _github_links(context, issue):
    from plane.db.models import GitHubWorkItemLink

    links = GitHubWorkItemLink.objects.filter(issue=issue).select_related("pull_request")
    rows = []
    for link in links:
        row = {"kind": link.kind, "repository": link.repository_full_name, "ref": link.ref, "title": link.title}
        pull = link.pull_request
        if pull is not None:
            name = f"{pull.repository_full_name}#{pull.number}"
            row.update({"title": pull.title, "url": pull.html_url, "state": _pr_state(pull), "name": name})
            context.add_source("pull_request", pull.id, name, pull.title, pull.html_url)
        else:
            row["url"] = link.url
        rows.append(row)
    return rows


# --- tools -----------------------------------------------------------------------------------------


def _search_work_items(context, tool_input):
    query = str(tool_input.get("query") or "").strip()
    project = _project_filter(context, tool_input)
    issues = _visible_issues(context.user, context.workspace.id)
    if project is not None:
        issues = issues.filter(project=project)
    if tool_input.get("open_only"):
        issues = issues.filter(state__group__in=OPEN_GROUPS)
    if query:
        match = IDENTIFIER_RE.match(query)
        by_text = Q(name__icontains=query) | Q(description_stripped__icontains=query)
        if match:
            by_text |= Q(project__identifier__iexact=match.group(1), sequence_id=int(match.group(2)))
        issues = issues.filter(by_text)
    issues = list(issues.select_related("project", "state").order_by("-updated_at")[: MAX_ROWS + 1])
    more = len(issues) > MAX_ROWS
    issues = issues[:MAX_ROWS]
    names = _assignees([issue.id for issue in issues])
    rows = []
    for issue in issues:
        rows.append(
            {
                "identifier": _issue_identifier(issue),
                "title": issue.name,
                "state": issue.state.name if issue.state else None,
                "state_group": issue.state.group if issue.state else None,
                "assignees": names.get(issue.id, []),
                "target_date": _iso(issue.target_date),
                "project": issue.project.identifier,
            }
        )
    return rows, issues, more


def _get_work_item(context, tool_input):
    from plane.api.views.issue import visible_issue_q
    from plane.db.models import DecisionRequest, Issue, IssueComment, IssueRelation, WorkItemWaiting

    issue = _visible_issue(context, tool_input.get("identifier"))
    comments = IssueComment.objects.filter(issue=issue).select_related("actor").order_by("-created_at")[:LAST_COMMENTS]
    relations = list(
        IssueRelation.objects.filter(issue=issue, relation_type="blocked_by")
        .exclude(related_issue__state__group__in=("completed", "cancelled"))
        .filter(related_issue__deleted_at__isnull=True, related_issue__archived_at__isnull=True)
        .select_related("related_issue", "related_issue__project")
    )
    visible_blockers = set(
        Issue.issue_objects.filter(
            visible_issue_q(context.user), pk__in=[rel.related_issue_id for rel in relations]
        ).values_list("pk", flat=True)
    )
    blocked_by = []
    for rel in relations:
        blocker = rel.related_issue
        if blocker.id in visible_blockers:
            context.add_issue(blocker)
            blocked_by.append(f"{_issue_identifier(blocker)} {blocker.name}")
        else:
            blocked_by.append("a work item you can't see")
    waiting = [
        {"on": _name(row.waiting_on_user) or row.waiting_on_text, "note": row.note, "since": _iso(row.created_at)}
        for row in WorkItemWaiting.objects.filter(issue=issue, resolved_at__isnull=True).select_related(
            "waiting_on_user"
        )
    ]
    decisions = [
        {"question": row.question, "asked": _name(row.asked_user), "since": _iso(row.created_at)}
        for row in DecisionRequest.objects.filter(issue=issue, status="open").select_related("asked_user")
    ]
    context.add_issue(issue)
    return {
        "identifier": _issue_identifier(issue),
        "title": issue.name,
        "project": issue.project.identifier,
        "state": issue.state.name if issue.state else None,
        "state_group": issue.state.group if issue.state else None,
        "priority": issue.priority,
        "assignees": _assignees([issue.id]).get(issue.id, []),
        "target_date": _iso(issue.target_date),
        "description": _plain(issue.description_stripped or issue.description_html, DESCRIPTION_CHARS),
        "last_comments": [
            {"by": _name(c.actor), "at": _iso(c.created_at), "text": _plain(c.comment_stripped, COMMENT_CHARS)}
            for c in comments
        ],
        "blocked_by": blocked_by,
        "waiting_on": waiting,
        "open_decisions": decisions,
        "pull_requests": [row for row in _github_links(context, issue) if row["kind"] == "pull_request"],
    }


def _list_milestones(context, tool_input):
    from plane.db.models import Milestone

    project = _project_filter(context, tool_input)
    milestones = Milestone.objects.filter(project__in=_member_projects(context)).select_related("project")
    if project is not None:
        milestones = milestones.filter(project=project)
    days = tool_input.get("due_within_days")
    if days is not None:
        try:
            days = int(days)
        except (TypeError, ValueError):
            raise _ToolError("due_within_days must be a whole number")
        today = _local_date(context.user, timezone.now())
        milestones = milestones.filter(target_date__lte=today + timedelta(days=days))
    milestones = list(milestones.order_by("target_date", "title")[: MAX_ROWS + 1])
    more = len(milestones) > MAX_ROWS
    milestones = milestones[:MAX_ROWS]
    counts = {
        row["milestone_id"]: row
        for row in _visible_issues(context.user, context.workspace.id)
        .filter(milestone_id__in=[m.id for m in milestones])
        .values("milestone_id")
        .annotate(total=Count("id", distinct=True), open=Count("id", filter=Q(state__group__in=OPEN_GROUPS)))
    }
    rows = []
    for milestone in milestones:
        count = counts.get(milestone.id, {"total": 0, "open": 0})
        rows.append(
            {
                "title": milestone.title,
                "project": milestone.project.identifier,
                "target_date": _iso(milestone.target_date),
                "open_work_items": count["open"],
                "total_work_items": count["total"],
            }
        )
        url = f"/{context.slug}/projects/{milestone.project_id}/milestones/{milestone.id}"
        context.add_source("milestone", milestone.id, None, milestone.title, url)
    return rows, more


def _blocked(context, tool_input):
    project = _project_filter(context, tool_input)
    rows = _blocked_items(context.workspace.id, context.user)
    if project is not None:
        rows = [row for row in rows if row["issue"]["project_id"] == str(project.id)]
    more = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    for row in rows:
        issue = row["issue"]
        context.add_source(
            "work_item",
            issue["id"],
            issue["identifier"],
            issue["name"],
            f"/{context.slug}/browse/{issue['identifier']}/",
        )
    return [
        {
            "identifier": row["issue"]["identifier"],
            "title": row["issue"]["name"],
            "state": row["issue"]["state_name"],
            "reasons": [
                {"kind": why["kind"], "detail": why["detail"] or "a work item you can't see", "since": why["since"]}
                for why in row["reasons"]
            ],
        }
        for row in rows
    ], more


def _search_pages(context, tool_input):
    from plane.app.permissions import ROLE
    from plane.db.models import Page, ProjectMember, ProjectPage
    from plane.utils.workspace_pages import workspace_pages

    query = str(tool_input.get("query") or "").strip()
    text = Q(name__icontains=query) | Q(description_stripped__icontains=query) if query else Q()
    # Project pages, with the access rule ProjectPagePermission applies: a person sees their own pages in
    # their projects, and public pages only where they are above guest or the project lets guests see all.
    memberships = ProjectMember.objects.filter(
        workspace_id=context.workspace.id,
        member=context.user,
        is_active=True,
        project__archived_at__isnull=True,
        project__deleted_at__isnull=True,
    )
    member_of = set(memberships.values_list("project_id", flat=True))
    readable = set(
        memberships.filter(Q(role__gt=ROLE.GUEST.value) | Q(project__guest_view_all_features=True)).values_list(
            "project_id", flat=True
        )
    )
    in_projects = ProjectPage.objects.filter(deleted_at__isnull=True)
    own = in_projects.filter(project_id__in=member_of).values("page_id")
    public = in_projects.filter(project_id__in=readable).values("page_id")
    project_pages = (
        Page.objects.filter(workspace_id=context.workspace.id, archived_at__isnull=True)
        .filter(Q(owned_by=context.user, id__in=own) | Q(access=Page.PUBLIC_ACCESS, id__in=public))
        .filter(text)
        .prefetch_related("projects")
        .order_by("-updated_at")
    )
    pages = list(project_pages[: MAX_ROWS + 1])
    wiki = (
        workspace_pages(context.user, context.slug)
        .filter(archived_at__isnull=True)
        .filter(text)
        .prefetch_related("projects")
    )
    pages += list(wiki.order_by("-updated_at")[: MAX_ROWS + 1 - len(pages)]) if len(pages) <= MAX_ROWS else []
    more = len(pages) > MAX_ROWS
    rows = []
    for page in pages[:MAX_ROWS]:
        # A page can sit in several projects; link it through one the person can open it in. Wiki pages have none.
        allowed = member_of if page.owned_by_id == context.user.id else readable
        project = next((p for p in page.projects.all() if p.id in allowed), None)
        if project is not None:
            url = f"/{context.slug}/projects/{project.id}/pages/{page.id}"
        else:
            url = f"/{context.slug}/wiki/{page.id}"
        context.add_source("page", page.id, None, page.name, url)
        rows.append(
            {
                "title": page.name,
                "project": project.identifier if project else None,
                "excerpt": _plain(page.description_stripped or page.description_html, PAGE_EXCERPT_CHARS),
            }
        )
    return rows, more


def _github_activity(context, tool_input):
    issue = _visible_issue(context, tool_input.get("identifier"))
    context.add_issue(issue)
    return _github_links(context, issue)


def _fit(payload, rows_key=None):
    """JSON for a tool result within MAX_RESULT_CHARS, dropping rows from the end when needed."""
    text = json.dumps(payload, default=str)
    if rows_key is not None:
        rows = payload[rows_key]
        while len(text) > MAX_RESULT_CHARS and rows:
            rows.pop()
            payload["truncated"] = True
            text = json.dumps(payload, default=str)
    return text[:MAX_RESULT_CHARS]


def run_tool(context, name, tool_input):
    """Run one tool as ``context.user`` and return its result as JSON text."""
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    try:
        if name == "search_work_items":
            rows, issues, more = _search_work_items(context, tool_input)
            for issue in issues:
                context.add_issue(issue)
            return _fit({"results": rows, "truncated": more}, "results")
        if name == "get_work_item":
            item = _get_work_item(context, tool_input)
            text = json.dumps(item, default=str)
            while len(text) > MAX_RESULT_CHARS and item["last_comments"]:
                item["last_comments"].pop()
                text = json.dumps(item, default=str)
            return text[:MAX_RESULT_CHARS]
        if name == "list_milestones":
            rows, more = _list_milestones(context, tool_input)
            return _fit({"results": rows, "truncated": more}, "results")
        if name == "blocked_items":
            rows, more = _blocked(context, tool_input)
            return _fit({"results": rows, "truncated": more}, "results")
        if name == "search_pages":
            rows, more = _search_pages(context, tool_input)
            return _fit({"results": rows, "truncated": more}, "results")
        if name == "github_activity":
            rows = _github_activity(context, tool_input)
            return _fit({"results": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS}, "results")
    except _ToolError as error:
        return json.dumps({"error": str(error)})
    return json.dumps({"error": f"Unknown tool {name}"})


# --- the question loop ------------------------------------------------------------------------------


def _clean_question(question):
    if not isinstance(question, str) or not question.strip():
        raise AgentError("Ask a question", 400, "question")
    question = question.strip()
    if len(question) > MAX_QUESTION_LENGTH:
        raise AgentError(f"Questions can be at most {MAX_QUESTION_LENGTH} characters", 400, "question")
    return question


def _clean_history(history):
    if history in (None, ""):
        return []
    if not isinstance(history, (list, tuple)):
        raise AgentError("history must be a list of turns", 400, "history")
    turns = []
    for turn in list(history)[-MAX_HISTORY_TURNS:]:
        if (
            not isinstance(turn, dict)
            or turn.get("role") not in ("user", "assistant")
            or not isinstance(turn.get("content"), str)
            or not turn["content"].strip()
            or len(turn["content"]) > MAX_HISTORY_CONTENT
        ):
            raise AgentError("Each history turn needs a role and plain text content", 400, "history")
        turns.append({"role": turn["role"], "content": turn["content"]})
    # The conversation sent to Claude must start with the person
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    return turns


def _block_dict(block):
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if block.type == "text":
        return {"type": "text", "text": block.text}
    return None


def _text(response):
    return "".join(block.text for block in response.content if block.type == "text").strip()


def _cited(answer, sources):
    """Sources whose identifier or title appears in the answer, in order of first mention."""
    found = []
    lowered = answer.lower()
    for source in sources:
        positions = []
        if source["identifier"]:
            hit = re.search(rf"(?<![A-Za-z0-9]){re.escape(source['identifier'])}(?![0-9])", answer, re.IGNORECASE)
            if hit:
                positions.append(hit.start())
        title = (source["title"] or "").strip()
        if len(title) >= MIN_TITLE_MENTION:
            index = lowered.find(title.lower())
            if index >= 0:
                positions.append(index)
        if positions:
            found.append((min(positions), source))
    found.sort(key=lambda pair: pair[0])
    return [source for _, source in found]


def ask(workspace, user, question, history=()):
    """Answer ``question`` for ``user`` from Plane data. Returns {"answer", "sources"}.

    Raises AgentError for a bad question or history, no key (400), the monthly limit (409) or an API error (502)."""
    question = _clean_question(question)
    messages = _clean_history(history) + [{"role": "user", "content": question}]
    context = AskContext(workspace, user)
    system = SYSTEM_PROMPT.format(today=_local_date(user, timezone.now()).isoformat())
    response = None
    for round_number in range(MAX_TOOL_ROUNDS + 1):
        kwargs = {"system": system, "messages": list(messages), "tools": TOOLS, "max_tokens": MAX_TOKENS}
        if round_number == MAX_TOOL_ROUNDS:
            # Out of tool rounds: answer with what has been found
            kwargs["tool_choice"] = {"type": "none"}
        response = ai_message(workspace, user, "ask", **kwargs)
        tool_uses = [block for block in response.content if block.type == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses or round_number == MAX_TOOL_ROUNDS:
            break
        messages.append({"role": "assistant", "content": [b for b in map(_block_dict, response.content) if b]})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": run_tool(context, block.name, block.input),
                    }
                    for block in tool_uses
                ],
            }
        )
    answer = _text(response) or "I couldn't find an answer to that in this workspace."
    return {"answer": answer, "sources": _cited(answer, list(context.sources.values()))}


def rate_key(user):
    return f"ask:rate:{user.id}"


def check_rate(user):
    """At most RATE_LIMIT questions per person per RATE_WINDOW_SECONDS."""
    key = rate_key(user)
    cache.add(key, 0, timeout=RATE_WINDOW_SECONDS)
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add and incr
        cache.set(key, 1, timeout=RATE_WINDOW_SECONDS)
        count = 1
    if count > RATE_LIMIT:
        raise AgentError("You've asked a lot of questions; try again in a few minutes", 429, "rate_limited")
