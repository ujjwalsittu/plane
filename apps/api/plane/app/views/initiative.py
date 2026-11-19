# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-authenticated (web app) versions of the initiative endpoints."""

from plane.api.views.initiative import (
    InitiativeDetailAPIEndpoint,
    InitiativeListCreateAPIEndpoint,
    InitiativeProjectAPIEndpoint,
    InitiativeWorkItemAPIEndpoint,
)
from plane.authentication.session import BaseSessionAuthentication


class _Session:
    authentication_classes = [BaseSessionAuthentication]

    def get_throttles(self):
        return []


class InitiativeListEndpoint(_Session, InitiativeListCreateAPIEndpoint):
    pass


class InitiativeEndpoint(_Session, InitiativeDetailAPIEndpoint):
    pass


class InitiativeProjectEndpoint(_Session, InitiativeProjectAPIEndpoint):
    pass


class InitiativeWorkItemEndpoint(_Session, InitiativeWorkItemAPIEndpoint):
    pass
