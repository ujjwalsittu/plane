# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Initiatives, shared by the external API (SDK/MCP) and the app API (web)."""

# Python imports
from datetime import date

# Django imports
from django.db import transaction
from django.db.models import Count, Q

# Module imports
from plane.db.models import Initiative, InitiativeProject, InitiativeWorkItem, Issue, Project, WorkspaceMember
from plane.utils.html_processor import html_to_plain_text


class InitiativeError(ValueError):
    def __init__(self, message, status_code=400, field="error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.field = field


def _iso(value):
    return value.isoformat() if value else None


def _date(data, field):
    value = data.get(field)
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise InitiativeError(f"{field} must be a date (YYYY-MM-DD)", field=field)


# --- progress -------------------------------------------------------------------------------------


def _work_items(initiative):
    """The work items an initiative covers: every item of its projects plus the ones linked directly."""
    project_ids = initiative.project_links.values_list("project_id", flat=True)
    direct_ids = initiative.work_item_links.values_list("issue_id", flat=True)
    return Issue.issue_objects.filter(
        Q(project_id__in=project_ids) | Q(pk__in=direct_ids), workspace_id=initiative.workspace_id
    )


def progress(initiative):
    counts = _work_items(initiative).aggregate(
        total=Count("id", distinct=True),
        completed=Count("id", filter=Q(state__group="completed"), distinct=True),
        cancelled=Count("id", filter=Q(state__group="cancelled"), distinct=True),
        started=Count("id", filter=Q(state__group="started"), distinct=True),
        unstarted=Count("id", filter=Q(state__group="unstarted"), distinct=True),
        backlog=Count("id", filter=Q(state__group="backlog"), distinct=True),
    )
    active = counts["total"] - counts["cancelled"]
    counts["percent"] = round(100 * counts["completed"] / active) if active else 0
    return counts


# --- payloads -------------------------------------------------------------------------------------


def payload(initiative, with_progress=True):
    data = {
        "id": str(initiative.id),
        "name": initiative.name,
        "description": initiative.description_stripped,
        "description_html": initiative.description_html,
        "description_stripped": initiative.description_stripped,
        "start_date": _iso(initiative.start_date),
        "end_date": _iso(initiative.end_date),
        "logo_props": initiative.logo_props or {},
        "state": initiative.state,
        "lead": str(initiative.lead_id) if initiative.lead_id else None,
        "workspace": str(initiative.workspace_id),
        "sort_order": initiative.sort_order,
        "project_ids": [str(pid) for pid in initiative.project_links.values_list("project_id", flat=True)],
        "work_item_ids": [str(iid) for iid in initiative.work_item_links.values_list("issue_id", flat=True)],
        "created_at": _iso(initiative.created_at),
        "updated_at": _iso(initiative.updated_at),
        "deleted_at": _iso(initiative.deleted_at),
        "created_by": str(initiative.created_by_id) if initiative.created_by_id else None,
    }
    if with_progress:
        data["progress"] = progress(initiative)
    return data


# --- create / update ------------------------------------------------------------------------------


def _apply(initiative, data, partial):
    if not partial or "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            raise InitiativeError("name is required", field="name")
        initiative.name = name[:255]
    if "description_html" in data:
        html = data.get("description_html") or "<p></p>"
        initiative.description_html = html
        initiative.description_stripped = html_to_plain_text(html)
    for field in ("start_date", "end_date"):
        if field in data:
            setattr(initiative, field, _date(data, field))
    if initiative.start_date and initiative.end_date and initiative.end_date < initiative.start_date:
        raise InitiativeError("end_date can't be before start_date", field="end_date")
    if data.get("state") is not None:
        state = str(data["state"]).upper()
        if state not in Initiative.STATES:
            raise InitiativeError(f"state is one of {', '.join(Initiative.STATES)}", field="state")
        initiative.state = state
    if "lead" in data:
        lead = data.get("lead")
        if (
            lead
            and not WorkspaceMember.objects.filter(
                workspace_id=initiative.workspace_id, member_id=lead, is_active=True
            ).exists()
        ):
            raise InitiativeError("lead is not a member of this workspace", field="lead")
        initiative.lead_id = lead or None
    if isinstance(data.get("logo_props"), dict):
        initiative.logo_props = data["logo_props"]
    if data.get("sort_order") is not None:
        initiative.sort_order = float(data["sort_order"])


def create(workspace, data):
    initiative = Initiative(workspace=workspace)
    _apply(initiative, data, partial=False)
    initiative.save()
    return initiative


def update(initiative, data):
    _apply(initiative, data, partial=True)
    initiative.save()
    return initiative


# --- links ----------------------------------------------------------------------------------------


def _ids(data, *names):
    for name in names:
        value = data.get(name)
        if value is not None:
            if isinstance(value, str):
                value = [v.strip() for v in value.split(",") if v.strip()]
            if not isinstance(value, list):
                raise InitiativeError(f"{name} must be a list of ids", field=name)
            return [str(v) for v in value]
    raise InitiativeError(f"{names[0]} is required", field=names[0])


@transaction.atomic
def add_projects(initiative, data):
    ids = _ids(data, "project_ids")
    projects = list(Project.objects.filter(workspace_id=initiative.workspace_id, pk__in=ids))
    if len(projects) != len(set(ids)):
        raise InitiativeError("Some projects are not in this workspace", field="project_ids")
    existing = set(initiative.project_links.values_list("project_id", flat=True))
    for project in projects:
        if project.id not in existing:
            InitiativeProject.objects.create(
                workspace_id=initiative.workspace_id, initiative=initiative, project=project
            )
    return projects


def remove_projects(initiative, data):
    initiative.project_links.filter(project_id__in=_ids(data, "project_ids")).delete()


@transaction.atomic
def add_work_items(initiative, data):
    ids = _ids(data, "work_item_ids", "epic_ids")
    issues = list(Issue.issue_objects.filter(workspace_id=initiative.workspace_id, pk__in=ids))
    if len(issues) != len(set(ids)):
        raise InitiativeError("Some work items are not in this workspace", field="work_item_ids")
    existing = set(initiative.work_item_links.values_list("issue_id", flat=True))
    for issue in issues:
        if issue.id not in existing:
            InitiativeWorkItem.objects.create(workspace_id=initiative.workspace_id, initiative=initiative, issue=issue)
    return issues


def remove_work_items(initiative, data):
    initiative.work_item_links.filter(issue_id__in=_ids(data, "work_item_ids", "epic_ids")).delete()


@transaction.atomic
def delete(initiative):
    # Soft deletion doesn't cascade right away; drop the links now.
    initiative.project_links.all().delete()
    initiative.work_item_links.all().delete()
    initiative.delete()
