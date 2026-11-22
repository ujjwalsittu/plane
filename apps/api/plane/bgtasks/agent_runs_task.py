# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Cloud runs in the background: follow every open session (every 15 seconds), interrupt the sessions of a
deactivated agent, and start the loops that are due (every minute)."""

from celery import shared_task
from django.core.cache import cache

from plane.db.models import AgentRun, Workspace
from plane.utils import loops, managed_agents
from plane.utils.agent_runs import OPEN_STATUSES
from plane.utils.exception_logger import log_exception

# One sync of every open run at a time; a tick that finds one still going skips. The lock outlives a crashed
# worker by at most this long.
SYNC_ALL_LOCK = "agent-runs:sync-all"
SYNC_ALL_LOCK_SECONDS = 300


@shared_task
def sync_agent_runs():
    if not cache.add(SYNC_ALL_LOCK, 1, SYNC_ALL_LOCK_SECONDS):
        return
    try:
        _sync_all()
    finally:
        cache.delete(SYNC_ALL_LOCK)


def _sync_all():
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


@shared_task
def run_due_loops():
    loops.run_due_loops()
