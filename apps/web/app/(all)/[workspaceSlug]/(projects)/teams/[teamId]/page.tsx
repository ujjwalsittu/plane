/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { TeamDetail } from "@/components/teams/detail-root";
import type { Route } from "./+types/page";

function WorkspaceTeamDetailPage({ params }: Route.ComponentProps) {
  return <TeamDetail workspaceSlug={params.workspaceSlug} teamId={params.teamId} />;
}

export default observer(WorkspaceTeamDetailPage);
