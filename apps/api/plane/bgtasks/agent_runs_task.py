# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Cloud runs in the background: follow every open session (every 15 seconds), and interrupt the sessions of a
deactivated agent."""

from celery import shared_task

from plane.db.models import AgentRun, Workspace
from plane.utils import managed_agents
from plane.utils.agent_runs import OPEN_STATUSES
from plane.utils.exception_logger import log_exception


@shared_task
def sync_agent_runs():
    try:
        managed_agents.fail_unstarted_runs()
    except Exception as exc:
        log_exception(exc)
    run_ids = list(
        AgentRun.objects.filter(kind="managed", status__in=OPEN_STATUSES)
        .exclude(external_session_id="")
        .values_list("id", flat=True)
    )
    for run_id in run_ids:
        run = AgentRun.objects.select_related("workspace", "project", "issue").filter(pk=run_id).first()
        if run is None:
            continue
        # One bad run (or session) never stops the others
        try:
            managed_agents.sync_run(run)
        except Exception as exc:
            log_exception(exc)
        # Independent of whether the sync worked, so a run never stays open forever
        try:
            managed_agents.end_stalled_run(run)
        except Exception as exc:
            log_exception(exc)


@shared_task
def interrupt_sessions(workspace_id, session_ids):
    workspace = Workspace.objects.filter(pk=workspace_id).first()
    if workspace is not None:
        managed_agents.interrupt_sessions(workspace, session_ids)
