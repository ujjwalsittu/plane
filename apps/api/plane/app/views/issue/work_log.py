# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-authenticated (web app) versions of the work log endpoints."""

from plane.api.views.work_log import (
    ProjectWorkLogSummaryAPIEndpoint,
    WorkLogDetailAPIEndpoint,
    WorkLogListCreateAPIEndpoint,
)
from plane.authentication.session import BaseSessionAuthentication


class _Session:
    authentication_classes = [BaseSessionAuthentication]

    def get_throttles(self):
        return []


class IssueWorkLogEndpoint(_Session, WorkLogListCreateAPIEndpoint):
    pass


class IssueWorkLogDetailEndpoint(_Session, WorkLogDetailAPIEndpoint):
    pass


class ProjectWorkLogSummaryEndpoint(_Session, ProjectWorkLogSummaryAPIEndpoint):
    pass
