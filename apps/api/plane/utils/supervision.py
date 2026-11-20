# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Supervision: who did the work (an agent or a person) and what needs a human's attention."""


class SupervisionError(ValueError):
    def __init__(self, message, status_code=400, field="error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.field = field


def is_agent_activity(activity):
    """An activity is an agent's when it came in through an API key or its actor is a bot user."""
    if activity.source == "api":
        return True
    return bool(activity.actor_id and activity.actor.is_bot)
