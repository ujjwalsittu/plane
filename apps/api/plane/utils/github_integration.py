# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The GitHub integration's data side: claiming installations for a workspace, linking
repositories to projects, and applying webhook deliveries."""

# Django imports
from django.conf import settings
from django.db import transaction
from django.utils import timezone

# Module imports
from plane.db.models import GitHubInstallation, GitHubRepositoryLink, GitHubWebhookDelivery, Project
from plane.utils import github_app


class GitHubIntegrationError(ValueError):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _iso(value):
    return value.isoformat() if value else None


# --- payloads -------------------------------------------------------------------------------------


def installation_payload(installation):
    return {
        "id": str(installation.id),
        "installation_id": installation.installation_id,
        "account_login": installation.account_login,
        "account_type": installation.account_type,
        "account_avatar_url": installation.account_avatar_url,
        "repository_selection": installation.repository_selection,
        "suspended_at": _iso(installation.suspended_at),
        "manage_url": (
            f"https://github.com/organizations/{installation.account_login}/settings/installations/"
            f"{installation.installation_id}"
            if installation.account_type == "Organization"
            else f"https://github.com/settings/installations/{installation.installation_id}"
        ),
        "created_at": _iso(installation.created_at),
    }


def link_payload(link):
    return {
        "id": str(link.id),
        "installation": str(link.installation_id),
        "project": str(link.project_id),
        "repository_id": link.repository_id,
        "full_name": link.full_name,
        "html_url": link.html_url,
        "default_branch": link.default_branch,
        "is_private": link.is_private,
        "created_at": _iso(link.created_at),
    }


# --- installations --------------------------------------------------------------------------------


def _apply_installation_data(installation, data):
    account = data.get("account") or {}
    installation.account_login = account.get("login") or installation.account_login or ""
    installation.account_id = account.get("id") or installation.account_id
    installation.account_type = account.get("type") or installation.account_type or ""
    installation.account_avatar_url = account.get("avatar_url") or installation.account_avatar_url or ""
    installation.repository_selection = data.get("repository_selection") or installation.repository_selection or ""
    installation.suspended_at = data.get("suspended_at") or None


def claim_installation(workspace, installation_id):
    """Connect an installation (checked with GitHub) to ``workspace``."""
    try:
        installation_id = int(installation_id)
    except (TypeError, ValueError):
        raise GitHubIntegrationError("installation_id is not a number")
    data = github_app.get_installation(installation_id)
    if str(data.get("app_id")) != str(settings.GITHUB_APP_ID):
        raise GitHubIntegrationError("That installation belongs to another GitHub App", status_code=403)
    existing = GitHubInstallation.objects.filter(installation_id=installation_id).first()
    if existing and existing.workspace_id != workspace.id:
        raise GitHubIntegrationError("That GitHub account is already connected to another workspace", 409)
    installation = existing or GitHubInstallation(workspace=workspace, installation_id=installation_id)
    _apply_installation_data(installation, data)
    installation.save()
    return installation


@transaction.atomic
def remove_installation(installation):
    # Soft deletion doesn't cascade right away; drop the links now.
    installation.repository_links.all().delete()
    github_app.forget_installation_token(installation.installation_id)
    installation.delete()


# --- repository links -----------------------------------------------------------------------------


def link_repository(workspace, data):
    installation = GitHubInstallation.objects.filter(workspace=workspace, id=data.get("installation")).first()
    if not installation:
        raise GitHubIntegrationError("Unknown installation for this workspace", status_code=404)
    if installation.suspended_at:
        raise GitHubIntegrationError("That installation is suspended on GitHub")
    project = Project.objects.filter(workspace=workspace, id=data.get("project")).first()
    if not project:
        raise GitHubIntegrationError("Unknown project for this workspace", status_code=404)
    try:
        repository_id = int(data.get("repository_id"))
    except (TypeError, ValueError):
        raise GitHubIntegrationError("repository_id is required")
    if GitHubRepositoryLink.objects.filter(project=project, repository_id=repository_id).exists():
        raise GitHubIntegrationError("That repository is already linked to this project", status_code=409)
    # Confirms the installation can see the repository.
    repo = github_app.repository_summary(github_app.get_repository(installation.installation_id, repository_id))
    return GitHubRepositoryLink.objects.create(
        project=project,
        installation=installation,
        repository_id=repo["id"],
        full_name=repo["full_name"],
        html_url=repo["html_url"],
        default_branch=repo["default_branch"],
        is_private=repo["private"],
    )


# --- webhook deliveries ---------------------------------------------------------------------------


def _installation_event(delivery, payload):
    data = payload.get("installation") or {}
    installation = GitHubInstallation.objects.filter(installation_id=data.get("id")).first()
    if not installation:
        return
    if delivery.action == "deleted":
        remove_installation(installation)
        return
    _apply_installation_data(installation, data)
    if delivery.action == "new_permissions_accepted":
        github_app.forget_installation_token(installation.installation_id)
    if delivery.action == "suspend":
        installation.suspended_at = installation.suspended_at or timezone.now()
    elif delivery.action == "unsuspend":
        installation.suspended_at = None
    installation.save()


def _installation_repositories_event(delivery, payload):
    installation = GitHubInstallation.objects.filter(
        installation_id=(payload.get("installation") or {}).get("id")
    ).first()
    if not installation:
        return
    installation.repository_selection = payload.get("repository_selection") or installation.repository_selection
    installation.save(update_fields=["repository_selection", "updated_at"])
    removed = [repo["id"] for repo in payload.get("repositories_removed") or []]
    if removed:
        GitHubRepositoryLink.objects.filter(installation=installation, repository_id__in=removed).delete()


def _repository_event(delivery, payload):
    repo = payload.get("repository") or {}
    links = GitHubRepositoryLink.objects.filter(repository_id=repo.get("id"))
    if delivery.action == "deleted":
        links.delete()
        return
    if repo.get("full_name"):
        links.update(
            full_name=repo["full_name"],
            html_url=repo.get("html_url", ""),
            default_branch=repo.get("default_branch", ""),
            is_private=bool(repo.get("private")),
            updated_at=timezone.now(),
        )


EVENT_HANDLERS = {
    "installation": _installation_event,
    "installation_repositories": _installation_repositories_event,
    "repository": _repository_event,
}


def process_delivery(delivery):
    """Apply one delivery; events without a handler are recorded and marked processed."""
    handler = EVENT_HANDLERS.get(delivery.event)
    if handler:
        handler(delivery, delivery.payload or {})


def record_delivery(delivery_id, event, payload):
    """Store a delivery; returns (delivery, created). A redelivery of a processed one is not
    reprocessed, a failed one is reset to pending so it is tried again."""
    installation_id = (payload.get("installation") or {}).get("id")
    delivery, created = GitHubWebhookDelivery.objects.get_or_create(
        delivery_id=delivery_id,
        defaults={
            "event": event,
            "action": str(payload.get("action") or "")[:100],
            "installation_id": installation_id,
            "payload": payload,
        },
    )
    if not created and delivery.status == GitHubWebhookDelivery.FAILED:
        delivery.status = GitHubWebhookDelivery.PENDING
        delivery.attempts = 0
        delivery.save(update_fields=["status", "attempts"])
        return delivery, True
    return delivery, created
