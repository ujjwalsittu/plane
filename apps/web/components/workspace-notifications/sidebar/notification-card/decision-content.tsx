/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useTranslation } from "@plane/i18n";
import type { TNotification, TNotificationData } from "@plane/types";
import { cn } from "@plane/utils";

type TDecisionNotificationData = TNotificationData & { decision?: { question?: string } };

/** A decision request in the inbox: "Decision needed: {question}" (written by supervision_task.py). */
export function DecisionNotificationContent({
  notification,
  isUnread = false,
}: {
  notification: TNotification;
  isUnread?: boolean;
}) {
  const { t } = useTranslation();
  const data = notification.data as TDecisionNotificationData | undefined;
  const question = data?.decision?.question ?? notification.title ?? "";
  return (
    <span className={cn("text-primary", isUnread ? "font-semibold" : "font-medium")}>
      {t("supervision.notification_decision", { question })}
    </span>
  );
}
