# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Teams (teamspaces), shared by the external API (SDK) and the app API (web): the team itself,
its members and projects, and the work assigned to it."""

# Django imports
from django.db import IntegrityError, transaction
from django.db.models import Count, Q

# Module imports
from plane.db.models import (
    Issue,
    Project,
    ProjectMember,
    Teamspace,
    TeamspaceMember,
    TeamspaceProject,
    User,
    WorkspaceMember,
)
from plane.utils.html_processor import html_to_plain_text

ADMIN, MEMBER = 20, 15
STATE_GROUPS = ("backlog", "unstarted", "started", "completed", "cancelled")
OPEN_GROUPS = ("backlog", "unstarted", "started")


class TeamError(ValueError):
    def __init__(self, message, status_code=400, field="error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.field = field


def _iso(value):
    return value.isoformat() if value else None


def member_ids(team):
    return [str(i) for i in team.member_links.values_list("member_id", flat=True)]


def project_ids(team):
    return [
        str(i)
        for i in team.project_links.filter(project__archived_at__isnull=True).values_list("project_id", flat=True)
    ]


def team_payload(team):
    return {
        "id": str(team.id),
        "name": team.name,
        "description_html": team.description_html,
        "description_json": team.description_json or None,
        "description_stripped": team.description_stripped,
        "logo_props": team.logo_props or {},
        "lead": str(team.lead_id) if team.lead_id else None,
        "member_ids": member_ids(team),
        "project_ids": project_ids(team),
        "workspace": str(team.workspace_id),
        "created_at": _iso(team.created_at),
        "updated_at": _iso(team.updated_at),
        "deleted_at": None,
        "created_by": str(team.created_by_id) if team.created_by_id else None,
        "updated_by": str(team.updated_by_id) if team.updated_by_id else None,
    }


def user_payload(user):
    return {
        "id": str(user.id),
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "avatar": user.avatar,
        "avatar_url": user.avatar_url,
        "display_name": user.display_name,
    }


def project_payload(project):
    return {
        "id": str(project.id),
        "name": project.name,
        "identifier": project.identifier,
        "description": project.description,
        "logo_props": project.logo_props or {},
        "workspace": str(project.workspace_id),
        "archived_at": _iso(project.archived_at),
        "created_at": _iso(project.created_at),
        "updated_at": _iso(project.updated_at),
    }


def _active_members(workspace_id):
    return WorkspaceMember.objects.filter(workspace_id=workspace_id, is_active=True)


def save_team(workspace_id, data, team=None):
    team = team or Teamspace(workspace_id=workspace_id)
    if team._state.adding or "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            raise TeamError("name is required", field="name")
        clash = Teamspace.objects.filter(workspace_id=workspace_id, name__iexact=name).exclude(pk=team.pk)
        if clash.exists():
            raise TeamError(f"A team named {name} already exists", status_code=409, field="name")
        team.name = name[:255]
    if data.get("description_html") is not None:
        team.description_html = data["description_html"] or "<p></p>"
        team.description_stripped = html_to_plain_text(team.description_html)
        team.description_json = data.get("description_json") or {}
    if isinstance(data.get("logo_props"), dict):
        team.logo_props = data["logo_props"]
    if "lead" in data:
        lead = data.get("lead") or None
        if lead and not _active_members(workspace_id).filter(member_id=lead).exists():
            raise TeamError("lead is not a member of this workspace", field="lead")
        team.lead_id = lead
    with transaction.atomic():
        team.save()
        # The lead is always on the team.
        if team.lead_id:
            _link(TeamspaceMember, {"workspace_id": workspace_id, "teamspace": team, "member_id": team.lead_id})
    return team


@transaction.atomic
def delete_team(team):
    team.member_links.all().delete()
    team.project_links.all().delete()
    team.delete()


def _ids(data, name):
    value = data.get(name)
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",") if v.strip()]
    if not isinstance(value, list) or not value:
        raise TeamError(f"{name} must be a non-empty list of ids", field=name)
    return [str(v) for v in value]


def _link(model, lookup):
    try:
        with transaction.atomic():
            model.objects.get_or_create(**lookup)
    except IntegrityError:
        pass


def add_members(team, data):
    ids = _ids(data, "member_ids")
    users = list(
        User.objects.filter(pk__in=_active_members(team.workspace_id).filter(member_id__in=ids).values("member_id"))
    )
    if len(users) != len(set(ids)):
        raise TeamError("Some members are not active members of this workspace", field="member_ids")
    for user in users:
        _link(TeamspaceMember, {"workspace_id": team.workspace_id, "teamspace": team, "member": user})
    return users


def remove_members(team, data):
    ids = _ids(data, "member_ids")
    if team.lead_id and str(team.lead_id) in ids:
        raise TeamError("The team lead can't be removed; change the lead first", field="member_ids")
    team.member_links.filter(member_id__in=ids).delete()


def team_members(team):
    return User.objects.filter(pk__in=team.member_links.values("member_id")).order_by("display_name")


def add_projects(team, data):
    ids = _ids(data, "project_ids")
    projects = list(Project.objects.filter(workspace_id=team.workspace_id, pk__in=ids, archived_at__isnull=True))
    if len(projects) != len(set(ids)):
        raise TeamError("Some projects are not active projects of this workspace", field="project_ids")
    for project in projects:
        _link(TeamspaceProject, {"workspace_id": team.workspace_id, "teamspace": team, "project": project})
    return projects


def remove_projects(team, data):
    team.project_links.filter(project_id__in=_ids(data, "project_ids")).delete()


def team_projects(team):
    return Project.objects.filter(pk__in=team.project_links.values("project_id"), archived_at__isnull=True).order_by(
        "name"
    )


# --- the team's work ------------------------------------------------------------------------------


def visible_project_ids(workspace_id, user):
    """Projects whose work items the user may read: those they belong to."""
    return ProjectMember.objects.filter(
        workspace_id=workspace_id, member=user, is_active=True, project__archived_at__isnull=True
    ).values("project_id")


def assigned_to_team_q(team_ids):
    """Work items assigned to at least one member of any of the teams."""
    members = TeamspaceMember.objects.filter(teamspace_id__in=team_ids).values("member_id")
    return Q(
        pk__in=Issue.objects.filter(
            issue_assignee__assignee_id__in=members, issue_assignee__deleted_at__isnull=True
        ).values("id")
    )


def team_work_items(team, user, view="assigned", state_groups=None, member_id=None, project_id=None):
    """The team's work items the user can see.

    view "assigned": assigned to team members, inside the team's projects when it has any.
    view "unassigned": not assigned to anyone, inside the team's projects (empty without projects)."""
    rows = Issue.issue_objects.filter(
        workspace_id=team.workspace_id, project_id__in=visible_project_ids(team.workspace_id, user)
    )
    projects = team.project_links.values("project_id")
    has_projects = team.project_links.exists()
    if view == "unassigned":
        if not has_projects:
            return Issue.objects.none()
        rows = rows.filter(project_id__in=projects).exclude(
            pk__in=Issue.objects.filter(issue_assignee__deleted_at__isnull=True, issue_assignee__isnull=False).values(
                "id"
            )
        )
    else:
        rows = rows.filter(assigned_to_team_q([team.id]))
        if has_projects:
            rows = rows.filter(project_id__in=projects)
    if member_id:
        rows = rows.filter(
            pk__in=Issue.objects.filter(
                issue_assignee__assignee_id=member_id, issue_assignee__deleted_at__isnull=True
            ).values("id")
        )
    if project_id:
        rows = rows.filter(project_id=project_id)
    if state_groups:
        rows = rows.filter(state__group__in=state_groups)
    return rows.select_related("project", "state").distinct()


def work_item_payload(issue):
    return {
        "id": str(issue.id),
        "name": issue.name,
        "project_id": str(issue.project_id),
        "project_identifier": issue.project.identifier,
        "sequence_id": issue.sequence_id,
        "priority": issue.priority,
        "state_id": str(issue.state_id) if issue.state_id else None,
        "state_name": issue.state.name if issue.state_id else None,
        "state_group": issue.state.group if issue.state_id else None,
        "target_date": _iso(issue.target_date),
        "assignee_ids": [
            str(i) for i in issue.issue_assignee.filter(deleted_at__isnull=True).values_list("assignee_id", flat=True)
        ],
    }


def workload(team, user):
    """Per member: open and completed work items assigned to them in the team's scope."""
    rows = team_work_items(team, user)
    counts = {
        str(row["issue_assignee__assignee_id"]): row
        for row in rows.filter(
            issue_assignee__deleted_at__isnull=True,
            issue_assignee__assignee_id__in=team.member_links.values("member_id"),
        )
        .values("issue_assignee__assignee_id")
        .annotate(
            open=Count("id", filter=Q(state__group__in=OPEN_GROUPS), distinct=True),
            started=Count("id", filter=Q(state__group="started"), distinct=True),
            completed=Count("id", filter=Q(state__group="completed"), distinct=True),
        )
    }
    result = []
    for member_id in member_ids(team):
        row = counts.get(member_id, {})
        result.append(
            {
                "member_id": member_id,
                "open": row.get("open", 0),
                "started": row.get("started", 0),
                "completed": row.get("completed", 0),
            }
        )
    unassigned = team_work_items(team, user, view="unassigned", state_groups=OPEN_GROUPS).count()
    return {"members": result, "unassigned_open": unassigned}
