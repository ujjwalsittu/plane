/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React from "react";
import { observer } from "mobx-react";
// plane imports
import type { TIssueServiceType, TWorkItemWidgets } from "@plane/types";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useTimeLineRelationOptions } from "@/components/relations";
// local imports
import { AgentRunsCollapsible } from "./agent-runs";
import { AttachmentsCollapsible } from "./attachments";
import { LinksCollapsible } from "./links";
import { CustomRelationsCollapsible } from "./custom-relations";
import { GitHubCollapsible } from "./github";
import { SupervisionCollapsible } from "./supervision";
import { WorkItemPagesCollapsible } from "./pages";
import { WorkLogsCollapsible } from "./work-logs";
import { RelationsCollapsible } from "./relations";
import { SubIssuesCollapsible } from "./sub-issues";
import { TriageCollapsible } from "./triage";

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  disabled: boolean;
  issueServiceType: TIssueServiceType;
  hideWidgets?: TWorkItemWidgets[];
};

export const IssueDetailWidgetCollapsibles = observer(function IssueDetailWidgetCollapsibles(props: Props) {
  const { workspaceSlug, projectId, issueId, disabled, issueServiceType, hideWidgets } = props;
  // store hooks
  const {
    updateIssue,
    createRelation,
    issue: { getIssueById },
    subIssues: { subIssuesByIssueId },
    attachment: { getAttachmentsCountByIssueId, getAttachmentsUploadStatusByIssueId },
    relation: { getRelationCountByIssueId },
  } = useIssueDetail(issueServiceType);
  // derived values
  const issue = getIssueById(issueId);
  const subIssues = subIssuesByIssueId(issueId);
  const ISSUE_RELATION_OPTIONS = useTimeLineRelationOptions();
  const issueRelationsCount = getRelationCountByIssueId(issueId, ISSUE_RELATION_OPTIONS);
  // render conditions
  const shouldRenderSubIssues = !!subIssues && subIssues.length > 0 && !hideWidgets?.includes("sub-work-items");
  const shouldRenderRelations = issueRelationsCount > 0 && !hideWidgets?.includes("relations");
  const shouldRenderLinks = !!issue?.link_count && issue?.link_count > 0 && !hideWidgets?.includes("links");
  const attachmentUploads = getAttachmentsUploadStatusByIssueId(issueId);
  const attachmentsCount = getAttachmentsCountByIssueId(issueId);
  const shouldRenderAttachments =
    attachmentsCount > 0 ||
    (!!attachmentUploads && attachmentUploads.length > 0 && !hideWidgets?.includes("attachments"));

  return (
    <div className="flex flex-col">
      {shouldRenderSubIssues && (
        <SubIssuesCollapsible
          workspaceSlug={workspaceSlug}
          projectId={projectId}
          issueId={issueId}
          disabled={disabled}
          issueServiceType={issueServiceType}
        />
      )}
      {shouldRenderRelations && (
        <RelationsCollapsible
          workspaceSlug={workspaceSlug}
          issueId={issueId}
          disabled={disabled}
          issueServiceType={issueServiceType}
        />
      )}
      {shouldRenderLinks && (
        <LinksCollapsible
          workspaceSlug={workspaceSlug}
          projectId={projectId}
          issueId={issueId}
          disabled={disabled}
          issueServiceType={issueServiceType}
        />
      )}
      <CustomRelationsCollapsible
        workspaceSlug={workspaceSlug}
        projectId={projectId}
        issueId={issueId}
        disabled={disabled}
      />
      <GitHubCollapsible workspaceSlug={workspaceSlug} projectId={projectId} issueId={issueId} />
      <SupervisionCollapsible
        workspaceSlug={workspaceSlug}
        projectId={projectId}
        issueId={issueId}
        disabled={disabled}
      />
      <TriageCollapsible
        workspaceSlug={workspaceSlug}
        projectId={projectId}
        issueId={issueId}
        createdAt={issue?.created_at}
        assigneeIds={issue?.assignee_ids ?? []}
        labelIds={issue?.label_ids ?? []}
        disabled={disabled}
        onAssign={(memberId) =>
          updateIssue(workspaceSlug, projectId, issueId, { assignee_ids: [...(issue?.assignee_ids ?? []), memberId] })
        }
        onAddLabel={(labelId) =>
          updateIssue(workspaceSlug, projectId, issueId, { label_ids: [...(issue?.label_ids ?? []), labelId] })
        }
        onMarkDuplicate={async (relatedId) => {
          await createRelation(workspaceSlug, projectId, issueId, "duplicate", [relatedId]);
        }}
      />
      <AgentRunsCollapsible workspaceSlug={workspaceSlug} projectId={projectId} issueId={issueId} disabled={disabled} />
      <WorkLogsCollapsible workspaceSlug={workspaceSlug} projectId={projectId} issueId={issueId} disabled={disabled} />
      <WorkItemPagesCollapsible
        workspaceSlug={workspaceSlug}
        projectId={projectId}
        issueId={issueId}
        disabled={disabled}
      />
      {shouldRenderAttachments && (
        <AttachmentsCollapsible
          workspaceSlug={workspaceSlug}
          projectId={projectId}
          issueId={issueId}
          disabled={disabled}
          issueServiceType={issueServiceType}
        />
      )}
    </div>
  );
});
