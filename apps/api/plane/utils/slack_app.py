# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""A workspace's internal Slack app: connect with a bot token, link people by email, call the Web API,
send DMs and verify the signature on requests Slack sends us. The token is never logged or returned."""

# Python imports
import hashlib
import hmac
import json
import time

# Django imports
from django.conf import settings

# Third party imports
import requests

# Module imports
from plane.db.models import SlackConnection, SlackUserLink, WorkspaceMember
from plane.license.utils.encryption import decrypt_data, encrypt_data

SLACK_API = "https://slack.com/api"
TIMEOUT = 10
SIGNATURE_MAX_AGE = 60 * 5
# Errors that mean the token will not work again until someone reconnects.
BROKEN_ERRORS = {"invalid_auth", "token_revoked", "account_inactive"}


class SlackError(Exception):
    pass


def _post(method, token, params):
    try:
        response = requests.post(
            f"{SLACK_API}/{method}",
            data=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )
        data = response.json()
    except (requests.RequestException, ValueError):
        return {"ok": False, "error": "request_failed"}
    return data if isinstance(data, dict) else {"ok": False, "error": "bad_response"}


def _mark_broken(connection, error):
    connection.status = "broken"
    connection.last_error = str(error)[:255]
    connection.save(update_fields=["status", "last_error", "updated_at"])


def connect(workspace, bot_token):
    """Verify the token with ``auth.test`` and store it encrypted. Raises SlackError when Slack refuses it."""
    result = _post("auth.test", bot_token, {})
    if not result.get("ok"):
        raise SlackError(result.get("error") or "auth_failed")
    encrypted = encrypt_data(bot_token)
    if not encrypted:
        raise SlackError("encryption_failed")
    connection, _ = SlackConnection.objects.update_or_create(
        workspace=workspace,
        defaults={
            "team_id": result.get("team_id", ""),
            "team_name": result.get("team", ""),
            "bot_token_encrypted": encrypted,
            "status": "ok",
            "last_error": "",
        },
    )
    return connection


def bot_token(connection):
    """The decrypted token, or None (and the connection marked broken) when it can't be read, for example
    after SECRET_KEY changed."""
    try:
        token = decrypt_data(connection.bot_token_encrypted)
    except Exception:
        token = ""
    if not token:
        _mark_broken(connection, "reconnect")
        return None
    return token


def slack_call(connection, method, **params):
    token = bot_token(connection)
    if token is None:
        return {"ok": False, "error": "reconnect"}
    result = _post(method, token, params)
    if not result.get("ok") and result.get("error") in BROKEN_ERRORS:
        _mark_broken(connection, result["error"])
    return result


def link_users(connection):
    """Match active workspace members to Slack users by email. Returns how many people are linked."""
    members = WorkspaceMember.objects.filter(workspace=connection.workspace, is_active=True).select_related("member")
    for membership in members:
        user = membership.member
        if not user.email:
            continue
        result = slack_call(connection, "users.lookupByEmail", email=user.email)
        if connection.status == "broken":
            break
        slack_id = (result.get("user") or {}).get("id") if result.get("ok") else None
        if slack_id:
            SlackUserLink.objects.update_or_create(
                workspace=connection.workspace, user=user, defaults={"slack_user_id": slack_id}
            )
    return SlackUserLink.objects.filter(workspace=connection.workspace, user__in=[m.member_id for m in members]).count()


def dm(connection, user, blocks, text):
    """Send a direct message to a linked user. False when the user isn't linked or Slack refuses."""
    link = SlackUserLink.objects.filter(workspace=connection.workspace, user=user).first()
    if link is None:
        return False
    opened = slack_call(connection, "conversations.open", users=link.slack_user_id)
    channel = (opened.get("channel") or {}).get("id") if opened.get("ok") else None
    if not channel:
        return False
    posted = slack_call(connection, "chat.postMessage", channel=channel, text=text, blocks=json.dumps(blocks))
    return bool(posted.get("ok"))


def verify_signature(headers, body):
    """Slack's v0 signature: HMAC-SHA256 of ``v0:{timestamp}:{body}``, no older than five minutes."""
    secret = settings.SLACK_SIGNING_SECRET
    timestamp = headers.get("X-Slack-Request-Timestamp", "")
    signature = headers.get("X-Slack-Signature", "")
    if not secret or not timestamp or not signature:
        return False
    try:
        if abs(time.time() - int(timestamp)) > SIGNATURE_MAX_AGE:
            return False
    except ValueError:
        return False
    expected = "v0=" + hmac.new(secret.encode(), f"v0:{timestamp}:".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
