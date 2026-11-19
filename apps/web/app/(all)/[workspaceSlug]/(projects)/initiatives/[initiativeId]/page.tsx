/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { InitiativeDetail } from "@/components/initiatives/detail-root";
import type { Route } from "./+types/page";

function WorkspaceInitiativeDetailPage({ params }: Route.ComponentProps) {
  return <InitiativeDetail workspaceSlug={params.workspaceSlug} initiativeId={params.initiativeId} />;
}

export default observer(WorkspaceInitiativeDetailPage);
