# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-authenticated (web app) versions of the relation definition and custom relation
endpoints; the logic is the external API's, only authentication and throttling differ."""

from plane.api.views.work_item_relation import (
    WorkItemCustomRelationDetailAPIEndpoint,
    WorkItemCustomRelationListCreateAPIEndpoint,
    WorkItemRelationDefinitionDetailAPIEndpoint,
    WorkItemRelationDefinitionListAPIEndpoint,
)
from plane.authentication.session import BaseSessionAuthentication


class _Session:
    authentication_classes = [BaseSessionAuthentication]

    def get_throttles(self):
        return []


class RelationDefinitionListEndpoint(_Session, WorkItemRelationDefinitionListAPIEndpoint):
    pass


class RelationDefinitionDetailEndpoint(_Session, WorkItemRelationDefinitionDetailAPIEndpoint):
    pass


class IssueCustomRelationListEndpoint(_Session, WorkItemCustomRelationListCreateAPIEndpoint):
    pass


class IssueCustomRelationDetailEndpoint(_Session, WorkItemCustomRelationDetailAPIEndpoint):
    pass
