# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Validation for a project's planning fields (dates, priority, status)."""

from rest_framework import serializers


def validate_project_dates(data, instance=None):
    """A project's start date can't be after its target date (also when only one is changed)."""
    start = data.get("start_date", getattr(instance, "start_date", None))
    target = data.get("target_date", getattr(instance, "target_date", None))
    if start and target and start > target:
        raise serializers.ValidationError({"target_date": "Target date can't be before the start date."})
