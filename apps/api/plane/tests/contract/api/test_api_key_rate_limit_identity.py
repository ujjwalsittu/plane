# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The API key rate limit returns a retryable 429 on ordinary calls, but never
on users/me, which MCP clients use to check that the key is still valid."""

from unittest import mock

import pytest
from rest_framework import status

from plane.api.rate_limit import ApiKeyRateThrottle


@pytest.mark.contract
@pytest.mark.django_db
def test_identity_check_is_not_rate_limited(api_key_client, workspace):
    with mock.patch.object(ApiKeyRateThrottle, "rate", "2/minute"):
        projects_url = f"/api/v1/workspaces/{workspace.slug}/projects/"
        assert api_key_client.get(projects_url).status_code == status.HTTP_200_OK
        assert api_key_client.get(projects_url).status_code == status.HTTP_200_OK
        throttled = api_key_client.get(projects_url)
        assert throttled.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert int(throttled["Retry-After"]) > 0

        for _ in range(5):
            assert api_key_client.get("/api/v1/users/me/").status_code == status.HTTP_200_OK
