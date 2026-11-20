/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { Badge } from "@makeplane/propel/components/badge";
import { useTranslation } from "@plane/i18n";
import type { TIssueActivity } from "@plane/types";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";

/** "Agent" next to a work item activity made through an API key or by a bot user. */
export const IssueActivityAgentBadge = observer(function IssueActivityAgentBadge({
  activityId,
}: {
  activityId: string;
}) {
  const { t } = useTranslation();
  const {
    activity: { getActivityById },
  } = useIssueDetail();
  const activity = getActivityById(activityId) as (TIssueActivity & { source?: string }) | undefined;
  if (!activity || (activity.source !== "api" && !activity.actor_detail?.is_bot)) return null;
  return (
    <span className="mr-1 inline-flex align-middle">
      <Badge variant="purple" size="sm" label={t("supervision.agent")} />
    </span>
  );
});
