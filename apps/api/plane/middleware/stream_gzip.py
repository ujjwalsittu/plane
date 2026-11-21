# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.middleware.gzip import GZipMiddleware


class StreamFriendlyGZipMiddleware(GZipMiddleware):
    """Django's GZip, minus server-sent events: compressing a stream buffers it, so frames would arrive late."""

    def process_response(self, request, response):
        if response.get("Content-Type", "").startswith("text/event-stream"):
            return response
        return super().process_response(request, response)
