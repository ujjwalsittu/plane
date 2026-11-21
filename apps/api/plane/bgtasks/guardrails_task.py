# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Daily expiry of agent approvals nobody decided on."""

from celery import shared_task

from plane.utils.guardrails import expire_approvals


@shared_task
def expire_agent_approvals():
    return expire_approvals()
