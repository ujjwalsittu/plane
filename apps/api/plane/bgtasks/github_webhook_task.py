# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Processes stored GitHub webhook deliveries, retrying failures, and prunes old ones."""

# Python imports
import logging
from datetime import timedelta

# Third party imports
from celery import shared_task

# Django imports
from django.db import transaction
from django.utils import timezone

# Module imports
from plane.db.models import GitHubRepositoryLink, GitHubWebhookDelivery, Issue
from plane.utils.exception_logger import log_exception
from plane.utils.github_integration import process_delivery
from plane.utils.github_sync import backfill_repository

logger = logging.getLogger("plane.worker")

MAX_ATTEMPTS = 5
KEEP_DAYS = 30


@shared_task(bind=True, max_retries=MAX_ATTEMPTS - 1)
def process_github_delivery(self, delivery_pk):
    with transaction.atomic():
        delivery = GitHubWebhookDelivery.objects.select_for_update().filter(pk=delivery_pk).first()
        # Processed ones are done; failed ones wait for a redelivery from GitHub, which resets them.
        if not delivery or delivery.status != GitHubWebhookDelivery.PENDING:
            return
        delivery.attempts += 1
        try:
            with transaction.atomic():
                process_delivery(delivery)
        except Exception as exc:  # noqa: BLE001 - recorded on the delivery and retried
            delivery.error = f"{exc.__class__.__name__}: {exc}"[:2000]
            final = delivery.attempts >= MAX_ATTEMPTS
            delivery.status = GitHubWebhookDelivery.FAILED if final else GitHubWebhookDelivery.PENDING
            delivery.save(update_fields=["attempts", "error", "status"])
            if final:
                log_exception(exc)
                return
            failure = exc
        else:
            delivery.status = GitHubWebhookDelivery.PROCESSED
            delivery.error = ""
            delivery.processed_at = timezone.now()
            delivery.save(update_fields=["attempts", "error", "status", "processed_at"])
            return
    # Outside the transaction so the attempt count is committed before the retry is queued.
    raise self.retry(exc=failure, countdown=min(30 * 2 ** (delivery.attempts - 1), 600))


@shared_task
def delete_old_github_deliveries():
    cutoff = timezone.now() - timedelta(days=KEEP_DAYS)
    deleted, _ = GitHubWebhookDelivery.objects.filter(received_at__lt=cutoff).delete()
    logger.info("Deleted %s old GitHub webhook deliveries", deleted)


@shared_task(bind=True, max_retries=3)
def backfill_github_repository(self, link_id):
    """Link the open pull requests of a newly linked repository to the work items they mention."""
    link = GitHubRepositoryLink.objects.filter(pk=link_id).select_related("installation").first()
    if not link:
        return
    try:
        count = backfill_repository(link)
    except Exception as exc:  # noqa: BLE001 - retried, then logged
        if self.request.retries >= self.max_retries:
            log_exception(exc)
            return
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
    logger.info("Backfilled %s open pull requests for %s", count, link.full_name)


@shared_task(bind=True, max_retries=5)
def push_github_issue(self, issue_id):
    """Send a work item's changes and comments to its GitHub issue."""
    from plane.utils.github_issue_sync import push_issue

    issue = Issue.issue_objects.filter(pk=issue_id).select_related("state").first()
    if not issue:
        return
    try:
        push_issue(issue)
    except Exception as exc:  # noqa: BLE001 - retried, then logged
        if self.request.retries >= self.max_retries:
            log_exception(exc)
            return
        raise self.retry(exc=exc, countdown=30 * 2**self.request.retries)


@shared_task(bind=True, max_retries=3)
def import_github_issues(self, link_id):
    """Import a repository's open issues as work items when issue sync is turned on."""
    from plane.utils.github_issue_sync import import_open_issues

    link = (
        GitHubRepositoryLink.objects.filter(pk=link_id, issue_sync=True)
        .select_related("project", "installation")
        .first()
    )
    if not link:
        return
    try:
        count = import_open_issues(link)
    except Exception as exc:  # noqa: BLE001 - retried, then logged
        if self.request.retries >= self.max_retries:
            log_exception(exc)
            return
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
    logger.info("Imported %s open GitHub issues for %s", count, link.full_name)
