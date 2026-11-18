/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { WikiPageEditor } from "@/components/wiki/page-editor";
import type { Route } from "./+types/page";

function WorkspaceWikiPageDetail({ params }: Route.ComponentProps) {
  return <WikiPageEditor workspaceSlug={params.workspaceSlug} pageId={params.pageId} />;
}

export default observer(WorkspaceWikiPageDetail);
