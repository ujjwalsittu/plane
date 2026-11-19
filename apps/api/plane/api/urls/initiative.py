# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.initiative import (
    InitiativeDetailAPIEndpoint,
    InitiativeListCreateAPIEndpoint,
    InitiativeProjectAPIEndpoint,
    InitiativeWorkItemAPIEndpoint,
)

_BASE = "workspaces/<str:slug>/initiatives"
_ONE = f"{_BASE}/<uuid:initiative_id>"
_routes = [
    (_BASE, InitiativeListCreateAPIEndpoint, ["get", "post"], "initiatives"),
    (_ONE, InitiativeDetailAPIEndpoint, ["get", "patch", "delete"], "initiative"),
    (f"{_ONE}/projects", InitiativeProjectAPIEndpoint, ["get", "post", "delete"], "initiative-projects"),
    (f"{_ONE}/work-items", InitiativeWorkItemAPIEndpoint, ["get", "post", "delete"], "initiative-work-items"),
    (f"{_ONE}/epics", InitiativeWorkItemAPIEndpoint, ["get", "post", "delete"], "initiative-epics"),
]

# The SDK calls these without a trailing slash; serve both (a redirect would drop bodies).
urlpatterns = [
    path(f"{route}/", view.as_view(http_method_names=methods), name=name) for route, view, methods, name in _routes
] + [
    path(route, view.as_view(http_method_names=methods), name=f"{name}-no-slash")
    for route, view, methods, name in _routes
]
