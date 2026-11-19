# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""GitHub App integration endpoints: workspace settings (connect accounts, link repositories),
the post-install callback GitHub redirects to, and the webhook receiver."""

# Python imports
import json
import logging
from urllib.parse import urlencode

# Django imports
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.api.views.github import WorkItemGitHubAPIEndpoint
from plane.authentication.session import BaseSessionAuthentication
from plane.bgtasks.github_webhook_task import (
    backfill_github_repository,
    import_github_issues,
    process_github_delivery,
)
from plane.db.models import GitHubInstallation, GitHubRepositoryLink, Project, Workspace, WorkspaceMember
from plane.utils import github_app, github_issue_sync
from plane.utils.github_automation import GitHubAutomationError, rules_for, rules_payload, update_rules
from plane.utils.github_integration import (
    GitHubIntegrationError,
    available_installations,
    claim_installation,
    installation_payload,
    link_payload,
    link_repository,
    record_delivery,
    remove_installation,
)

logger = logging.getLogger("plane.api")


def _error(exc):
    return Response({"error": exc.message}, status=exc.status_code)


class GitHubIntegrationEndpoint(BaseAPIView):
    """The workspace's GitHub connection: whether the server has an app, installations, links."""

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        installations = GitHubInstallation.objects.filter(workspace__slug=slug)
        links = GitHubRepositoryLink.objects.filter(workspace__slug=slug, project__archived_at__isnull=True)
        return Response(
            {
                "configured": github_app.is_configured(),
                "app_slug": settings.GITHUB_APP_SLUG or None,
                "installations": [installation_payload(i) for i in installations],
                "links": [link_payload(link) for link in links],
            }
        )


class GitHubInstallUrlEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug):
        if not github_app.is_configured():
            return Response({"error": "The GitHub App is not configured on this server"}, status=400)
        workspace = Workspace.objects.get(slug=slug)
        state = github_app.make_install_state(workspace.id, request.user.id)
        return Response({"url": github_app.install_url(state)})


class GitHubInstallationListEndpoint(BaseAPIView):
    """Installations of the app not connected to any workspace yet, and connecting one directly (for
    when the app was installed from GitHub rather than through Plane's install link)."""

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        try:
            return Response(available_installations())
        except github_app.GitHubAppError as exc:
            return _error(exc)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        try:
            installation = claim_installation(workspace, request.data.get("installation_id"))
        except (GitHubIntegrationError, github_app.GitHubAppError) as exc:
            return _error(exc)
        return Response(installation_payload(installation), status=status.HTTP_201_CREATED)


class GitHubInstallationDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def delete(self, request, slug, pk):
        installation = GitHubInstallation.objects.filter(workspace__slug=slug, pk=pk).first()
        if not installation:
            return Response({"error": "Installation not found"}, status=status.HTTP_404_NOT_FOUND)
        remove_installation(installation)
        return Response(status=status.HTTP_204_NO_CONTENT)


class GitHubInstallationRepositoriesEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug, pk):
        installation = GitHubInstallation.objects.filter(workspace__slug=slug, pk=pk).first()
        if not installation:
            return Response({"error": "Installation not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            repos = github_app.installation_repositories(installation.installation_id)
        except github_app.GitHubAppError as exc:
            return _error(exc)
        return Response([github_app.repository_summary(repo) for repo in repos])


class GitHubRepositoryLinkListEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        try:
            link = link_repository(workspace, request.data)
        except (GitHubIntegrationError, github_app.GitHubAppError) as exc:
            return _error(exc)
        return Response(link_payload(link), status=status.HTTP_201_CREATED)


class GitHubRepositoryLinkDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def patch(self, request, slug, pk):
        """Turn two-way issue sync on or off; turning it on imports the open issues."""
        link = GitHubRepositoryLink.objects.filter(workspace__slug=slug, pk=pk).first()
        if not link:
            return Response({"error": "Link not found"}, status=status.HTTP_404_NOT_FOUND)
        value = request.data.get("issue_sync") if isinstance(request.data, dict) else None
        if not isinstance(value, bool):
            return Response({"error": "issue_sync must be true or false"}, status=status.HTTP_400_BAD_REQUEST)
        if value and link.installation.suspended_at:
            return Response({"error": "That installation is suspended on GitHub"}, status=status.HTTP_400_BAD_REQUEST)
        if value and not link.issue_sync:
            try:
                repo = github_app.get_repository(link.installation.installation_id, link.repository_id)
            except github_app.GitHubAppError as exc:
                return _error(exc)
            if not repo.get("has_issues", True):
                return Response(
                    {"error": f"Issues are turned off for {link.full_name} on GitHub (repository Settings → Features)"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        turned_on = value and not link.issue_sync
        link.issue_sync = value
        link.save(update_fields=["issue_sync", "updated_at"])
        if turned_on:
            transaction.on_commit(lambda: import_github_issues.delay(str(link.id)))
        return Response(link_payload(link))

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def delete(self, request, slug, pk):
        link = GitHubRepositoryLink.objects.filter(workspace__slug=slug, pk=pk).first()
        if not link:
            return Response({"error": "Link not found"}, status=status.HTTP_404_NOT_FOUND)
        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class GitHubRepositoryLinkSyncEndpoint(BaseAPIView):
    """Re-reads the repository's open pull requests and links the work items they mention."""

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug, pk):
        link = GitHubRepositoryLink.objects.filter(workspace__slug=slug, pk=pk).first()
        if not link:
            return Response({"error": "Link not found"}, status=status.HTTP_404_NOT_FOUND)
        backfill_github_repository.delay(str(link.id))
        return Response(status=status.HTTP_202_ACCEPTED)


class IssueGitHubEndpoint(WorkItemGitHubAPIEndpoint):
    """The web app's view of a work item's pull requests, branches and commits."""

    authentication_classes = [BaseSessionAuthentication]

    def get_throttles(self):
        return []


class GitHubAutomationListEndpoint(BaseAPIView):
    """Pull request automation rules for each project that has a linked repository."""

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        project_ids = (
            GitHubRepositoryLink.objects.filter(workspace__slug=slug, project__archived_at__isnull=True)
            .values_list("project_id", flat=True)
            .distinct()
        )
        projects = Project.objects.filter(pk__in=list(project_ids)).order_by("name")
        return Response([rules_payload(rules_for(project)) for project in projects])


class GitHubAutomationDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def patch(self, request, slug, project_id):
        project = Project.objects.filter(workspace__slug=slug, pk=project_id).first()
        if not project:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            rules = update_rules(project, request.data if isinstance(request.data, dict) else {})
        except GitHubAutomationError as exc:
            return _error(exc)
        return Response(rules_payload(rules))


class GitHubUserMappingEndpoint(BaseAPIView):
    """GitHub logins of workspace members, used to sync assignees."""

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        return Response(github_issue_sync.mappings_payload(workspace.id))

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def put(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        data = request.data if isinstance(request.data, dict) else {}
        user_id = data.get("user")
        if not WorkspaceMember.objects.filter(workspace=workspace, member_id=user_id, is_active=True).exists():
            return Response(
                {"error": "That user is not a member of this workspace"}, status=status.HTTP_400_BAD_REQUEST
            )
        github_issue_sync.set_mapping(workspace, user_id, data.get("github_login"))
        return Response(github_issue_sync.mappings_payload(workspace.id))


def _settings_redirect(slug, **params):
    query = f"?{urlencode(params)}" if params else ""
    return HttpResponseRedirect(f"/{slug}/settings/github/{query}")


class GitHubSetupCallbackView(View):
    """GitHub's "Setup URL": the browser lands here after installing or updating the app."""

    def get(self, request):
        state = request.GET.get("state", "")
        installation_id = request.GET.get("installation_id", "")
        try:
            workspace_id, user_id = github_app.read_install_state(state)
        except signing.BadSignature:
            # Installed or reconfigured from GitHub directly; nothing to tie it to.
            return HttpResponseRedirect("/")
        workspace = Workspace.objects.filter(id=workspace_id).first()
        if not workspace:
            return HttpResponseRedirect("/")
        user = request.user
        if not user.is_authenticated or str(user.id) != user_id:
            return _settings_redirect(workspace.slug, github_error="Sign in as the user who started the connection")
        if not WorkspaceMember.objects.filter(
            workspace=workspace, member=user, role=ROLE.ADMIN.value, is_active=True
        ).exists():
            return _settings_redirect(workspace.slug, github_error="Only workspace admins can connect GitHub")
        if not installation_id:
            # e.g. setup_action=request: an org owner has to approve the installation first.
            return _settings_redirect(workspace.slug, github_error="GitHub did not report an installation yet")
        try:
            claim_installation(workspace, installation_id)
        except (GitHubIntegrationError, github_app.GitHubAppError) as exc:
            return _settings_redirect(workspace.slug, github_error=exc.message)
        return _settings_redirect(workspace.slug, github_connected="1")


@method_decorator(csrf_exempt, name="dispatch")
class GitHubWebhookView(View):
    """Receives GitHub App webhooks: checks the signature, stores the delivery once, and hands it
    to the worker. Answers quickly; GitHub gives up after 10 seconds."""

    def post(self, request):
        if not github_app.is_configured():
            return HttpResponse("GitHub App not configured", status=503)
        if not github_app.verify_signature(request.body, request.headers.get("X-Hub-Signature-256", "")):
            return HttpResponse("Invalid signature", status=401)
        delivery_id = request.headers.get("X-GitHub-Delivery", "")
        event = request.headers.get("X-GitHub-Event", "")
        if not delivery_id or not event:
            return HttpResponse("Missing delivery headers", status=400)
        try:
            payload = json.loads(request.body or b"{}")
        except ValueError:
            return HttpResponse("Body is not JSON", status=400)
        if not isinstance(payload, dict):
            return HttpResponse("Body is not a JSON object", status=400)
        delivery, queue = record_delivery(delivery_id[:100], event[:100], payload)
        if queue:
            transaction.on_commit(lambda: process_github_delivery.delay(delivery.pk))
        return HttpResponse(status=202 if queue else 200)
