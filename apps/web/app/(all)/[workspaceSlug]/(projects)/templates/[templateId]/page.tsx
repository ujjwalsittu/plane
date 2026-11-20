/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { TemplateDetail } from "@/components/templates/detail-root";
import type { Route } from "./+types/page";

function WorkspaceTemplateDetailPage({ params }: Route.ComponentProps) {
  return <TemplateDetail workspaceSlug={params.workspaceSlug} templateId={params.templateId} />;
}

export default observer(WorkspaceTemplateDetailPage);
