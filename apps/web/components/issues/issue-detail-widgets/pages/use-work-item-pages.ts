/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import { MilestoneService } from "@/services/milestone.service";
import { ProjectPageService } from "@/services/page";

const milestoneService = new MilestoneService();
const projectPageService = new ProjectPageService();

export const getWorkItemPagesKey = (issueId: string) => `WORK_ITEM_PAGES_${issueId}`;

/** Pages linked to a work item, plus the project's pages that can still be linked. */
export const useWorkItemPages = (args: {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  loadLinkable?: boolean;
}) => {
  const { workspaceSlug, projectId, issueId, loadLinkable = false } = args;
  const { t } = useTranslation();
  const { data: links, mutate } = useSWR(getWorkItemPagesKey(issueId), () =>
    milestoneService.listWorkItemPages(workspaceSlug, projectId, issueId)
  );
  const { data: projectPages } = useSWR(loadLinkable ? `PROJECT_PAGES_FOR_LINKING_${projectId}` : null, () =>
    projectPageService.fetchAll(workspaceSlug, projectId)
  );

  const linkedIds = new Set((links ?? []).map((link) => link.page.id));
  const linkablePages = (projectPages ?? []).filter((page) => page.id && !linkedIds.has(page.id) && !page.archived_at);

  const linkPage = async (pageId: string) => {
    try {
      await milestoneService.linkWorkItemPage(workspaceSlug, projectId, issueId, pageId);
      await mutate();
    } catch {
      setToast({ type: "error", title: t("work_item_pages.link_error") });
    }
  };

  const unlinkPage = async (linkId: string) => {
    try {
      await mutate((current) => current?.filter((link) => link.id !== linkId), { revalidate: false });
      await milestoneService.unlinkWorkItemPage(workspaceSlug, projectId, issueId, linkId);
    } catch {
      setToast({ type: "error", title: t("work_item_pages.unlink_error") });
    } finally {
      await mutate();
    }
  };

  return { links: links ?? [], linkablePages, linkPage, unlinkPage };
};
