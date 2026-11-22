# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-authenticated (web app) agent management."""

import uuid

from rest_framework import status
from rest_framework.response import Response

from plane.api.views.agents import (
    AgentLoopsAPIEndpoint,
    AgentRunAPIEndpoint,
    AgentRunCancelAPIEndpoint,
    AgentRunDelegateAPIEndpoint,
    AgentRunFollowUpAPIEndpoint,
    AgentRunsAPIEndpoint,
    agent_list,
    project_for,
    workspace_for,
)
from plane.api.views.base import BaseAPIView
from plane.authentication.session import BaseSessionAuthentication
from plane.api.views.issue import visible_issue_q
from plane.db.models import AgentApproval, AgentRun, Issue, WorkspaceAgent
from plane.utils import agent_runs, agents, ai_config, guardrails, loops, managed_agents


class _Session:
    authentication_classes = [BaseSessionAuthentication]

    def get_throttles(self):
        return []

    def _workspace(self, request, slug):
        return workspace_for(request, slug)

    def _agent(self, workspace, pk):
        return WorkspaceAgent.objects.filter(workspace=workspace, pk=pk).select_related("owner", "user").first()


def _not_found(what="Workspace"):
    return Response({"error": f"{what} not found"}, status=status.HTTP_404_NOT_FOUND)


def _data(request):
    return request.data if isinstance(request.data, dict) else {}


class AgentsEndpoint(_Session, BaseAPIView):
    def get(self, request, slug):
        workspace = self._workspace(request, slug)
        if workspace is None:
            return _not_found()
        return Response(agent_list(workspace))

    def post(self, request, slug):
        workspace = self._workspace(request, slug)
        if workspace is None:
            return _not_found()
        try:
            agent, token = agents.create_agent(workspace, _data(request), request.user)
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response({**agents.agent_payload(agent), "token": token}, status=status.HTTP_201_CREATED)


class AgentEndpoint(_Session, BaseAPIView):
    def get(self, request, slug, agent_id):
        workspace = self._workspace(request, slug)
        agent = self._agent(workspace, agent_id) if workspace else None
        if agent is None:
            return _not_found("Agent")
        return Response(agents.agent_payload(agent))

    def patch(self, request, slug, agent_id):
        workspace = self._workspace(request, slug)
        agent = self._agent(workspace, agent_id) if workspace else None
        if agent is None:
            return _not_found("Agent")
        try:
            agent = agents.update_agent(agent, _data(request), request.user)
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response(agents.agent_payload(agent))

    def delete(self, request, slug, agent_id):
        workspace = self._workspace(request, slug)
        agent = self._agent(workspace, agent_id) if workspace else None
        if agent is None:
            return _not_found("Agent")
        try:
            agents.deactivate_agent(agent, request.user)
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AgentAuditEndpoint(_Session, BaseAPIView):
    """An agent's audit trail (workspace admins only): requests, approvals and runs, newest first."""

    def get(self, request, slug, agent_id):
        workspace = self._workspace(request, slug)
        agent = self._agent(workspace, agent_id) if workspace else None
        if agent is None:
            return _not_found("Agent")
        try:
            agents.require_admin(workspace, request.user)
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response(agents.audit_for(agent))


class AgentRotateTokenEndpoint(_Session, BaseAPIView):
    def post(self, request, slug, agent_id):
        workspace = self._workspace(request, slug)
        agent = self._agent(workspace, agent_id) if workspace else None
        if agent is None:
            return _not_found("Agent")
        try:
            token = agents.rotate_token(agent, request.user)
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response({"token": token})


class AISettingsEndpoint(_Session, BaseAPIView):
    """The workspace's Claude key, model and monthly limit (admins only). Never returns the key."""

    def _workspace(self, request, slug):
        workspace = super()._workspace(request, slug)
        if workspace is not None:
            agents._require_admin(workspace, request.user)
        return workspace

    def _respond(self, request, slug, apply=None):
        try:
            workspace = self._workspace(request, slug)
            if workspace is None:
                return _not_found()
            if apply:
                apply(workspace)
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        return Response(ai_config.settings_payload(workspace))

    def get(self, request, slug):
        return self._respond(request, slug)

    def put(self, request, slug):
        return self._respond(request, slug, lambda ws: ai_config.update_settings(ws, _data(request), request.user))

    def delete(self, request, slug):
        return self._respond(request, slug, lambda ws: ai_config.clear_api_key(ws, request.user))


class CloudAgentsSetupEndpoint(AISettingsEndpoint):
    """Set up cloud agents on Claude Managed Agents: the workspace environment, then every active agent."""

    def post(self, request, slug):
        return self._respond(request, slug, lambda ws: managed_agents.setup_cloud_agents(ws, request.user))


class AgentRunsEndpoint(_Session, AgentRunsAPIEndpoint):
    pass


class AgentRunEndpoint(_Session, AgentRunAPIEndpoint):
    pass


class AgentRunDelegateEndpoint(_Session, AgentRunDelegateAPIEndpoint):
    pass


class AgentRunFollowUpEndpoint(_Session, AgentRunFollowUpAPIEndpoint):
    pass


class AgentRunCancelEndpoint(_Session, AgentRunCancelAPIEndpoint):
    pass


class LiveAgentRunsEndpoint(_Session, BaseAPIView):
    """Live runs for the given work items, keyed by work item id, for list and Brief badges."""

    MAX_IDS = 200

    def get(self, request, slug):
        workspace = self._workspace(request, slug)
        if workspace is None:
            return _not_found()
        ids = []
        for raw in (request.query_params.get("issue_ids") or "").split(",")[: self.MAX_IDS]:
            try:
                ids.append(uuid.UUID(raw.strip()))
            except ValueError:
                continue
        visible = Issue.issue_objects.filter(visible_issue_q(request.user), workspace=workspace, pk__in=ids)
        runs = agent_runs.live_runs_for(list(visible.values_list("pk", flat=True).distinct()))
        if request.query_params.get("meta") != "1":
            return Response(runs)
        # `poll` tells the web app whether anything in this workspace can be live, so idle workspaces stop polling
        can_be_live = (
            WorkspaceAgent.objects.filter(workspace=workspace, is_active=True).exists()
            or AgentRun.objects.filter(
                workspace=workspace,
                issue__isnull=False,
                issue__deleted_at__isnull=True,
                status__in=agent_runs.OPEN_STATUSES,
            ).exists()
        )
        return Response({"runs": runs, "poll": can_be_live})


class AgentApprovalsEndpoint(_Session, BaseAPIView):
    """Approvals waiting on (or decided by) the signed-in person; ?status=open for the ones to act on."""

    def get(self, request, slug):
        workspace = self._workspace(request, slug)
        if workspace is None:
            return _not_found()
        status_filter = request.query_params.get("status") or None
        if status_filter and status_filter not in dict(AgentApproval.STATUS_CHOICES):
            return Response({"status": "Unknown status"}, status=status.HTTP_400_BAD_REQUEST)
        rows = guardrails.approvals_for(workspace, request.user, status_filter)
        return Response([guardrails.approval_payload(a, request.user) for a in rows])


class AgentApprovalDecisionEndpoint(_Session, BaseAPIView):
    approve = True

    def post(self, request, slug, approval_id):
        workspace = self._workspace(request, slug)
        approval = (
            AgentApproval.objects.filter(workspace=workspace, pk=approval_id).select_related("agent").first()
            if workspace
            else None
        )
        if approval is None:
            return _not_found("Approval")
        try:
            approval = guardrails.decide_approval(approval, request.user, self.approve)
        except agents.AgentError as exc:
            return Response({exc.field: exc.message}, status=exc.status_code)
        approval = AgentApproval.objects.select_related("agent", "asked_user", "decided_by", "project").get(
            pk=approval.pk
        )
        return Response(guardrails.approval_payload(approval, request.user))


class AgentApprovalApproveEndpoint(AgentApprovalDecisionEndpoint):
    approve = True


class AgentApprovalRejectEndpoint(AgentApprovalDecisionEndpoint):
    approve = False


def _error(exc):
    return Response({exc.field: exc.message}, status=exc.status_code)


class AgentLoopsEndpoint(_Session, AgentLoopsAPIEndpoint):
    """A project's loops: project members list them, project and workspace admins create them."""

    def post(self, request, slug, project_id):
        project = project_for(request, slug, project_id)
        if project is None:
            return _not_found("Project")
        try:
            loop = loops.create_loop(project, _data(request), request.user)
        except agents.AgentError as exc:
            return _error(exc)
        return Response(loops.loop_payload(loop), status=status.HTTP_201_CREATED)


class _LoopView(_Session, BaseAPIView):
    def _loop(self, request, slug, project_id, loop_id):
        """The loop, once the request's user may see it; raises AgentError (403) otherwise."""
        project = project_for(request, slug, project_id)
        if project is None:
            return None
        loops.require_viewer(project, request.user)
        return loops.loops_for(project).filter(pk=loop_id).first()


class AgentLoopEndpoint(_LoopView):
    def get(self, request, slug, project_id, loop_id):
        try:
            loop = self._loop(request, slug, project_id, loop_id)
        except agents.AgentError as exc:
            return _error(exc)
        if loop is None:
            return _not_found("Loop")
        return Response(loops.loop_payload(loop))

    def patch(self, request, slug, project_id, loop_id):
        try:
            loop = self._loop(request, slug, project_id, loop_id)
            if loop is None:
                return _not_found("Loop")
            loop = loops.update_loop(loop, _data(request), request.user)
        except agents.AgentError as exc:
            return _error(exc)
        return Response(loops.loop_payload(loop))

    def delete(self, request, slug, project_id, loop_id):
        try:
            loop = self._loop(request, slug, project_id, loop_id)
            if loop is None:
                return _not_found("Loop")
            loops.delete_loop(loop, request.user)
        except agents.AgentError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AgentLoopRunNowEndpoint(_LoopView):
    def post(self, request, slug, project_id, loop_id):
        try:
            loop = self._loop(request, slug, project_id, loop_id)
            if loop is None:
                return _not_found("Loop")
            run = loops.run_now(loop, request.user)
        except agents.AgentError as exc:
            return _error(exc)
        return Response(agent_runs.run_payload(run, steps=True), status=status.HTTP_201_CREATED)


class AgentLoopRunsEndpoint(_LoopView):
    """The loop's runs, newest first (50)."""

    def get(self, request, slug, project_id, loop_id):
        try:
            loop = self._loop(request, slug, project_id, loop_id)
        except agents.AgentError as exc:
            return _error(exc)
        if loop is None:
            return _not_found("Loop")
        rows = agent_runs.runs_for_loop(loop).order_by("-created_at")[: loops.RUNS_MAX]
        return Response([agent_runs.run_payload(run) for run in rows])


class AgentLoopRunEndpoint(_LoopView):
    """One of the loop's runs with its steps; members follow up on it or cancel it as on a work item's run."""

    def _run(self, request, slug, project_id, loop_id, run_id):
        loop = self._loop(request, slug, project_id, loop_id)
        return agent_runs.runs_for_loop(loop).filter(pk=run_id).first() if loop else None

    def get(self, request, slug, project_id, loop_id, run_id):
        try:
            run = self._run(request, slug, project_id, loop_id, run_id)
        except agents.AgentError as exc:
            return _error(exc)
        if run is None:
            return _not_found("Run")
        return Response(agent_runs.run_payload(run, steps=True))


class AgentLoopRunFollowUpEndpoint(AgentLoopRunEndpoint):
    def post(self, request, slug, project_id, loop_id, run_id):
        try:
            run = self._run(request, slug, project_id, loop_id, run_id)
            if run is None:
                return _not_found("Run")
            run = managed_agents.send_follow_up(run, request.user, _data(request).get("text"))
        except agents.AgentError as exc:
            return _error(exc)
        return Response(agent_runs.run_payload(run, steps=True))


class AgentLoopRunCancelEndpoint(AgentLoopRunEndpoint):
    def post(self, request, slug, project_id, loop_id, run_id):
        try:
            run = self._run(request, slug, project_id, loop_id, run_id)
            if run is None:
                return _not_found("Run")
            run = managed_agents.cancel_run(run, request.user)
        except agents.AgentError as exc:
            return _error(exc)
        return Response(agent_runs.run_payload(run, steps=True))
