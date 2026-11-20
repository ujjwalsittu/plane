# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-authenticated (web app) versions of the supervision endpoints."""

from plane.api.views import supervision as api
from plane.authentication.session import BaseSessionAuthentication


class _Session:
    authentication_classes = [BaseSessionAuthentication]

    def get_throttles(self):
        return []


class WorkItemWaitingEndpoint(_Session, api.WorkItemWaitingAPIEndpoint):
    pass
