# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Direct image upload for inline use in descriptions, pages and comments.

POST a multipart ``file`` (or JSON ``{"name", "type", "data": <base64>}``) and
get back the asset id plus ready-to-embed HTML and Markdown. The server writes
the file to storage itself, so clients need no presigned-upload round trip.

Uploading from a URL is deliberately not offered: fetching arbitrary URLs from
the server would let callers reach internal services.
"""

# Python imports
import base64
import binascii
import io
import uuid

# Django imports
from django.conf import settings

# Third party imports
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions import ProjectEntityPermission
from plane.db.models import FileAsset, Issue, IssueComment, Page, Project
from plane.settings.storage import S3Storage
from plane.utils.markdown import ASSET_SCHEME
from plane.utils.path_validator import sanitize_filename

ALLOWED_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}

# entity_type -> (FileAsset field, model, lookup within the project)
ENTITY_LINKS = {
    FileAsset.EntityTypeContext.ISSUE_DESCRIPTION: ("issue_id", Issue, "project_id"),
    FileAsset.EntityTypeContext.PAGE_DESCRIPTION: ("page_id", Page, "project_pages__project_id"),
    FileAsset.EntityTypeContext.COMMENT_DESCRIPTION: ("comment_id", IssueComment, "project_id"),
}


def _read_upload(request):
    """(name, content_type, bytes) from a multipart file or base64 JSON, or an error string."""
    upload = request.FILES.get("file")
    if upload is not None:
        return upload.name, upload.content_type, upload.read(), None
    data = request.data.get("data") if hasattr(request.data, "get") else None
    if not data:
        return None, None, None, "Send the image as a multipart 'file', or as base64 in 'data' with 'name' and 'type'"
    if isinstance(data, str) and data.startswith("data:") and ";base64," in data:
        header, data = data.split(";base64,", 1)
        content_type = header[len("data:") :]
    else:
        content_type = request.data.get("type")
    try:
        content = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError, TypeError):
        return None, None, None, "'data' is not valid base64"
    return request.data.get("name") or "image", content_type, content, None


class InlineAssetUploadAPIEndpoint(BaseAPIView):
    permission_classes = [ProjectEntityPermission]
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    model = FileAsset

    def post(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        name, content_type, content, error = _read_upload(request)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        content_type = (content_type or "").lower()
        if content_type not in ALLOWED_TYPES:
            return Response(
                {"error": "Only JPEG, PNG, WebP and GIF images can be uploaded inline", "type": content_type},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not content:
            return Response({"error": "The file is empty"}, status=status.HTTP_400_BAD_REQUEST)
        if len(content) > settings.FILE_SIZE_LIMIT:
            return Response(
                {"error": f"The file exceeds the {settings.FILE_SIZE_LIMIT} byte limit"},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        # Optional link to the work item / page / comment it is embedded in.
        entity_type = request.data.get("entity_type") or FileAsset.EntityTypeContext.ISSUE_DESCRIPTION
        entity_id = request.data.get("entity_id") or None
        if entity_type not in ENTITY_LINKS:
            return Response(
                {"error": f"entity_type must be one of: {', '.join(ENTITY_LINKS)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        link = {}
        if entity_id:
            field, model, project_lookup = ENTITY_LINKS[entity_type]
            if not model.objects.filter(pk=entity_id, **{project_lookup: project.id}).exists():
                return Response({"error": "entity_id not found in this project"}, status=status.HTTP_404_NOT_FOUND)
            link = {field: entity_id}

        name = sanitize_filename(name) or "image"
        asset_key = f"{project.workspace_id}/{uuid.uuid4().hex}-{name}"
        # No request: write through the internal storage endpoint, not the public host.
        if not S3Storage().upload_file(io.BytesIO(content), asset_key, content_type):
            return Response({"error": "Could not store the file"}, status=status.HTTP_502_BAD_GATEWAY)

        asset = FileAsset.objects.create(
            attributes={"name": name, "type": content_type, "size": len(content)},
            asset=asset_key,
            size=len(content),
            workspace_id=project.workspace_id,
            project_id=project.id,
            entity_type=entity_type,
            is_uploaded=True,
            created_by=request.user,
            **link,
        )
        asset_id = str(asset.id)
        return Response(
            {
                "id": asset_id,
                "name": name,
                "type": content_type,
                "size": len(content),
                "url": f"/api/assets/v2/workspaces/{slug}/projects/{project.id}/{asset_id}/",
                "html": f'<image-component src="{asset_id}" status="uploaded" alignment="left"></image-component>',
                "markdown": f"![{name}]({ASSET_SCHEME}{asset_id})",
            },
            status=status.HTTP_201_CREATED,
        )
