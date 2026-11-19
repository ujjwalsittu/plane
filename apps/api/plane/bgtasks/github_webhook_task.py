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
from plane.db.models import GitHubWebhookDelivery
from plane.utils.exception_logger import log_exception
from plane.utils.github_integration import process_delivery

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
