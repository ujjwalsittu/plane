# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Daily expiry of agent approvals nobody decided on, and a frequent sweep of approved replays that died."""

from celery import shared_task

from plane.utils.guardrails import _fail_stuck_replays, expire_approvals


@shared_task
def expire_agent_approvals():
    return expire_approvals()


@shared_task
def fail_stuck_approval_replays():
    return _fail_stuck_replays()
