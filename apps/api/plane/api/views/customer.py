# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Customers for the official Plane SDK and its MCP tools (customer, customer_property, customer_request).

Every endpoint is workspace-level: active workspace members and admins (role >= 15) may read and write,
guests get nothing. Agents are held by the P7 guardrail in plane.utils.guardrails.check_request, not
here: a non-manage agent's write needs a project_id in the URL, which these routes never have, so a
contribute agent may read customers but its writes are refused (403); a manage agent may write.

Errors from these endpoints are {"error": message, <field>: message}. Only work items the caller can
see (plane.api.views.issue.visible_issue_q) are listed, linked or unlinked."""

import re

# Django imports
from django.db import transaction
from django.db.models import Count, Q

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.serializers.customer import (
    CustomerError,
    apply_customer,
    apply_property,
    apply_request,
    clean_values,
    customer_payload,
    linked_work_item_payload,
    property_payload,
    request_payload,
    save_options,
    text,
    uuid_list,
    uuid_string,
    work_item_payload,
)
from plane.api.views.base import BaseAPIView
from plane.api.views.issue import visible_issue_q
from plane.app.permissions import WorkSpaceAdminPermission
from plane.db.models import (
    Customer,
    CustomerProperty,
    CustomerPropertyValue,
    CustomerRequest,
    CustomerRequestIssue,
    Issue,
    ProjectMember,
    Workspace,
)


def _not_found(what):
    return Response({"error": f"{what} not found"}, status=status.HTTP_404_NOT_FOUND)


def _body(request):
    if not isinstance(request.data, dict):
        raise CustomerError("The body must be a JSON object")
    return request.data


def _visible_issues(user, workspace_id):
    """Work items `user` may see in the workspace, leaving out deleted, archived and draft ones and those of
    deleted projects or memberships."""
    return Issue.issue_objects.filter(
        workspace_id=workspace_id,
        project__deleted_at__isnull=True,
        project_id__in=ProjectMember.objects.filter(member=user, is_active=True).values("project_id"),
        pk__in=Issue.issue_objects.filter(visible_issue_q(user)).values("pk"),
    )


def _live_links(**filters):
    """Customer work item links whose request (if any) is not deleted."""
    return CustomerRequestIssue.objects.filter(
        Q(customer_request__isnull=True) | Q(customer_request__deleted_at__isnull=True), **filters
    )


def _customers(slug):
    return (
        Customer.objects.filter(workspace__slug=slug)
        .select_related("logo_asset__workspace")
        .annotate(request_count=Count("requests", filter=Q(requests__deleted_at__isnull=True)))
    )


def _customer(slug, customer_id):
    return Customer.objects.filter(workspace__slug=slug, pk=customer_id).first()


def _payload(customer):
    return customer_payload(customer, customer.requests.count())


def _delete_customer(customer):
    with transaction.atomic():
        CustomerRequestIssue.objects.filter(customer=customer).delete()
        CustomerPropertyValue.objects.filter(customer=customer).delete()
        CustomerRequest.objects.filter(customer=customer).delete()
        customer.delete()


class _Base(BaseAPIView):
    permission_classes = [WorkSpaceAdminPermission]
    model = Customer

    def handle_exception(self, exc):
        if isinstance(exc, CustomerError):
            return Response({"error": exc.message, exc.field: exc.message}, status=exc.status_code)
        return super().handle_exception(exc)


# --- customers ------------------------------------------------------------------------------------


class CustomerListCreateAPIEndpoint(_Base):
    def get(self, request, slug):
        rows = _customers(slug)
        query = request.GET.get("query", "").strip()
        if query:
            rows = rows.filter(name__icontains=query)
        return self.paginate(
            request=request,
            queryset=rows,
            order_by="-created_at",
            on_results=lambda page: [customer_payload(row, row.request_count) for row in page],
        )

    def post(self, request, slug):
        """Upsert, as the SDK documents: match external_source + external_id when both are given, else the
        name; update the match (200) or create a customer (201)."""
        data = _body(request)
        workspace = Workspace.objects.get(slug=slug)
        external_source, external_id = text(data, "external_source"), text(data, "external_id")
        rows = Customer.objects.filter(workspace=workspace)
        match = None
        if external_source and external_id:
            match = rows.filter(external_source=external_source, external_id=external_id).first()
        if match is None:
            match = rows.filter(name=text(data, "name", required=True)).first()
        with transaction.atomic():
            customer = apply_customer(match or Customer(workspace=workspace), data, partial=match is not None)
            customer.save()
        return Response(_payload(customer), status=status.HTTP_200_OK if match is not None else status.HTTP_201_CREATED)

    def delete(self, request, slug):
        """Delete by external reference; no match still succeeds, as the SDK documents."""
        external_source = request.GET.get("external_source", "").strip()
        external_id = request.GET.get("external_id", "").strip()
        if not (external_source and external_id):
            raise CustomerError("Pass both external_source and external_id", field="external_id")
        match = Customer.objects.filter(
            workspace__slug=slug, external_source=external_source, external_id=external_id
        ).first()
        if match is not None:
            _delete_customer(match)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CustomerDetailAPIEndpoint(_Base):
    def get(self, request, slug, customer_id):
        customer = _customers(slug).filter(pk=customer_id).first()
        if customer is None:
            return _not_found("Customer")
        return Response(customer_payload(customer, customer.request_count))

    def patch(self, request, slug, customer_id):
        customer = _customer(slug, customer_id)
        if customer is None:
            return _not_found("Customer")
        with transaction.atomic():
            apply_customer(customer, _body(request), partial=True).save()
        return Response(_payload(customer))

    def delete(self, request, slug, customer_id):
        customer = _customer(slug, customer_id)
        if customer is None:
            return _not_found("Customer")
        _delete_customer(customer)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- properties -----------------------------------------------------------------------------------


def _properties(slug):
    return CustomerProperty.objects.filter(workspace__slug=slug).prefetch_related("options")


def _save_property(prop, data, partial, has_values):
    with transaction.atomic():
        options = apply_property(prop, data, partial, has_values)
        prop.save()
        if options is not None:
            save_options(prop, options)
    return CustomerProperty.objects.prefetch_related("options").get(pk=prop.pk)


class CustomerPropertyListCreateAPIEndpoint(_Base):
    model = CustomerProperty

    def get(self, request, slug):
        return self.paginate(
            request=request,
            queryset=_properties(slug),
            order_by="sort_order",
            on_results=lambda page: [property_payload(prop) for prop in page],
        )

    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        prop = _save_property(CustomerProperty(workspace=workspace), _body(request), partial=False, has_values=False)
        return Response(property_payload(prop), status=status.HTTP_201_CREATED)


class CustomerPropertyDetailAPIEndpoint(_Base):
    model = CustomerProperty

    def get(self, request, slug, property_id):
        prop = _properties(slug).filter(pk=property_id).first()
        return Response(property_payload(prop)) if prop else _not_found("Customer property")

    def patch(self, request, slug, property_id):
        prop = _properties(slug).filter(pk=property_id).first()
        if prop is None:
            return _not_found("Customer property")
        has_values = CustomerPropertyValue.objects.filter(property=prop, customer__deleted_at__isnull=True).exists()
        prop = _save_property(prop, _body(request), partial=True, has_values=has_values)
        return Response(property_payload(prop))

    def delete(self, request, slug, property_id):
        prop = _properties(slug).filter(pk=property_id).first()
        if prop is None:
            return _not_found("Customer property")
        with transaction.atomic():
            CustomerPropertyValue.objects.filter(property=prop).delete()
            prop.options.all().delete()
            prop.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- property values ------------------------------------------------------------------------------


def _value_map(customer, user, properties):
    """Property id -> values for the given (active) properties, leaving out work items `user` can't see."""
    by_id = {str(prop.id): prop for prop in properties}
    rows = CustomerPropertyValue.objects.filter(customer=customer, property_id__in=by_id).order_by(
        "sort_order", "created_at"
    )
    issue_props = {pid for pid, prop in by_id.items() if prop.relation_type == "ISSUE"}
    issue_values = [row.value for row in rows if str(row.property_id) in issue_props]
    visible = set()
    if issue_values:
        visible = {
            str(pk)
            for pk in _visible_issues(user, customer.workspace_id)
            .filter(pk__in=issue_values)
            .values_list("pk", flat=True)
        }
    values = {}
    for row in rows:
        pid = str(row.property_id)
        if pid in issue_props and row.value not in visible:
            continue
        values.setdefault(pid, []).append(row.value)
    return values


def _replace_values(customer, prop, values, user):
    CustomerPropertyValue.objects.filter(customer=customer, property=prop).delete()
    CustomerPropertyValue.objects.bulk_create(
        [
            CustomerPropertyValue(
                workspace_id=customer.workspace_id,
                customer=customer,
                property=prop,
                value=value,
                sort_order=index,
                created_by=user,
            )
            for index, value in enumerate(values)
        ]
    )


class CustomerPropertyValueListAPIEndpoint(_Base):
    """A customer's values, as property id -> list of strings. Writes replace the named properties' values."""

    model = CustomerPropertyValue

    def get(self, request, slug, customer_id):
        customer = _customer(slug, customer_id)
        if customer is None:
            return _not_found("Customer")
        properties = CustomerProperty.objects.filter(workspace_id=customer.workspace_id, is_active=True)
        return Response(_value_map(customer, request.user, properties))

    def post(self, request, slug, customer_id):
        customer = _customer(slug, customer_id)
        if customer is None:
            return _not_found("Customer")
        given = _body(request).get("customer_property_values")
        if not isinstance(given, dict):
            raise CustomerError(
                "customer_property_values must map property ids to lists of strings", field="customer_property_values"
            )
        ids = {uuid_string(pid, "customer_property_values"): values for pid, values in given.items()}
        properties = {
            str(prop.id): prop
            for prop in CustomerProperty.objects.filter(
                workspace_id=customer.workspace_id, is_active=True, pk__in=list(ids)
            )
        }
        missing = [pid for pid in ids if pid not in properties]
        if missing:
            raise CustomerError(f"{missing[0]} isn't an active customer property", field="customer_property_values")
        visible = _visible_issues(request.user, customer.workspace_id)
        cleaned = {pid: clean_values(properties[pid], values, visible) for pid, values in ids.items()}
        with transaction.atomic():
            for pid, values in cleaned.items():
                _replace_values(customer, properties[pid], values, request.user)
        active = CustomerProperty.objects.filter(workspace_id=customer.workspace_id, is_active=True)
        return Response(_value_map(customer, request.user, active))


class CustomerPropertyValueDetailAPIEndpoint(_Base):
    model = CustomerPropertyValue

    def _target(self, slug, customer_id, property_id):
        customer = _customer(slug, customer_id)
        if customer is None:
            return None, _not_found("Customer")
        prop = CustomerProperty.objects.filter(workspace_id=customer.workspace_id, pk=property_id).first()
        if prop is None:
            return None, _not_found("Customer property")
        return (customer, prop), None

    def get(self, request, slug, customer_id, property_id):
        target, missing = self._target(slug, customer_id, property_id)
        if missing:
            return missing
        customer, prop = target
        values = _value_map(customer, request.user, [prop]) if prop.is_active else {}
        return Response({str(prop.id): values.get(str(prop.id), [])})

    def patch(self, request, slug, customer_id, property_id):
        target, missing = self._target(slug, customer_id, property_id)
        if missing:
            return missing
        customer, prop = target
        if not prop.is_active:
            raise CustomerError(f"{prop.display_name} isn't active", field="values")
        values = clean_values(prop, _body(request).get("values"), _visible_issues(request.user, customer.workspace_id))
        with transaction.atomic():
            _replace_values(customer, prop, values, request.user)
        return Response({str(prop.id): _value_map(customer, request.user, [prop]).get(str(prop.id), [])})


# --- requests -------------------------------------------------------------------------------------


def _link_issues(customer, customer_request, issue_ids, user):
    """Link the given work items (all of which the caller must see) to the customer, through
    `customer_request` when given. Re-linking is a no-op. Returns the work items."""
    issues = list(_visible_issues(user, customer.workspace_id).filter(pk__in=issue_ids).select_related("project"))
    if len(issues) != len(issue_ids):
        raise CustomerError("A work item doesn't exist or you can't see it", field="issue_ids")
    linked = set(
        CustomerRequestIssue.objects.filter(
            customer=customer, customer_request=customer_request, issue_id__in=issue_ids
        ).values_list("issue_id", flat=True)
    )
    for issue in issues:
        if issue.id not in linked:
            CustomerRequestIssue(
                workspace_id=customer.workspace_id, customer=customer, customer_request=customer_request, issue=issue
            ).save()
    return issues


def _request_work_item_ids(customer_requests, user, workspace_id):
    """Request id -> ids of the visible work items linked through it."""
    links = (
        CustomerRequestIssue.objects.filter(customer_request__in=customer_requests)
        .filter(issue_id__in=_visible_issues(user, workspace_id).values("pk"))
        .order_by("created_at")
        .values_list("customer_request_id", "issue_id")
    )
    ids = {}
    for request_id, issue_id in links:
        ids.setdefault(request_id, []).append(str(issue_id))
    return ids


def _request_payload(customer_request, user):
    ids = _request_work_item_ids([customer_request], user, customer_request.workspace_id)
    return request_payload(customer_request, ids.get(customer_request.id, []))


class CustomerRequestListCreateAPIEndpoint(_Base):
    model = CustomerRequest

    def get(self, request, slug, customer_id):
        customer = _customer(slug, customer_id)
        if customer is None:
            return _not_found("Customer")
        rows = CustomerRequest.objects.filter(customer=customer)
        query = request.GET.get("query", "").strip()
        if query:
            rows = rows.filter(name__icontains=query)

        def on_results(page):
            ids = _request_work_item_ids(page, request.user, customer.workspace_id)
            return [request_payload(row, ids.get(row.id, [])) for row in page]

        return self.paginate(request=request, queryset=rows, order_by="-created_at", on_results=on_results)

    def post(self, request, slug, customer_id):
        """work_item_ids links those work items to the customer through the new request."""
        customer = _customer(slug, customer_id)
        if customer is None:
            return _not_found("Customer")
        data = _body(request)
        issue_ids = uuid_list(data, "work_item_ids", allow_empty=True) if data.get("work_item_ids") is not None else []
        with transaction.atomic():
            customer_request = apply_request(
                CustomerRequest(workspace_id=customer.workspace_id, customer=customer), data, partial=False
            )
            customer_request.save()
            _link_issues(customer, customer_request, issue_ids, request.user)
        return Response(_request_payload(customer_request, request.user), status=status.HTTP_201_CREATED)


class CustomerRequestDetailAPIEndpoint(_Base):
    model = CustomerRequest

    def _request(self, slug, customer_id, request_id):
        return CustomerRequest.objects.filter(
            customer__workspace__slug=slug, customer_id=customer_id, customer__deleted_at__isnull=True, pk=request_id
        ).first()

    def get(self, request, slug, customer_id, request_id):
        customer_request = self._request(slug, customer_id, request_id)
        if customer_request is None:
            return _not_found("Customer request")
        return Response(_request_payload(customer_request, request.user))

    def patch(self, request, slug, customer_id, request_id):
        """work_item_ids, when given, links more work items through this request; it never unlinks."""
        customer_request = self._request(slug, customer_id, request_id)
        if customer_request is None:
            return _not_found("Customer request")
        data = _body(request)
        issue_ids = uuid_list(data, "work_item_ids", allow_empty=True) if data.get("work_item_ids") is not None else []
        with transaction.atomic():
            apply_request(customer_request, data, partial=True).save()
            _link_issues(customer_request.customer, customer_request, issue_ids, request.user)
        return Response(_request_payload(customer_request, request.user))

    def delete(self, request, slug, customer_id, request_id):
        customer_request = self._request(slug, customer_id, request_id)
        if customer_request is None:
            return _not_found("Customer request")
        with transaction.atomic():
            customer_request.issue_links.all().delete()
            customer_request.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- linked work items ----------------------------------------------------------------------------


def _request_param(request, customer):
    """The optional customer_request_id query parameter, as a request of `customer`."""
    raw = request.GET.get("customer_request_id", "").strip()
    if not raw:
        return None, None
    request_id = uuid_string(raw, "customer_request_id")
    customer_request = CustomerRequest.objects.filter(customer=customer, pk=request_id).first()
    if customer_request is None:
        return None, _not_found("Customer request")
    return customer_request, None


class CustomerWorkItemListAPIEndpoint(_Base):
    """The work items linked to a customer (not paginated, as the SDK expects), and linking more."""

    model = CustomerRequestIssue

    def get(self, request, slug, customer_id):
        customer = _customer(slug, customer_id)
        if customer is None:
            return _not_found("Customer")
        customer_request, missing = _request_param(request, customer)
        if missing:
            return missing
        links = _live_links(customer=customer)
        if customer_request is not None:
            links = links.filter(customer_request=customer_request)
        issues = (
            _visible_issues(request.user, customer.workspace_id)
            .filter(pk__in=links.values("issue_id"))
            .select_related("project")
            .order_by("created_at")
        )
        search = request.GET.get("search", "").strip()
        if search:
            match = Q(name__icontains=search) | Q(project__identifier__icontains=search)
            if search.isdigit():
                match |= Q(sequence_id=int(search))
            key = re.fullmatch(r"([A-Za-z0-9]+)-(\d+)", search)
            if key:
                match |= Q(project__identifier__iexact=key.group(1), sequence_id=int(key.group(2)))
            issues = issues.filter(match)
        return Response([work_item_payload(issue) for issue in issues])

    def post(self, request, slug, customer_id):
        """Link {"issue_ids": [...]}; the whole call is refused if any of them doesn't exist or the caller
        can't see it."""
        customer = _customer(slug, customer_id)
        if customer is None:
            return _not_found("Customer")
        customer_request, missing = _request_param(request, customer)
        if missing:
            return missing
        issue_ids = uuid_list(_body(request), "issue_ids")
        with transaction.atomic():
            issues = _link_issues(customer, customer_request, issue_ids, request.user)
        return Response(
            {
                "message": f"Linked {len(issues)} work item(s) to {customer.name}",
                "linked_issues": [linked_work_item_payload(issue) for issue in issues],
            },
            status=status.HTTP_201_CREATED,
        )


class CustomerWorkItemDetailAPIEndpoint(_Base):
    model = CustomerRequestIssue

    def delete(self, request, slug, customer_id, issue_id):
        """Unlink a work item: only the link made through customer_request_id when given, else every link
        between the customer and the work item."""
        customer = _customer(slug, customer_id)
        if customer is None:
            return _not_found("Customer")
        customer_request, missing = _request_param(request, customer)
        if missing:
            return missing
        if not _visible_issues(request.user, customer.workspace_id).filter(pk=issue_id).exists():
            return _not_found("Work item")
        links = CustomerRequestIssue.objects.filter(customer=customer, issue_id=issue_id)
        if customer_request is not None:
            links = links.filter(customer_request=customer_request)
        if not links.exists():
            return _not_found("Link")
        links.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
