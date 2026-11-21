# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Keeps an agent's Claude Managed Agents agent and vault in step, off the request. Takes only the agent id: the
token is read from the database, never passed through the broker."""

from celery import shared_task

from plane.db.models import WorkspaceAgent
from plane.utils.managed_agents import sync_agent


@shared_task
def sync_cloud_agent(agent_id):
    agent = WorkspaceAgent.objects.filter(pk=agent_id).select_related("workspace").first()
    if agent is not None:
        sync_agent(agent)
