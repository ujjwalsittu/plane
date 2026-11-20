# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Slack messages for supervision: the daily brief, milestone alerts and decision requests."""

# Python imports
import uuid
from datetime import date, timedelta

# Django imports
from django.conf import settings
from django.utils import timezone

# Third party imports
from celery import shared_task

# Module imports
from plane.db.models import BriefVisit, DecisionRequest, Notification, SlackConnection, SlackUserLink
from plane.utils import slack_app
from plane.utils.brief import _milestones_due, brief_for, zone_for
from plane.utils.exception_logger import log_exception

BRIEF_HOUR = 9
TOP = 5
MAX_NAME = 120
MAX_BUTTON = 75
RATE_LIMITED = "ratelimited"


def escape_mrkdwn(value):
    """Slack mrkdwn only treats ``&``, ``<`` and ``>`` as special in user text."""
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def web_url():
    return (settings.WEB_URL or settings.APP_BASE_URL or "").rstrip("/")


def _item_url(slug, identifier):
    return f"{web_url()}/{slug}/browse/{identifier}/"


def _brief_url(slug):
    return f"{web_url()}/{slug}/brief/"


def _short(value, limit=MAX_NAME):
    value = str(value or "")
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _open_brief_button(slug):
    return {
        "type": "actions",
        "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Open Brief"}, "url": _brief_url(slug)}],
    }


def _item_line(slug, issue, suffix=""):
    link = f"<{_item_url(slug, issue['identifier'])}|{issue['identifier']}>"
    return f"• {link} {escape_mrkdwn(_short(issue['name']))}{suffix}"


def _list_section(title, count, lines):
    more = f"\n_and {count - len(lines)} more_" if count > len(lines) else ""
    return _section(f"*{title} ({count})*\n" + "\n".join(lines) + more)


def build_brief_blocks(slug, brief):
    """Slack blocks for a brief: counts, then the top five of each list. Empty when there is nothing to say."""
    needs = brief["needs_me"]
    blocked = brief["blocked"]
    done = [item for group in brief["done"] for item in group["items"]]
    milestones = brief["milestones_due"]
    if not (needs or blocked or done or milestones):
        return []
    blocks = [
        _section(
            f"*Your Plane brief*\n{len(needs)} need you · {len(blocked)} blocked · {len(done)} done · "
            f"{len(milestones)} milestones due"
        )
    ]
    if needs:
        lines = [_item_line(slug, row["issue"], " _(overdue)_" if row["overdue"] else "") for row in needs[:TOP]]
        blocks.append(_list_section("Needs you", len(needs), lines))
    if blocked:
        lines = [_item_line(slug, row["issue"]) for row in blocked[:TOP]]
        blocks.append(_list_section("Blocked", len(blocked), lines))
    if done:
        lines = [_item_line(slug, item["issue"]) for item in done[:TOP]]
        blocks.append(_list_section("Done since you last looked", len(done), lines))
    if milestones:
        lines = [
            f"• *{escape_mrkdwn(_short(m['title']))}* ({m['project_identifier']}) {m['target_date']}: {m['open']} open"
            for m in milestones[:TOP]
        ]
        blocks.append(_list_section("Milestones due", len(milestones), lines))
    blocks.append(_open_brief_button(slug))
    return blocks


def _claim(workspace_id, user, today):
    """Mark the brief as sent for ``today`` before sending, so two runs can't both send it. Returns the
    previous value to restore when the send fails, or False when it was already sent. Only
    ``slack_sent_on`` is written: the last-seen time that drives "done since" is left alone."""
    visit, _ = BriefVisit.objects.get_or_create(workspace_id=workspace_id, user=user)
    claimed = BriefVisit.objects.filter(pk=visit.pk).exclude(slack_sent_on=today).update(slack_sent_on=today)
    return (visit.slack_sent_on,) if claimed else False


def _release(workspace_id, user, today, previous):
    BriefVisit.objects.filter(workspace_id=workspace_id, user=user, slack_sent_on=today).update(slack_sent_on=previous)


def _send_connection_briefs(connection, now=None):
    now = now or timezone.now()
    slug = connection.workspace.slug
    links = SlackUserLink.objects.filter(workspace_id=connection.workspace_id).select_related("user")
    for link in links:
        user = link.user
        if not user.is_active:
            continue
        local = now.astimezone(zone_for(user))
        if local.hour != BRIEF_HOUR:
            continue
        today = local.date()
        previous = _claim(connection.workspace_id, user, today)
        if previous is False:
            continue
        try:
            # Nothing to report today: stays marked, so it isn't rebuilt for the rest of the hour.
            blocks = build_brief_blocks(slug, brief_for(connection.workspace_id, user))
            error = slack_app.send_dm(connection, user, blocks, "Your Plane brief") if blocks else None
        except Exception as exc:  # one person's failure must not stop the rest; never log tokens
            log_exception(exc)
            error = "exception"
        if error is not None:
            _release(connection.workspace_id, user, today, previous[0])
        if error == RATE_LIMITED or connection.status == "broken":
            return  # the rest get it next hour


@shared_task
def send_slack_briefs():
    """Hourly: DM each linked person their brief once, when it is 09:xx where they are."""
    for connection in SlackConnection.objects.filter(status="ok").select_related("workspace"):
        try:
            _send_connection_briefs(connection)
        except Exception as exc:  # one workspace must not stop the others; never log tokens
            log_exception(exc)


def _due_phrase(target, today):
    days = (target - today).days
    if days < 0:
        return f"overdue by {-days} day{'s' if days != -1 else ''}"
    return "due today" if days == 0 else "due tomorrow"


def _send_connection_milestone_alerts(connection, now):
    slug = connection.workspace.slug
    links = SlackUserLink.objects.filter(workspace_id=connection.workspace_id).select_related("user")
    for link in links:
        user = link.user
        if not user.is_active:
            continue
        today = now.astimezone(zone_for(user)).date()
        horizon = (today + timedelta(days=1)).isoformat()
        due = [m for m in _milestones_due(connection.workspace_id, user, today) if m["target_date"] <= horizon]
        if not due:
            continue
        lines = []
        for m in due[:TOP]:
            when = _due_phrase(date.fromisoformat(m["target_date"]), today)
            mine = f", {m['assigned_to_me_open']} yours" if m["assigned_to_me_open"] else ""
            lines.append(
                f"• *{escape_mrkdwn(_short(m['title']))}* ({m['project_identifier']}) {when}: "
                f"{m['open']} of {m['total']} open{mine}"
            )
        blocks = [_list_section("Milestones needing attention", len(due), lines), _open_brief_button(slug)]
        error = slack_app.send_dm(connection, user, blocks, "Milestones due soon")
        if error == RATE_LIMITED or connection.status == "broken":
            return


@shared_task
def send_milestone_alerts():
    """Daily: DM people with open items in milestones due tomorrow or already overdue."""
    now = timezone.now()
    for connection in SlackConnection.objects.filter(status="ok").select_related("workspace"):
        try:
            _send_connection_milestone_alerts(connection, now)
        except Exception as exc:
            log_exception(exc)


def _decision_blocks(decision):
    issue = decision.issue
    slug = decision.workspace.slug
    identifier = f"{issue.project.identifier}-{issue.sequence_id}"
    url = _item_url(slug, identifier)
    blocks = [
        _section(
            f"*Decision needed* on <{url}|{identifier}> {escape_mrkdwn(_short(issue.name))}\n"
            f"{escape_mrkdwn(decision.question)}"
        )
    ]
    if decision.options:
        elements = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": _short(option, MAX_BUTTON)},
                "action_id": f"decision:{decision.id}:{index}",
            }
            for index, option in enumerate(decision.options)
        ]
    else:
        elements = [{"type": "button", "text": {"type": "plain_text", "text": "Answer in Plane"}, "url": url}]
    blocks.append({"type": "actions", "elements": elements})
    return blocks


def _create_decision_notification(decision):
    if Notification.objects.filter(
        receiver_id=decision.asked_user_id, entity_name="decision", data__decision__id=str(decision.id)
    ).exists():
        return
    issue = decision.issue
    Notification.objects.create(
        workspace_id=decision.workspace_id,
        project_id=decision.project_id,
        sender="decision",
        triggered_by_id=decision.created_by_id,
        receiver_id=decision.asked_user_id,
        entity_identifier=decision.issue_id,
        entity_name="decision",
        title=decision.question[:500],
        data={
            "decision": {"id": str(decision.id), "question": decision.question, "options": decision.options},
            "issue": {
                "id": str(issue.id),
                "name": issue.name,
                "identifier": issue.project.identifier,
                "sequence_id": issue.sequence_id,
            },
        },
    )


@shared_task
def notify_decision(decision_id):
    """Tell the asked person: an inbox row, and a Slack DM with a button per option when connected."""
    try:
        pk = uuid.UUID(str(decision_id))
    except ValueError:
        return
    decision = (
        DecisionRequest.objects.filter(pk=pk)
        .select_related("issue", "issue__project", "workspace", "asked_user", "created_by")
        .first()
    )
    if decision is None or decision.status != "open":
        return
    _create_decision_notification(decision)
    connection = SlackConnection.objects.filter(workspace_id=decision.workspace_id, status="ok").first()
    if connection is None:
        return
    try:
        slack_app.send_dm(connection, decision.asked_user, _decision_blocks(decision), "Decision needed")
    except Exception as exc:
        log_exception(exc)
