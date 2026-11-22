# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.customer import (
    CustomerDetailAPIEndpoint,
    CustomerListCreateAPIEndpoint,
    CustomerPropertyDetailAPIEndpoint,
    CustomerPropertyListCreateAPIEndpoint,
    CustomerPropertyValueDetailAPIEndpoint,
    CustomerPropertyValueListAPIEndpoint,
    CustomerRequestDetailAPIEndpoint,
    CustomerRequestListCreateAPIEndpoint,
    CustomerWorkItemDetailAPIEndpoint,
    CustomerWorkItemListAPIEndpoint,
)

_BASE = "workspaces/<str:slug>/customers"
_ONE = f"{_BASE}/<uuid:customer_id>"
_PROPERTIES = "workspaces/<str:slug>/customer-properties"
_routes = [
    (_BASE, CustomerListCreateAPIEndpoint, ["get", "post", "delete"], "customers"),
    (_ONE, CustomerDetailAPIEndpoint, ["get", "patch", "delete"], "customer"),
    (f"{_ONE}/property-values", CustomerPropertyValueListAPIEndpoint, ["get", "post"], "customer-property-values"),
    (
        f"{_ONE}/property-values/<uuid:property_id>",
        CustomerPropertyValueDetailAPIEndpoint,
        ["get", "patch"],
        "customer-property-value",
    ),
    (f"{_ONE}/requests", CustomerRequestListCreateAPIEndpoint, ["get", "post"], "customer-requests"),
    (
        f"{_ONE}/requests/<uuid:request_id>",
        CustomerRequestDetailAPIEndpoint,
        ["get", "patch", "delete"],
        "customer-request",
    ),
    (f"{_ONE}/issues", CustomerWorkItemListAPIEndpoint, ["get", "post"], "customer-work-items"),
    (f"{_ONE}/issues/<uuid:issue_id>", CustomerWorkItemDetailAPIEndpoint, ["delete"], "customer-work-item"),
    (_PROPERTIES, CustomerPropertyListCreateAPIEndpoint, ["get", "post"], "customer-properties"),
    (
        f"{_PROPERTIES}/<uuid:property_id>",
        CustomerPropertyDetailAPIEndpoint,
        ["get", "patch", "delete"],
        "customer-property",
    ),
]

# The SDK adds a trailing slash; serve both (a redirect would drop bodies).
urlpatterns = [
    path(f"{route}/", view.as_view(http_method_names=methods), name=name) for route, view, methods, name in _routes
] + [
    path(route, view.as_view(http_method_names=methods), name=f"{name}-no-slash")
    for route, view, methods, name in _routes
]
