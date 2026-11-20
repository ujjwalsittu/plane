# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Teams (teamspaces) for the SDK: workspaces/<slug>/teamspaces, their members and projects, plus
the team's work items and workload (used by the web app)."""

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions import WorkspaceEntityPermission
from plane.db.models import Teamspace, Workspace
from plane.utils import teamspaces


def _data(request):
    return request.data if isinstance(request.data, dict) else {}


def _error(exc):
    return Response({"error": exc.message, exc.field: exc.message}, status=exc.status_code)


def _missing():
    return Response({"error": "Team not found"}, status=status.HTTP_404_NOT_FOUND)


def _team(slug, team_id):
    return Teamspace.objects.filter(workspace__slug=slug, pk=team_id).first()


class _Base(BaseAPIView):
    model = Teamspace
    permission_classes = [WorkspaceEntityPermission]


class TeamspaceListCreateAPIEndpoint(_Base):
    def get(self, request, slug):
        rows = Teamspace.objects.filter(workspace__slug=slug).order_by("name")
        return self.paginate(
            request=request, queryset=rows, on_results=lambda page: [teamspaces.team_payload(t) for t in page]
        )

    def post(self, request, slug):
        workspace_id = Workspace.objects.filter(slug=slug).values_list("id", flat=True).first()
        try:
            team = teamspaces.save_team(workspace_id, _data(request))
        except teamspaces.TeamError as exc:
            return _error(exc)
        return Response(teamspaces.team_payload(team), status=status.HTTP_201_CREATED)


class TeamspaceDetailAPIEndpoint(_Base):
    def get(self, request, slug, team_id):
        team = _team(slug, team_id)
        return Response(teamspaces.team_payload(team)) if team else _missing()

    def patch(self, request, slug, team_id):
        team = _team(slug, team_id)
        if team is None:
            return _missing()
        try:
            team = teamspaces.save_team(team.workspace_id, _data(request), team=team)
        except teamspaces.TeamError as exc:
            return _error(exc)
        return Response(teamspaces.team_payload(team))

    def delete(self, request, slug, team_id):
        team = _team(slug, team_id)
        if team is None:
            return _missing()
        teamspaces.delete_team(team)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TeamspaceMemberAPIEndpoint(_Base):
    def get(self, request, slug, team_id):
        team = _team(slug, team_id)
        if team is None:
            return _missing()
        return self.paginate(
            request=request,
            queryset=teamspaces.team_members(team),
            on_results=lambda page: [teamspaces.user_payload(u) for u in page],
        )

    def post(self, request, slug, team_id):
        team = _team(slug, team_id)
        if team is None:
            return _missing()
        try:
            users = teamspaces.add_members(team, _data(request))
        except teamspaces.TeamError as exc:
            return _error(exc)
        return Response([teamspaces.user_payload(u) for u in users], status=status.HTTP_201_CREATED)

    def delete(self, request, slug, team_id):
        team = _team(slug, team_id)
        if team is None:
            return _missing()
        try:
            teamspaces.remove_members(team, _data(request))
        except teamspaces.TeamError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TeamspaceProjectAPIEndpoint(_Base):
    def get(self, request, slug, team_id):
        team = _team(slug, team_id)
        if team is None:
            return _missing()
        return self.paginate(
            request=request,
            queryset=teamspaces.team_projects(team),
            on_results=lambda page: [teamspaces.project_payload(p) for p in page],
        )

    def post(self, request, slug, team_id):
        team = _team(slug, team_id)
        if team is None:
            return _missing()
        try:
            projects = teamspaces.add_projects(team, _data(request))
        except teamspaces.TeamError as exc:
            return _error(exc)
        return Response([teamspaces.project_payload(p) for p in projects], status=status.HTTP_201_CREATED)

    def delete(self, request, slug, team_id):
        team = _team(slug, team_id)
        if team is None:
            return _missing()
        try:
            teamspaces.remove_projects(team, _data(request))
        except teamspaces.TeamError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TeamspaceWorkItemAPIEndpoint(_Base):
    """GET ?view=assigned|unassigned&state_group=a,b&member_id=&project_id= -- the team's work the
    caller can see (projects they belong to)."""

    def get(self, request, slug, team_id):
        team = _team(slug, team_id)
        if team is None:
            return _missing()
        groups = [g for g in (request.GET.get("state_group") or "").split(",") if g in teamspaces.STATE_GROUPS]
        rows = teamspaces.team_work_items(
            team,
            request.user,
            view="unassigned" if request.GET.get("view") == "unassigned" else "assigned",
            state_groups=groups or None,
            member_id=request.GET.get("member_id") or None,
            project_id=request.GET.get("project_id") or None,
        )
        return self.paginate(
            request=request,
            queryset=rows.order_by("-updated_at"),
            on_results=lambda page: [teamspaces.work_item_payload(issue) for issue in page],
        )


class TeamspaceWorkloadAPIEndpoint(_Base):
    def get(self, request, slug, team_id):
        team = _team(slug, team_id)
        if team is None:
            return _missing()
        return Response(teamspaces.workload(team, request.user))
