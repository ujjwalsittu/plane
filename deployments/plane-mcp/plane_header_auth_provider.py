# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""API-key (header) auth for the Plane MCP server, patched for this fork.

Upstream validates the key with GET /api/v1/users/me/ on every request and
treats *any* non-200 -- a 429, a 502 while Plane restarts, a timeout -- as an
invalid key. The MCP client then gets a 401 and drops the connection until it
is re-authorised by hand, although the key is fine.

Here only a 401 or 403 from Plane means the key is bad. Anything else is
"Plane is unavailable": a key validated recently keeps working, and an
unknown key gets a retryable 503 instead of a 401. A key validated in the
last minute is not re-checked at all, which also keeps the checks from
adding to Plane's rate limit.
"""

import asyncio
import hashlib
import os
import time

import httpx
from fastmcp.server.auth import TokenVerifier
from fastmcp.server.auth.auth import AccessToken
from fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)

DEFAULT_PLANE_BASE_URL = "https://api.plane.so"

# Skip re-validating a key this soon after it last validated.
FRESH_SECONDS = int(os.getenv("PLANE_MCP_KEY_FRESH_SECONDS", "60"))
# While Plane is unavailable, trust a key that validated within this window.
GRACE_SECONDS = int(os.getenv("PLANE_MCP_KEY_GRACE_SECONDS", str(24 * 3600)))
RETRIES = 3

VALID, INVALID, UNAVAILABLE = "valid", "invalid", "unavailable"

# sha256(key) -> unix time of the last successful validation
_validated_at: dict[str, float] = {}


class PlaneUnavailableError(Exception):
    """Plane could not confirm the key; the caller should retry, not re-auth."""


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class PlaneHeaderAuthProvider(TokenVerifier):
    def __init__(self, required_scopes: list[str] | None = None, timeout_seconds: int = 10):
        super().__init__(required_scopes=required_scopes)
        self.timeout_seconds = timeout_seconds

    async def _check_once(self, token: str) -> str:
        base_url = (os.getenv("PLANE_INTERNAL_BASE_URL") or os.getenv("PLANE_BASE_URL", DEFAULT_PLANE_BASE_URL)).rstrip(
            "/"
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(
                    f"{base_url}/api/v1/users/me/",
                    headers={"x-api-key": token, "Content-Type": "application/json"},
                )
        except httpx.RequestError as e:
            logger.warning("API key validation request failed: %s", e)
            return UNAVAILABLE
        if response.status_code == 200:
            return VALID
        if response.status_code in (401, 403):
            logger.warning("API key rejected by Plane: %s", response.status_code)
            return INVALID
        logger.warning("Plane could not validate the API key right now: %s", response.status_code)
        return UNAVAILABLE

    async def _validate_api_key(self, token: str) -> str:
        for attempt in range(RETRIES):
            result = await self._check_once(token)
            if result != UNAVAILABLE:
                return result
            if attempt < RETRIES - 1:
                await asyncio.sleep(1.5 * (attempt + 1))
        return UNAVAILABLE

    async def _key_is_valid(self, token: str) -> bool:
        """True / False when known; raises PlaneUnavailableError when not."""
        key = _fingerprint(token)
        last = _validated_at.get(key)
        now = time.time()
        if last and now - last < FRESH_SECONDS:
            return True

        result = await self._validate_api_key(token)
        if result == VALID:
            _validated_at[key] = now
            return True
        if result == INVALID:
            _validated_at.pop(key, None)
            return False
        if last and now - last < GRACE_SECONDS:
            logger.warning("Plane unavailable; accepting an API key validated %ds ago", int(now - last))
            return True
        raise PlaneUnavailableError("Plane is unavailable; retry shortly")

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            from fastmcp.server.dependencies import get_http_headers

            headers = get_http_headers()

            if token:
                workspace_slug = headers.get("x-workspace-slug")
                if not workspace_slug:
                    logger.warning("x-api-key header found but x-workspace-slug is missing")
                    return None

                if not await self._key_is_valid(token):
                    logger.warning("API key validation against Plane API failed")
                    return None

                logger.info("API key validated")
                return AccessToken(
                    token=token,
                    client_id="api_key_header_user",
                    scopes=["read", "write"],
                    expires_at=int(time.time() + 3600),
                    claims={
                        "auth_method": "api_key_header",
                        "workspace_slug": workspace_slug,
                    },
                )
        except RuntimeError:
            # No active HTTP request available (e.g., stdio transport)
            logger.debug("No active HTTP request available for header check")
