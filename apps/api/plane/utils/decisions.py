# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Decision requests: an agent asks a person, the answer lands on the work item as a comment."""

import json
from html import escape

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from plane.utils.supervision import SupervisionError, work_item_payload

MAX_OPTIONS = 10
MAX_OPTION_LENGTH = 255
MAX_ANSWER_LENGTH = 5000


def on_decision_created(decision):
    """Called right after a decision is created. Does nothing yet; later work notifies the asked person."""


def _person(user):
    if user is None:
        return None
    return {"id": str(user.id), "display_name": user.display_name or user.email.split("@")[0]}


def decision_payload(decision, issue=None):
    payload = {
        "id": str(decision.id),
        "issue_id": str(decision.issue_id),
        "question": decision.question,
        "options": decision.options,
        "status": decision.status,
        "answer": decision.answer,
        "asked_user": _person(decision.asked_user),
        "requested_by": _person(decision.created_by),
        "answered_by": str(decision.answered_by_id) if decision.answered_by_id else None,
        "answered_at": decision.answered_at.isoformat() if decision.answered_at else None,
        "created_at": decision.created_at.isoformat(),
        "source": decision.source,
    }
    if issue is not None:
        payload["issue"] = work_item_payload(issue)
    return payload


def _clean_options(raw):
    if raw in (None, ""):
        return []
    if not isinstance(raw, list) or len(raw) > MAX_OPTIONS:
        raise SupervisionError(f"options must be a list of at most {MAX_OPTIONS} strings", field="options")
    options = []
    for option in raw:
        if not isinstance(option, str) or not option.strip() or len(option.strip()) > MAX_OPTION_LENGTH:
            raise SupervisionError(
                f"Each option must be a non-empty string of at most {MAX_OPTION_LENGTH} characters", field="options"
            )
        options.append(option.strip())
    return options


def create_decision(issue, data, actor, source):
    """Ask a project member for a decision on `issue`."""
    import uuid

    from plane.db.models import DecisionRequest, ProjectMember

    question = data.get("question")
    question = question.strip() if isinstance(question, str) else ""
    if not question:
        raise SupervisionError("question is required", field="question")
    options = _clean_options(data.get("options"))
    try:
        asked_id = uuid.UUID(str(data.get("asked_user")))
    except ValueError:
        raise SupervisionError("asked_user must be a user id", field="asked_user")
    # Guests cannot answer (writes need member or admin), so they cannot be asked.
    if not ProjectMember.objects.filter(
        project_id=issue.project_id, member_id=asked_id, is_active=True, role__gte=15
    ).exists():
        raise SupervisionError("asked_user must be an active member of the project", field="asked_user")

    decision = DecisionRequest.objects.create(
        issue=issue,
        project_id=issue.project_id,
        workspace_id=issue.workspace_id,
        asked_user_id=asked_id,
        question=question,
        options=options,
        source=source,
        created_by=actor,
    )
    # Looked up at call time so tests can patch it; fires only for committed rows.
    transaction.on_commit(lambda: on_decision_created(decision))
    return decision


def answer_decision(decision, user, answer, source="app"):
    """Record `user`'s answer and write it onto the work item as a comment."""
    from plane.db.models import DecisionRequest, IssueActivity, IssueComment

    if decision.asked_user_id != user.id:
        raise SupervisionError("Only the person asked can answer", status_code=403)
    answer = answer.strip() if isinstance(answer, str) else ""

    def _check(row):
        if row.status != "open":
            raise SupervisionError(f"This decision is already {row.status}", status_code=409)
        if not answer or len(answer) > MAX_ANSWER_LENGTH:
            raise SupervisionError(f"answer is required and at most {MAX_ANSWER_LENGTH} characters", field="answer")
        if row.options and answer not in row.options:
            raise SupervisionError("answer must be one of the options", field="answer")

    _check(decision)
    with transaction.atomic():
        locked = DecisionRequest.objects.select_for_update().get(pk=decision.pk)
        _check(locked)
        locked.status = "answered"
        locked.answer = answer
        locked.answered_by = user
        locked.answered_at = timezone.now()
        locked.updated_by = user
        locked.save()
        issue = locked.issue
        comment = IssueComment.objects.create(
            issue=issue,
            project_id=issue.project_id,
            workspace_id=issue.workspace_id,
            actor=user,
            created_by=user,
            comment_html=f"<p>Decision: <strong>{escape(answer)}</strong></p><p>{escape(locked.question)}</p>",
        )
        IssueActivity.objects.create(
            issue=issue,
            project_id=issue.project_id,
            workspace_id=issue.workspace_id,
            actor=user,
            verb="updated",
            field="decision",
            comment=f"answered a decision: {answer}",
            new_value=answer,
            issue_comment=comment,
            epoch=timezone.now().timestamp(),
            source=source,
        )
        _dispatch_comment_created(comment, user, source)
    return locked


def _dispatch_comment_created(comment, user, source):
    """Run the normal comment pipeline (activity, mentions, subscribers, webhooks) once committed."""
    from plane.bgtasks.issue_activities_task import issue_activity
    from plane.bgtasks.webhook_task import model_activity

    requested = json.dumps({"id": str(comment.id), "comment_html": comment.comment_html}, cls=DjangoJSONEncoder)
    epoch = int(timezone.now().timestamp())
    slug = comment.issue.workspace.slug

    def _send():
        issue_activity.delay(
            source=source,
            type="comment.activity.created",
            requested_data=requested,
            actor_id=str(user.id),
            issue_id=str(comment.issue_id),
            project_id=str(comment.project_id),
            current_instance=None,
            epoch=epoch,
        )
        model_activity.delay(
            model_name="issue_comment",
            model_id=str(comment.id),
            requested_data={"comment_html": comment.comment_html},
            current_instance=None,
            actor_id=str(user.id),
            slug=slug,
            origin=None,
        )

    transaction.on_commit(_send)


def withdraw_decision(decision, user):
    """The person who asked, or the person asked, takes an open decision back."""
    from plane.db.models import DecisionRequest

    if user.id not in (decision.created_by_id, decision.asked_user_id):
        raise SupervisionError("Only the asker or the person asked can withdraw", status_code=403)
    with transaction.atomic():
        locked = DecisionRequest.objects.select_for_update().get(pk=decision.pk)
        if locked.status != "open":
            raise SupervisionError(f"This decision is already {locked.status}", status_code=409)
        locked.status = "withdrawn"
        locked.updated_by = user
        locked.save()
    return locked


def decisions_for(workspace_id, user, status="open"):
    """Decisions asked of `user`, limited to work items they can see."""
    from plane.api.views.issue import visible_issue_q
    from plane.db.models import DecisionRequest, Issue

    visible = Issue.issue_objects.filter(visible_issue_q(user)).values("id")
    rows = (
        DecisionRequest.objects.filter(workspace_id=workspace_id, asked_user=user, status=status, issue_id__in=visible)
        .select_related("issue", "issue__project", "issue__state", "created_by")
        .order_by("-created_at")
    )
    return [decision_payload(row, row.issue) for row in rows]
