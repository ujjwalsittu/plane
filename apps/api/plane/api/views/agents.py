# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Agents as workspace members."""

from rest_framework import status
from rest_framework.response import Response

from plane.api.views.base import BaseAPIView
from plane.api.views.issue import guest_cannot_view_issue
from plane.app.permissions import ROLE, ProjectEntityPermission
from plane.db.models import AgentApproval, AgentRun, Issue, Project, ProjectMember, Workspace, WorkspaceAgent
from plane.utils import agent_runs, agents, guardrails, loops, managed_agents, triage


def workspace_for(request, slug):
    return Workspace.objects.filter(
        slug=slug, workspace_member__member=request.user, workspace_member__is_active=True
    ).first()


def agent_list(workspace):
    rows = WorkspaceAgent.objects.filter(workspace=workspace).select_related("owner", "user")
    return [agents.agent_payload(agent) for agent in rows]


class WorkspaceAgentsAPIEndpoint(BaseAPIView):
    """Read-only list so agents can see each other."""

    def get(self, request, slug):
        workspace = workspace_for(request, slug)
        if workspace is None:
            return Response({"error": "Workspace not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(agent_list(workspace))


def project_for(request, slug, project_id):
    workspace = workspace_for(request, slug)
    if workspace is None:
        return None
    return Project.objects.filter(workspace=workspace, pk=project_id).select_related("workspace").first()


def _issue(request, slug, project_id, issue_id):
    issue = (
        Issue.issue_objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id)
        .select_related("project")
        .first()
    )
    if issue is None or guest_cannot_view_issue(request.user.id, issue, slug):
        return None
    return issue


def _data(request):
    return request.data if isinstance(request.data, dict) else {}


def _missing(what="Work item"):
    return Response({"error": f"{what} not found"}, status=status.HTTP_404_NOT_FOUND)


class AgentRunsAPIEndpoint(BaseAPIView):
    """The run log of a work item: list the runs, report a new one."""

    permission_classes = [ProjectEntityPermission]
    model = AgentRun

    def get(self, request, slug, project_id, issue_id):
        issue = _issue(request, slug, project_id, issue_id)
        if issue is None:
            return _missing()
        return Response([agent_runs.run_payload(run) for run in agent_runs.runs_for_issue(issue)])

    def post(self, request, slug, project_id, issue_id):
        issue = _issue(request, slug, project_id, issue_id)
        if issue is None:
            return _missing()
        try:
            run = agent_runs.start_external_run(issue, request.user, _data(request))
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response(agent_runs.run_payload(run, steps=True), status=status.HTTP_201_CREATED)


class AgentRunAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectEntityPermission]
    model = AgentRun

    def _run(self, request, slug, project_id, issue_id, run_id):
        issue = _issue(request, slug, project_id, issue_id)
        if issue is None:
            return None
        return agent_runs.runs_for_issue(issue).filter(pk=run_id).first()

    def get(self, request, slug, project_id, issue_id, run_id):
        run = self._run(request, slug, project_id, issue_id, run_id)
        if run is None:
            return _missing("Run")
        return Response(agent_runs.run_payload(run, steps=True))

    def patch(self, request, slug, project_id, issue_id, run_id):
        run = self._run(request, slug, project_id, issue_id, run_id)
        if run is None:
            return _missing("Run")
        try:
            run = agent_runs.update_run(run, _data(request), request.user)
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response(agent_runs.run_payload(run, steps=True))


class AgentRunStepsAPIEndpoint(AgentRunAPIEndpoint):
    def post(self, request, slug, project_id, issue_id, run_id):
        run = self._run(request, slug, project_id, issue_id, run_id)
        if run is None:
            return _missing("Run")
        if run.actor_id != request.user.id:
            return Response({"error": "Only the run's reporter can change it"}, status=status.HTTP_403_FORBIDDEN)
        if run.status in agent_runs.TERMINAL_STATUSES:
            return Response({"status": "The run has already finished"}, status=status.HTTP_409_CONFLICT)
        data = _data(request)
        try:
            step = agent_runs.add_step(
                run, data.get("kind", "message"), data.get("text"), data.get("data"), data.get("external_event_id", "")
            )
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        if step is None:
            return Response({"duplicate": True}, status=status.HTTP_200_OK)
        return Response(agent_runs.step_payload(step), status=status.HTTP_201_CREATED)


class AgentRunDelegateAPIEndpoint(BaseAPIView):
    """Delegate the work item to a cloud agent: Plane starts a Claude Managed Agents session with it as the brief."""

    permission_classes = [ProjectEntityPermission]
    model = AgentRun

    def post(self, request, slug, project_id, issue_id):
        issue = _issue(request, slug, project_id, issue_id)
        if issue is None:
            return _missing()
        data = _data(request)
        try:
            agent_id = agents._uuid(data.get("agent_id"), "agent_id")
            agent = WorkspaceAgent.objects.filter(workspace_id=issue.workspace_id, pk=agent_id).first()
            if agent is None:
                raise agents.AgentError("Unknown agent", 400, "agent_id")
            run = managed_agents.start_managed_run(issue, agent, request.user, data.get("instructions", ""))
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response(agent_runs.run_payload(run, steps=True), status=status.HTTP_201_CREATED)


class AgentRunFollowUpAPIEndpoint(AgentRunAPIEndpoint):
    def post(self, request, slug, project_id, issue_id, run_id):
        run = self._run(request, slug, project_id, issue_id, run_id)
        if run is None:
            return _missing("Run")
        try:
            run = managed_agents.send_follow_up(run, request.user, _data(request).get("text"))
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response(agent_runs.run_payload(run, steps=True))


class AgentRunCancelAPIEndpoint(AgentRunAPIEndpoint):
    def post(self, request, slug, project_id, issue_id, run_id):
        run = self._run(request, slug, project_id, issue_id, run_id)
        if run is None:
            return _missing("Run")
        try:
            run = managed_agents.cancel_run(run, request.user)
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response(agent_runs.run_payload(run, steps=True))


class AgentApprovalAPIEndpoint(BaseAPIView):
    """An agent checks the outcome of a request that waited for approval."""

    def get(self, request, slug, approval_id):
        workspace = workspace_for(request, slug)
        approval = (
            AgentApproval.objects.filter(workspace=workspace, pk=approval_id)
            .select_related("agent", "asked_user", "decided_by", "project")
            .first()
            if workspace
            else None
        )
        if approval is None or not guardrails.can_view(approval, request.user):
            return _missing("Approval")
        return Response(guardrails.approval_payload(approval, request.user))


class AgentLoopsAPIEndpoint(BaseAPIView):
    """A project's loops, read-only, for project members."""

    def get(self, request, slug, project_id):
        project = project_for(request, slug, project_id)
        if project is None:
            return _missing("Project")
        try:
            loops.require_viewer(project, request.user)
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response([loops.loop_payload(loop) for loop in loops.loops_for(project)])


def triage_issue(request, slug, project_id, issue_id):
    """(work item, None) when the person may get triage suggestions for it, else (None, (message, status)).

    Members and admins of the project only. Intake items sit in a triage state the default work item manager
    hides, so this looks the item up with the plain manager."""
    if not ProjectMember.objects.filter(
        workspace__slug=slug,
        project_id=project_id,
        member=request.user,
        is_active=True,
        role__gte=ROLE.MEMBER.value,
        project__archived_at__isnull=True,
        project__deleted_at__isnull=True,
    ).exists():
        return None, ("Only project members can get suggestions", status.HTTP_403_FORBIDDEN)
    issue = (
        Issue.objects.filter(workspace__slug=slug, project_id=project_id, pk=issue_id, is_draft=False)
        .select_related("project", "workspace")
        .first()
    )
    if issue is None:
        return None, ("Work item not found", status.HTTP_404_NOT_FOUND)
    return issue, None


class WorkItemTriageAPIEndpoint(BaseAPIView):
    """Suggested assignee, labels, project and duplicates for a work item; `?refresh=1` asks Claude again."""

    def get(self, request, slug, project_id, issue_id):
        issue, refusal = triage_issue(request, slug, project_id, issue_id)
        if refusal is not None:
            return Response({"error": refusal[0]}, status=refusal[1])
        try:
            return Response(triage.suggest(issue, request.user, refresh=request.query_params.get("refresh") == "1"))
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
