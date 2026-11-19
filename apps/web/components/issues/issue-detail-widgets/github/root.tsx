/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { EntityDetailWidgetSection } from "@plane/blocks/entity-detail";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TWorkItemGitHub } from "@plane/types";
import { copyTextToClipboard } from "@plane/utils";
import { GitHubMarkIcon } from "@/components/integration/github-app/github-mark-icon";
import { GitHubAppService } from "@/services/github-app.service";

const service = new GitHubAppService();

type TPullRequest = TWorkItemGitHub["pull_requests"][number];

const STATUS_VARIANT = {
  open: "success",
  draft: "grey",
  merged: "purple",
  closed: "danger",
} as const;

const CHECKS_COLOR: Record<TPullRequest["checks_state"], string> = {
  "": "",
  pending: "bg-warning-primary",
  success: "bg-success-primary",
  failure: "bg-danger-primary",
};

type Props = { workspaceSlug: string; projectId: string; issueId: string };

export const getWorkItemGitHubKey = (issueId: string) => `WORK_ITEM_GITHUB_${issueId}`;

/** Pull requests, branches and commits that mention the work item, with a branch name to copy. */
export function GitHubCollapsible({ workspaceSlug, projectId, issueId }: Props) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(true);
  const { data } = useSWR(
    getWorkItemGitHubKey(issueId),
    () => service.getWorkItemGitHub(workspaceSlug, projectId, issueId),
    // Webhooks update the server within seconds; refresh while the work item is open.
    { refreshInterval: 30_000 }
  );

  if (!data) return null;
  const count = data.pull_requests.length + data.branches.length + data.commits.length;
  if (!data.enabled && count === 0) return null;

  // Open pull requests that need attention.
  const active = data.pull_requests.filter((pr) => pr.status === "open" || pr.status === "draft");
  const checksFailing = active.some((pr) => pr.checks_state === "failure");
  const changesRequested = active.some((pr) => pr.review_state === "changes_requested");

  const copyBranch = async () => {
    await copyTextToClipboard(data.branch_name);
    setToast({ type: "success", title: t("github_app.work_item.branch_copied"), message: data.branch_name });
  };

  return (
    <EntityDetailWidgetSection
      title={t("github_app.work_item.title")}
      count={count}
      isOpen={isOpen}
      onToggle={() => setIsOpen((value) => !value)}
      titleAccessory={
        checksFailing || changesRequested ? (
          <span className="flex items-center gap-1">
            {checksFailing && <Badge variant="danger" size="sm" label={t("github_app.work_item.flag_checks")} />}
            {changesRequested && <Badge variant="warning" size="sm" label={t("github_app.work_item.flag_changes")} />}
          </span>
        ) : undefined
      }
      actions={
        <Button
          variant="ghost"
          size="sm"
          stretch="auto"
          icon={<GitHubMarkIcon className="size-3" />}
          label={t("github_app.work_item.copy_branch")}
          onClick={() => void copyBranch()}
        />
      }
    >
      <div className="flex flex-col gap-0.5 py-1">
        {count === 0 && (
          <p className="px-2 py-1.5 text-body-xs-regular text-tertiary">
            {t("github_app.work_item.empty", { branch: data.branch_name })}
          </p>
        )}
        {data.pull_requests.map((pr) => (
          <PullRequestRow key={pr.id} pr={pr} />
        ))}
        {data.branches.map((branch) => (
          <a
            key={branch.id}
            href={branch.url || undefined}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-layer-1"
          >
            <span className="text-caption-md-medium text-tertiary">{t("github_app.work_item.branch")}</span>
            <span className="font-mono min-w-0 flex-1 truncate text-body-xs-regular text-primary">{branch.name}</span>
            <span className="shrink-0 text-caption-md-regular text-tertiary">{branch.repository}</span>
          </a>
        ))}
        {data.commits.map((commit) => (
          <a
            key={commit.id}
            href={commit.url || undefined}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-layer-1"
          >
            <span className="font-mono text-caption-md-medium text-tertiary">{commit.sha.slice(0, 7)}</span>
            <span className="min-w-0 flex-1 truncate text-body-xs-regular text-primary">{commit.message}</span>
            <span className="shrink-0 text-caption-md-regular text-tertiary">
              {commit.author ? `${commit.author} · ` : ""}
              {commit.repository}
            </span>
          </a>
        ))}
      </div>
    </EntityDetailWidgetSection>
  );
}

function PullRequestRow({ pr }: { pr: TPullRequest }) {
  const { t } = useTranslation();
  return (
    <a
      href={pr.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex flex-wrap items-center gap-2 rounded-md px-2 py-1.5 hover:bg-layer-1"
    >
      <Badge variant={STATUS_VARIANT[pr.status]} size="sm" label={t(`github_app.work_item.status.${pr.status}`)} />
      <span className="min-w-0 flex-1 truncate text-body-xs-medium text-primary">{pr.title}</span>
      {pr.review_state === "approved" && (
        <Badge variant="success" size="sm" label={t("github_app.work_item.approved")} />
      )}
      {pr.review_state === "changes_requested" && (
        <Badge variant="warning" size="sm" label={t("github_app.work_item.changes_requested")} />
      )}
      {pr.checks_state && (
        <span
          className={`size-2 shrink-0 rounded-full ${CHECKS_COLOR[pr.checks_state]}`}
          title={t(`github_app.work_item.checks.${pr.checks_state}`)}
          aria-label={t(`github_app.work_item.checks.${pr.checks_state}`)}
          role="img"
        />
      )}
      <span className="shrink-0 text-caption-md-regular text-tertiary">
        {pr.repository}#{pr.number}
      </span>
    </a>
  );
}
