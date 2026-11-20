# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Slack's interactivity endpoint: a person answers a decision by clicking a button in their DM."""

# Python imports
import json
import logging
import re
import uuid
from urllib.parse import parse_qs

# Django imports
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

# Third party imports
import requests

# Module imports
from plane.bgtasks.supervision_task import escape_mrkdwn, web_url
from plane.db.models import DecisionRequest, SlackConnection, SlackUserLink
from plane.utils import slack_app
from plane.utils.decisions import answer_decision
from plane.utils.supervision import SupervisionError

logger = logging.getLogger("plane.api")

ACTION_RE = re.compile(r"^decision:([0-9a-fA-F-]{36}):(\d{1,3})$")
RESPONSE_URL_PREFIX = "https://hooks.slack.com/"
RESPONSE_TIMEOUT = 2.5  # Slack wants our answer to the click within 3 seconds


def _reply(response_url, body):
    """Update the message through the click's response_url. Failing to reach Slack must not fail the click."""
    if not isinstance(response_url, str) or not response_url.startswith(RESPONSE_URL_PREFIX):
        return
    try:
        requests.post(response_url, json=body, timeout=RESPONSE_TIMEOUT)
    except requests.RequestException:
        logger.warning("Could not post to the Slack response_url")


def _ephemeral(text):
    return {"response_type": "ephemeral", "replace_original": False, "text": text}


def _replace(decision, text):
    return {
        "replace_original": True,
        "text": text,
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": escape_mrkdwn(decision.question)}},
            {"type": "section", "text": {"type": "mrkdwn", "text": escape_mrkdwn(text)}},
        ],
    }


@method_decorator(csrf_exempt, name="dispatch")
class SlackInteractivityView(View):
    """No session: Slack calls this, and the signed body is the only credential. The signature is checked
    over the raw bytes before anything is parsed."""

    def post(self, request):
        if not slack_app.verify_signature(request.headers, request.body):
            return HttpResponse("Invalid signature", status=401)
        try:
            raw = parse_qs(request.body.decode("utf-8")).get("payload", [""])[0]
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return HttpResponse("Bad payload", status=400)

        actions = payload.get("actions")
        action = actions[0] if isinstance(actions, list) and actions and isinstance(actions[0], dict) else {}
        match = ACTION_RE.match(str(action.get("action_id") or ""))
        if payload.get("type") != "block_actions" or not match:
            return HttpResponse(status=200)  # not one of ours
        response_url = payload.get("response_url")
        try:
            decision_id = uuid.UUID(match.group(1))
        except ValueError:
            _reply(response_url, _ephemeral("Unknown decision"))
            return HttpResponse(status=200)
        decision = DecisionRequest.objects.filter(pk=decision_id).select_related("issue").first()
        team_id = (payload.get("team") or {}).get("id") or (payload.get("user") or {}).get("team_id")
        slack_user = (payload.get("user") or {}).get("id")
        # The decision's own workspace must be the one connected to the Slack team that sent this.
        connection = (
            SlackConnection.objects.filter(workspace_id=decision.workspace_id, team_id=team_id or "").first()
            if decision
            else None
        )
        if decision is None or connection is None:
            return HttpResponse(status=200)

        link = (
            SlackUserLink.objects.filter(workspace_id=decision.workspace_id, slack_user_id=slack_user or "")
            .select_related("user")
            .first()
        )
        if link is None:
            _reply(response_url, _ephemeral("Link your account first: your Slack email must match your Plane email."))
            return HttpResponse(status=200)

        index = int(match.group(2))
        if index >= len(decision.options):
            _reply(response_url, _ephemeral("That option is no longer available."))
            return HttpResponse(status=200)

        try:
            answered = answer_decision(decision, link.user, decision.options[index], origin=web_url())
        except SupervisionError as exc:
            if exc.status_code == 409:
                decision.refresh_from_db()
                text = "Already answered" + (f": {decision.answer}" if decision.answer else "")
                _reply(response_url, _replace(decision, text))
            else:
                _reply(response_url, _ephemeral(exc.message))
            return HttpResponse(status=200)
        _reply(response_url, _replace(answered, f"Answered: {answered.answer}"))
        return HttpResponse(status=200)
