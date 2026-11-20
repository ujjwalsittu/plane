# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-authenticated (web app) versions of the team endpoints."""

from plane.api.views import teamspace as api
from plane.authentication.session import BaseSessionAuthentication


class _Session:
    authentication_classes = [BaseSessionAuthentication]

    def get_throttles(self):
        return []


class TeamspaceListEndpoint(_Session, api.TeamspaceListCreateAPIEndpoint):
    pass


class TeamspaceEndpoint(_Session, api.TeamspaceDetailAPIEndpoint):
    pass


class TeamspaceMemberEndpoint(_Session, api.TeamspaceMemberAPIEndpoint):
    pass


class TeamspaceProjectEndpoint(_Session, api.TeamspaceProjectAPIEndpoint):
    pass


class TeamspaceWorkItemEndpoint(_Session, api.TeamspaceWorkItemAPIEndpoint):
    pass


class TeamspaceWorkloadEndpoint(_Session, api.TeamspaceWorkloadAPIEndpoint):
    pass
