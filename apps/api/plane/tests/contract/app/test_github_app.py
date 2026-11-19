# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""GitHub App integration: connecting installations, linking repositories, and webhooks."""

import hashlib
import hmac
import json

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from rest_framework import status

from plane.bgtasks import github_webhook_task
from plane.db.models import (
    GitHubInstallation,
    GitHubRepositoryLink,
    GitHubWebhookDelivery,
    Project,
    User,
    Workspace,
    WorkspaceMember,
)
from plane.utils import github_app
from plane.utils.github_integration import process_delivery, record_delivery

SECRET = "webhook-secret"


@pytest.fixture
def rsa_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return key, pem


@pytest.fixture
def app_settings(settings, rsa_key):
    settings.GITHUB_APP_ID = "4242"
    settings.GITHUB_APP_SLUG = "plane-test"
    settings.GITHUB_APP_PRIVATE_KEY = rsa_key[1]
    settings.GITHUB_APP_WEBHOOK_SECRET = SECRET
    return settings


@pytest.fixture
def github(monkeypatch):
    """Fake GitHub: installations and repositories the app can see."""
    state = {
        "installations": {
            77: {
                "id": 77,
                "app_id": 4242,
                "account": {"login": "acme", "id": 9, "type": "Organization", "avatar_url": "https://a/x.png"},
                "repository_selection": "selected",
                "suspended_at": None,
            }
        },
        "repos": {
            501: {
                "id": 501,
                "full_name": "acme/api",
                "html_url": "https://github.com/acme/api",
                "default_branch": "main",
                "private": True,
            }
        },
    }

    def get_installation(installation_id):
        if int(installation_id) not in state["installations"]:
            raise github_app.GitHubAppError("Not found", status_code=404)
        return state["installations"][int(installation_id)]

    def get_repository(installation_id, repository_id):
        if int(repository_id) not in state["repos"]:
            raise github_app.GitHubAppError("Not found on GitHub, or the app has no access to it", status_code=404)
        return state["repos"][int(repository_id)]

    monkeypatch.setattr(github_app, "get_installation", get_installation)
    monkeypatch.setattr(github_app, "get_repository", get_repository)
    monkeypatch.setattr(github_app, "installation_repositories", lambda installation_id: list(state["repos"].values()))
    return state


@pytest.fixture
def project(workspace, create_user):
    return Project.objects.create(name="API", identifier="API", workspace=workspace, created_by=create_user)


@pytest.fixture
def installation(workspace):
    return GitHubInstallation.objects.create(
        workspace=workspace, installation_id=77, account_login="acme", account_type="Organization"
    )


def _base(workspace):
    return f"/api/workspaces/{workspace.slug}/github"


# --- client helpers -------------------------------------------------------------------------------


@pytest.mark.unit
def test_private_key_formats_and_app_jwt(app_settings, rsa_key):
    key, pem = rsa_key
    escaped = pem.replace("\n", "\\n")
    import base64

    for value in (pem, escaped, base64.b64encode(pem.encode()).decode()):
        app_settings.GITHUB_APP_PRIVATE_KEY = value
        assert github_app.private_key() == pem.strip()
        assert github_app.is_configured()
        claims = jwt.decode(github_app.app_jwt(), key.public_key(), algorithms=["RS256"])
        assert claims["iss"] == "4242" and claims["exp"] - claims["iat"] <= 600
    app_settings.GITHUB_APP_PRIVATE_KEY = "not a key"
    assert not github_app.is_configured()


@pytest.mark.unit
def test_signature_check(app_settings):
    body = b'{"zen": "hi"}'
    good = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert github_app.verify_signature(body, good)
    assert not github_app.verify_signature(body + b" ", good)
    assert not github_app.verify_signature(body, "sha1=abc")
    assert not github_app.verify_signature(body, "")


# --- settings endpoints ---------------------------------------------------------------------------


@pytest.mark.contract
@pytest.mark.django_db
def test_status_when_not_configured(session_client, workspace, settings):
    settings.GITHUB_APP_ID = ""
    response = session_client.get(f"{_base(workspace)}/")
    assert response.status_code == 200
    assert response.data["configured"] is False and response.data["installations"] == []
    assert session_client.post(f"{_base(workspace)}/install-url/").status_code == 400


@pytest.mark.contract
@pytest.mark.django_db
def test_install_flow_claims_installation(session_client, workspace, create_user, app_settings, github):
    session_client.force_login(create_user)  # the setup callback is a plain Django view
    url = session_client.post(f"{_base(workspace)}/install-url/").data["url"]
    assert url.startswith("https://github.com/apps/plane-test/installations/new?state=")
    state = url.split("state=")[1]

    response = session_client.get(
        f"/api/integrations/github/setup/?installation_id=77&setup_action=install&state={state}"
    )
    assert response.status_code == 302
    assert response["Location"] == f"/{workspace.slug}/settings/github/?github_connected=1"
    installation = GitHubInstallation.objects.get(installation_id=77)
    assert installation.workspace_id == workspace.id and installation.account_login == "acme"

    # Repeating the callback (e.g. "Redirect on update") updates rather than duplicates.
    session_client.get(f"/api/integrations/github/setup/?installation_id=77&state={state}")
    assert GitHubInstallation.objects.filter(installation_id=77).count() == 1

    data = session_client.get(f"{_base(workspace)}/").data
    assert data["configured"] is True and data["app_slug"] == "plane-test"
    assert data["installations"][0]["manage_url"].endswith("/organizations/acme/settings/installations/77")


@pytest.mark.contract
@pytest.mark.django_db
def test_setup_callback_rejects_bad_state_and_other_users(
    session_client, api_client, workspace, create_user, app_settings, github
):
    session_client.force_login(create_user)
    assert session_client.get("/api/integrations/github/setup/?installation_id=77&state=forged")["Location"] == "/"
    state = github_app.make_install_state(workspace.id, create_user.id)

    other = User.objects.create(email="other@plane.so", username="other")
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=20)
    api_client.force_authenticate(user=None)
    api_client.force_login(other)
    response = api_client.get(f"/api/integrations/github/setup/?installation_id=77&state={state}")
    assert "github_error" in response["Location"]
    assert not GitHubInstallation.objects.exists()

    # An installation of a different app is refused.
    github["installations"][88] = {**github["installations"][77], "id": 88, "app_id": 1}
    response = session_client.get(f"/api/integrations/github/setup/?installation_id=88&state={state}")
    assert "github_error" in response["Location"] and not GitHubInstallation.objects.exists()


@pytest.mark.contract
@pytest.mark.django_db
def test_installation_cannot_be_claimed_by_two_workspaces(session_client, workspace, create_user, app_settings, github):
    session_client.force_login(create_user)  # the setup callback is a plain Django view
    other_ws = Workspace.objects.create(name="Other", slug="other-ws", owner=create_user)
    GitHubInstallation.objects.create(workspace=other_ws, installation_id=77, account_login="acme")
    state = github_app.make_install_state(workspace.id, create_user.id)
    response = session_client.get(f"/api/integrations/github/setup/?installation_id=77&state={state}")
    assert "github_error" in response["Location"] and "another+workspace" in response["Location"]


@pytest.mark.contract
@pytest.mark.django_db
def test_link_and_unlink_repository(session_client, workspace, project, installation, app_settings, github):
    repos = session_client.get(f"{_base(workspace)}/installations/{installation.id}/repositories/")
    assert repos.status_code == 200 and repos.data[0]["full_name"] == "acme/api"

    body = {"installation": str(installation.id), "project": str(project.id), "repository_id": 501}
    created = session_client.post(f"{_base(workspace)}/links/", body, format="json")
    assert created.status_code == status.HTTP_201_CREATED, created.data
    assert created.data["full_name"] == "acme/api" and created.data["is_private"] is True

    again = session_client.post(f"{_base(workspace)}/links/", body, format="json")
    assert again.status_code == 409

    missing = session_client.post(f"{_base(workspace)}/links/", {**body, "repository_id": 999}, format="json")
    assert missing.status_code == 404

    assert session_client.get(f"{_base(workspace)}/").data["links"][0]["project"] == str(project.id)
    assert session_client.delete(f"{_base(workspace)}/links/{created.data['id']}/").status_code == 204
    assert not GitHubRepositoryLink.objects.exists()


@pytest.mark.contract
@pytest.mark.django_db
def test_members_cannot_manage_github(api_client, workspace, app_settings):
    member = User.objects.create(email="member@plane.so", username="member")
    WorkspaceMember.objects.create(workspace=workspace, member=member, role=15)
    api_client.force_authenticate(user=member)
    assert api_client.get(f"{_base(workspace)}/").status_code == 403
    assert api_client.post(f"{_base(workspace)}/install-url/").status_code == 403


@pytest.mark.contract
@pytest.mark.django_db
def test_disconnect_removes_links(session_client, workspace, project, installation):
    GitHubRepositoryLink.objects.create(project=project, installation=installation, repository_id=501, full_name="a/b")
    assert session_client.delete(f"{_base(workspace)}/installations/{installation.id}/").status_code == 204
    assert not GitHubInstallation.objects.exists() and not GitHubRepositoryLink.objects.exists()


# --- webhooks -------------------------------------------------------------------------------------


def _post_webhook(client, event, payload, delivery="d-1", secret=SECRET):
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.generic(
        "POST",
        "/api/integrations/github/webhook/",
        body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=signature,
        HTTP_X_GITHUB_EVENT=event,
        HTTP_X_GITHUB_DELIVERY=delivery,
    )


@pytest.fixture
def run_tasks(monkeypatch):
    monkeypatch.setattr(
        github_webhook_task.process_github_delivery, "delay", lambda pk: github_webhook_task.process_github_delivery(pk)
    )


@pytest.mark.contract
@pytest.mark.django_db
def test_webhook_signature_and_idempotency(
    api_client, app_settings, installation, run_tasks, django_capture_on_commit_callbacks
):
    payload = {"action": "suspend", "installation": {"id": 77, "suspended_at": "2026-11-19T00:00:00Z"}}
    assert _post_webhook(api_client, "installation", payload, secret="wrong").status_code == 401
    assert not GitHubWebhookDelivery.objects.exists()

    with django_capture_on_commit_callbacks(execute=True):
        first = _post_webhook(api_client, "installation", payload)
    assert first.status_code == 202
    delivery = GitHubWebhookDelivery.objects.get(delivery_id="d-1")
    assert delivery.status == GitHubWebhookDelivery.PROCESSED and delivery.attempts == 1
    installation.refresh_from_db()
    assert installation.suspended_at is not None

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        again = _post_webhook(api_client, "installation", payload)
    assert again.status_code == 200 and callbacks == []
    assert GitHubWebhookDelivery.objects.count() == 1


@pytest.mark.contract
@pytest.mark.django_db
def test_webhook_rejected_when_not_configured(api_client, settings):
    settings.GITHUB_APP_WEBHOOK_SECRET = ""
    assert _post_webhook(api_client, "ping", {"zen": "x"}).status_code == 503


@pytest.mark.django_db
def test_installation_events(workspace, project, installation):
    link = GitHubRepositoryLink.objects.create(
        project=project, installation=installation, repository_id=501, full_name="acme/api"
    )

    def deliver(event, action, payload):
        process_delivery(GitHubWebhookDelivery(delivery_id="x", event=event, action=action, payload=payload))

    deliver("repository", "renamed", {"repository": {"id": 501, "full_name": "acme/core", "default_branch": "dev"}})
    link.refresh_from_db()
    assert link.full_name == "acme/core" and link.default_branch == "dev"

    deliver("installation_repositories", "removed", {"installation": {"id": 77}, "repositories_removed": [{"id": 501}]})
    assert not GitHubRepositoryLink.objects.filter(pk=link.pk).exists()

    deliver("installation", "unsuspend", {"installation": {"id": 77, "account": {"login": "acme-inc"}}})
    installation.refresh_from_db()
    assert installation.suspended_at is None and installation.account_login == "acme-inc"

    deliver("installation", "deleted", {"installation": {"id": 77}})
    assert not GitHubInstallation.objects.filter(pk=installation.pk).exists()
    # Unknown events and installations are no-ops.
    deliver("push", "", {"installation": {"id": 12345}})


@pytest.mark.django_db
def test_failed_delivery_is_retried_then_marked_failed(monkeypatch):
    delivery = GitHubWebhookDelivery.objects.create(delivery_id="f-1", event="installation", payload={})

    def boom(delivery):
        raise RuntimeError("down")

    monkeypatch.setattr(github_webhook_task, "process_delivery", boom)
    # apply() runs the task's retries inline.
    github_webhook_task.process_github_delivery.apply(args=[delivery.pk])
    delivery.refresh_from_db()
    assert delivery.status == GitHubWebhookDelivery.FAILED and delivery.attempts == github_webhook_task.MAX_ATTEMPTS
    assert "down" in delivery.error

    # A failed delivery is left alone until GitHub redelivers it, which resets it.
    github_webhook_task.process_github_delivery.apply(args=[delivery.pk])
    delivery.refresh_from_db()
    assert delivery.attempts == github_webhook_task.MAX_ATTEMPTS
    _, queue = record_delivery("f-1", "installation", {})
    delivery.refresh_from_db()
    assert queue and delivery.status == GitHubWebhookDelivery.PENDING and delivery.attempts == 0
