# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-authenticated (web app) versions of the release endpoints."""

from plane.api.views import release as api
from plane.authentication.session import BaseSessionAuthentication


class _Session:
    authentication_classes = [BaseSessionAuthentication]

    def get_throttles(self):
        return []


class ReleaseListEndpoint(_Session, api.ReleaseListCreateAPIEndpoint):
    pass


class ReleaseEndpoint(_Session, api.ReleaseDetailAPIEndpoint):
    pass


class ReleaseChangelogEndpoint(_Session, api.ReleaseChangelogAPIEndpoint):
    pass


class ReleaseWorkItemEndpoint(_Session, api.ReleaseWorkItemAPIEndpoint):
    pass


class ReleaseItemLabelEndpoint(_Session, api.ReleaseItemLabelAPIEndpoint):
    pass


class ReleaseTagListEndpoint(_Session, api.ReleaseTagListCreateAPIEndpoint):
    pass


class ReleaseTagEndpoint(_Session, api.ReleaseTagDetailAPIEndpoint):
    pass


class ReleaseLabelListEndpoint(_Session, api.ReleaseLabelListCreateAPIEndpoint):
    pass


class ReleaseLabelEndpoint(_Session, api.ReleaseLabelDetailAPIEndpoint):
    pass
