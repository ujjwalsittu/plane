# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Talking to GitHub as the GitHub App: app JWTs, installation access tokens, webhook signature
checks and the few REST calls the integration needs."""

# Python imports
import base64
import hashlib
import hmac
import time

# Third party imports
import jwt
import requests

# Django imports
from django.conf import settings
from django.core.cache import cache
from django.core import signing

GITHUB_API = "https://api.github.com"
TIMEOUT = 10
INSTALL_STATE_SALT = "plane.github.install"
INSTALL_STATE_MAX_AGE = 60 * 60


# A GitHub failure is reported as 424 (failed dependency): a 5xx from Plane would be swapped for the
# proxy's own error page, hiding the message.
UPSTREAM_ERROR = 424


class GitHubAppError(Exception):
    def __init__(self, message, status_code=UPSTREAM_ERROR, github_status=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.github_status = github_status


def private_key():
    raw = (settings.GITHUB_APP_PRIVATE_KEY or "").strip()
    if not raw:
        return ""
    if "BEGIN" not in raw:
        try:
            raw = base64.b64decode(raw).decode()
        except (ValueError, UnicodeDecodeError):
            return ""
    return raw.replace("\\n", "\n").strip()


def is_configured():
    return bool(
        settings.GITHUB_APP_ID and settings.GITHUB_APP_SLUG and settings.GITHUB_APP_WEBHOOK_SECRET and private_key()
    )


def require_configured():
    if not is_configured():
        raise GitHubAppError("The GitHub App is not configured on this server", status_code=400)


def install_url(state):
    return f"https://github.com/apps/{settings.GITHUB_APP_SLUG}/installations/new?state={state}"


def make_install_state(workspace_id, user_id):
    return signing.dumps({"w": str(workspace_id), "u": str(user_id)}, salt=INSTALL_STATE_SALT, compress=True)


def read_install_state(state):
    """Returns (workspace_id, user_id); raises signing.BadSignature (or SignatureExpired)."""
    data = signing.loads(state, salt=INSTALL_STATE_SALT, max_age=INSTALL_STATE_MAX_AGE)
    return data["w"], data["u"]


def verify_signature(body, signature_header):
    """Checks GitHub's X-Hub-Signature-256 header against the raw request body."""
    secret = settings.GITHUB_APP_WEBHOOK_SECRET
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def app_jwt():
    now = int(time.time())
    # Backdated a minute for clock drift; GitHub caps the lifetime at 10 minutes.
    payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": str(settings.GITHUB_APP_ID)}
    return jwt.encode(payload, private_key(), algorithm="RS256")


def _headers(token, scheme="Bearer"):
    return {
        "Authorization": f"{scheme} {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "plane-github-app",
    }


def _request(method, path, token, **kwargs):
    try:
        response = requests.request(method, f"{GITHUB_API}{path}", headers=_headers(token), timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise GitHubAppError(f"GitHub could not be reached: {exc.__class__.__name__}") from exc
    if response.status_code == 404:
        raise GitHubAppError("Not found on GitHub, or the app has no access to it", status_code=404, github_status=404)
    if response.status_code >= 400:
        try:
            detail = response.json().get("message", "")
        except ValueError:
            detail = ""
        message = f"GitHub answered {response.status_code}" + (f": {detail}" if detail else "")
        raise GitHubAppError(message[:500], github_status=response.status_code)
    return response.json() if response.content else None


def get_installation(installation_id):
    require_configured()
    return _request("GET", f"/app/installations/{int(installation_id)}", app_jwt())


def app_installations(limit=500):
    """Every installation of the app, as GitHub lists them to the app itself."""
    require_configured()
    installations, page = [], 1
    while len(installations) < limit:
        batch = _request("GET", "/app/installations", app_jwt(), params={"per_page": 100, "page": page}) or []
        installations.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return installations[:limit]


def _token_cache_key(installation_id):
    return f"github:installation-token:{int(installation_id)}"


def installation_token(installation_id):
    require_configured()
    key = _token_cache_key(installation_id)
    token = cache.get(key)
    if token:
        return token
    data = _request("POST", f"/app/installations/{int(installation_id)}/access_tokens", app_jwt())
    token = data["token"]
    # Tokens last an hour; refresh well before that.
    cache.set(key, token, 50 * 60)
    return token


def forget_installation_token(installation_id):
    cache.delete(_token_cache_key(installation_id))


def _installation_request(installation_id, method, path, **kwargs):
    """A call with the installation's token. GitHub revokes tokens when the app's permissions or keys
    change, so a 401 with a cached token gets one retry with a fresh one."""
    try:
        return _request(method, path, installation_token(installation_id), **kwargs)
    except GitHubAppError as exc:
        if exc.github_status != 401:
            raise
    forget_installation_token(installation_id)
    return _request(method, path, installation_token(installation_id), **kwargs)


def installation_repositories(installation_id, limit=1000):
    repos, page = [], 1
    while len(repos) < limit:
        data = _installation_request(
            installation_id, "GET", "/installation/repositories", params={"per_page": 100, "page": page}
        )
        batch = data.get("repositories", [])
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos[:limit]


def get_repository(installation_id, repository_id):
    return _installation_request(installation_id, "GET", f"/repositories/{int(repository_id)}")


def repository_summary(repo):
    return {
        "id": repo["id"],
        "full_name": repo["full_name"],
        "html_url": repo.get("html_url", ""),
        "default_branch": repo.get("default_branch", ""),
        "private": bool(repo.get("private")),
    }
