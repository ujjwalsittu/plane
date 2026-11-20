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
RATE_LIMITED = "ratelimited"
NOT_FOUND = "users_not_found"


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
    values = {
        "team_id": result.get("team_id", ""),
        "team_name": result.get("team", ""),
        "bot_token_encrypted": encrypted,
        "status": "ok",
        "last_error": "",
        "deleted_at": None,
    }
    # all_objects: the workspace's unique row may be soft-deleted from before; revive it instead of inserting.
    connection = SlackConnection.all_objects.filter(workspace=workspace).first()
    if connection is None:
        connection = SlackConnection.objects.create(workspace=workspace, **values)
    else:
        if connection.team_id != values["team_id"]:
            # A different Slack team: the old links point at people in another team.
            SlackUserLink.all_objects.filter(workspace=workspace).delete()
        for field, value in values.items():
            setattr(connection, field, value)
        connection.save()
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
    """Replace the workspace's links with the people who resolve by email right now (so a changed email or
    team can't leave a link pointing at the wrong Slack user). Returns how many people are linked."""
    members = WorkspaceMember.objects.filter(workspace=connection.workspace, is_active=True).select_related("member")
    resolved = {}
    for membership in members:
        user = membership.member
        if not user.email:
            continue
        result = slack_call(connection, "users.lookupByEmail", email=user.email)
        slack_id = (result.get("user") or {}).get("id") if result.get("ok") else None
        if slack_id:
            resolved[user.id] = slack_id
        elif result.get("error") != NOT_FOUND or connection.status == "broken":
            # Only "users_not_found" says the person really isn't in Slack. Anything else (a broken token,
            # rate limiting, a network or Slack failure) leaves the pass incomplete: keep every existing link.
            return SlackUserLink.objects.filter(workspace=connection.workspace).count()
    SlackUserLink.objects.filter(workspace=connection.workspace).exclude(user_id__in=list(resolved)).delete(soft=False)
    for user_id, slack_id in resolved.items():
        SlackUserLink.objects.update_or_create(
            workspace=connection.workspace, user_id=user_id, defaults={"slack_user_id": slack_id}
        )
    return len(resolved)


def send_dm(connection, user, blocks, text):
    """Send a direct message to a linked user. Returns None when sent, otherwise Slack's error code
    (``not_linked`` when the user has no link), so callers can stop on ``ratelimited``."""
    link = SlackUserLink.objects.filter(workspace=connection.workspace, user=user).first()
    if link is None:
        return "not_linked"
    opened = slack_call(connection, "conversations.open", users=link.slack_user_id)
    channel = (opened.get("channel") or {}).get("id") if opened.get("ok") else None
    if not channel:
        return opened.get("error") or "open_failed"
    posted = slack_call(connection, "chat.postMessage", channel=channel, text=text, blocks=json.dumps(blocks))
    return None if posted.get("ok") else (posted.get("error") or "post_failed")


def dm(connection, user, blocks, text):
    """Send a direct message to a linked user. False when the user isn't linked or Slack refuses."""
    return send_dm(connection, user, blocks, text) is None


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
