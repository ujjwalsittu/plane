# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-authenticated (web app) versions of the workspace page and collection endpoints."""

from plane.api.views.workspace_page import (
    CollectionDetailAPIEndpoint,
    CollectionListCreateAPIEndpoint,
    CollectionPageDetailAPIEndpoint,
    CollectionPageListAddAPIEndpoint,
    WorkspacePageArchiveAPIEndpoint,
    WorkspacePageDetailAPIEndpoint,
    WorkspacePageListCreateAPIEndpoint,
)
from plane.authentication.session import BaseSessionAuthentication


class _Session:
    authentication_classes = [BaseSessionAuthentication]

    def get_throttles(self):
        return []


class WikiPageListEndpoint(_Session, WorkspacePageListCreateAPIEndpoint):
    pass


class WikiPageDetailEndpoint(_Session, WorkspacePageDetailAPIEndpoint):
    pass


class WikiPageArchiveEndpoint(_Session, WorkspacePageArchiveAPIEndpoint):
    pass


class WikiCollectionListEndpoint(_Session, CollectionListCreateAPIEndpoint):
    pass


class WikiCollectionDetailEndpoint(_Session, CollectionDetailAPIEndpoint):
    pass


class WikiCollectionPagesEndpoint(_Session, CollectionPageListAddAPIEndpoint):
    pass


class WikiCollectionPageEndpoint(_Session, CollectionPageDetailAPIEndpoint):
    pass
