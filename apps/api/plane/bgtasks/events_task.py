# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Daily clean-up of the workspace event log."""

from celery import shared_task

from plane.utils.events import prune_events as _prune_events


@shared_task
def prune_events():
    return _prune_events()
