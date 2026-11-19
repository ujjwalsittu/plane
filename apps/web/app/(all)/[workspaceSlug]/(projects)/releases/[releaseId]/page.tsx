/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { ReleaseDetail } from "@/components/releases/detail-root";
import type { Route } from "./+types/page";

function WorkspaceReleaseDetailPage({ params }: Route.ComponentProps) {
  return <ReleaseDetail workspaceSlug={params.workspaceSlug} releaseId={params.releaseId} />;
}

export default observer(WorkspaceReleaseDetailPage);
