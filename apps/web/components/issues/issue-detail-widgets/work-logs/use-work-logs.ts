/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import { useProject } from "@/hooks/store/use-project";
import { WorkLogService } from "@/services/work-log.service";

const service = new WorkLogService();

/** A work item's time entries, when time tracking is on for its project. */
export const useWorkLogs = (workspaceSlug: string, projectId: string, issueId: string) => {
  const { t } = useTranslation();
  const { getProjectById } = useProject();
  const enabled = !!getProjectById(projectId)?.is_time_tracking_enabled;
  const { data: logs, mutate } = useSWR(enabled ? `WORK_LOGS_${issueId}` : null, () =>
    service.list(workspaceSlug, projectId, issueId)
  );

  const log = async (duration: number, description: string) => {
    try {
      await service.create(workspaceSlug, projectId, issueId, { duration, description });
      await mutate();
      return true;
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error;
      setToast({ type: "error", title: message ?? t("work_logs.save_error") });
      return false;
    }
  };

  const remove = async (workLogId: string) => {
    try {
      await service.remove(workspaceSlug, projectId, issueId, workLogId);
      await mutate();
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error;
      setToast({ type: "error", title: message ?? t("work_logs.save_error") });
    }
  };

  const total = (logs ?? []).reduce((sum, entry) => sum + entry.duration, 0);
  return { enabled, logs: logs ?? [], total, log, remove };
};
