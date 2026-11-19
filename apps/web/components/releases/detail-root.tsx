/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR, { mutate as globalMutate } from "swr";
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { InputField } from "@makeplane/propel/components/input-field";
import { LinearProgress } from "@makeplane/propel/components/linear-progress";
import { Switch } from "@makeplane/propel/components/switch";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { Select } from "@plane/blocks/select";
import { setToast } from "@plane/blocks/toast";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import type { TRelease, TReleaseTag } from "@plane/types";
import { EFileAssetType } from "@plane/types";
import { ExistingIssuesListModal } from "@/components/core/modals/existing-issues-list-modal";
import { PageHead } from "@/components/core/page-title";
import { DescriptionInput } from "@/components/editor/rich-text/description-input/root";
import { ProjectDateSelect } from "@/components/project/planning";
import { useMember } from "@/hooks/store/use-member";
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";
import { ProjectService } from "@/services/project";
import { ReleaseService } from "@/services/release.service";
import {
  getReleaseKey,
  getReleaseLabelsKey,
  getReleasesKey,
  getReleaseTagsKey,
  ReleaseLabelChip,
  ReleaseStatusSelect,
} from "./common";

const service = new ReleaseService();
const projectService = new ProjectService();

type TOption = { id: string; name: string };

/** One release: details, labels, description, release notes and the work items it ships. */
export const ReleaseDetail = observer(function ReleaseDetail(props: { workspaceSlug: string; releaseId: string }) {
  const { workspaceSlug, releaseId } = props;
  const { t } = useTranslation();
  const router = useAppRouter();
  const { allowPermissions } = useUserPermissions();
  const { workspaceProjectIds } = useProject();
  const {
    workspace: { workspaceMemberIds, getWorkspaceMemberDetails },
  } = useMember();
  const canEdit = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.WORKSPACE,
    workspaceSlug
  );
  const {
    data: release,
    error,
    mutate,
  } = useSWR(getReleaseKey(releaseId), () => service.retrieve(workspaceSlug, releaseId));
  const { data: changelog } = useSWR(`${getReleaseKey(releaseId)}_CHANGELOG`, () =>
    service.getChangelog(workspaceSlug, releaseId)
  );
  const { data: workItems, mutate: mutateWorkItems } = useSWR(`${getReleaseKey(releaseId)}_WORK_ITEMS`, () =>
    service.listWorkItems(workspaceSlug, releaseId)
  );
  const { data: tags } = useSWR(getReleaseTagsKey(workspaceSlug), () => service.listTags(workspaceSlug));
  const { data: labels } = useSWR(getReleaseLabelsKey(workspaceSlug), () => service.listLabels(workspaceSlug));
  const [name, setName] = useState<string | null>(null);
  const [isPicking, setIsPicking] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const leads: TOption[] = useMemo(
    () =>
      (workspaceMemberIds ?? [])
        .map((id) => getWorkspaceMemberDetails(id)?.member)
        .filter((m): m is NonNullable<typeof m> => !!m)
        .map((m) => ({ id: m.id, name: m.display_name || m.first_name || m.id })),
    [workspaceMemberIds, getWorkspaceMemberDetails]
  );

  if (error) return <p className="px-6 py-6 text-body-sm-regular text-tertiary">{t("releases.not_found")}</p>;
  if (!release) return null;

  const refresh = async () => {
    await Promise.all([mutate(), mutateWorkItems(), globalMutate(getReleasesKey(workspaceSlug))]);
  };
  const run = async (action: () => Promise<unknown>) => {
    try {
      await action();
      await refresh();
    } catch (err) {
      const message = (err as { error?: string } | undefined)?.error;
      setToast({ type: "error", title: message ?? t("releases.save_error") });
    }
  };
  const save = (data: Partial<TRelease>) => run(() => service.update(workspaceSlug, releaseId, data));
  const tagOption = (tags ?? []).find((tag) => tag.id === release.tag) ?? null;
  const leadOption = leads.find((lead) => lead.id === release.lead) ?? null;
  const anyProjectId = workspaceProjectIds?.[0];

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 py-6">
      <PageHead title={`${release.name} - ${t("releases.title")}`} />
      <section className="flex flex-col gap-3">
        <InputField
          size="xl"
          orientation="vertical"
          value={name ?? release.name}
          maxLength={255}
          disabled={!canEdit}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => {
            if (name !== null && name.trim() && name.trim() !== release.name) void save({ name: name.trim() });
            setName(null);
          }}
          aria-label={t("releases.name_placeholder")}
        />
        <div className="flex flex-wrap items-center gap-2">
          <ReleaseStatusSelect
            value={release.status}
            onChange={(status) => void save({ status })}
            disabled={!canEdit}
          />
          {release.is_latest && <Badge variant="success" size="sm" label={t("releases.latest")} />}
          <ProjectDateSelect
            value={release.release_date}
            onChange={(release_date) => void save({ release_date })}
            placeholder={t("releases.release_date")}
            disabled={!canEdit}
          />
          <div className="w-40">
            <Select<TReleaseTag>
              getValues={() => tags ?? []}
              value={tagOption}
              onChange={(next) => void save({ tag: next || null })}
              getOptionValue={(option) => option.id}
              getOptionLabel={(option) => option.version}
              pinSelected={false}
              disabled={!canEdit}
              placeholder={t("releases.no_tag")}
            >
              <Select.Trigger variant="select-ghost-md">
                <Select.Value />
              </Select.Trigger>
            </Select>
          </div>
          <div className="w-44">
            <Select<TOption>
              getValues={() => leads}
              value={leadOption}
              onChange={(next) => void save({ lead: next || null })}
              getOptionValue={(option) => option.id}
              getOptionLabel={(option) => option.name}
              pinSelected={false}
              disabled={!canEdit}
              placeholder={t("releases.no_lead")}
            >
              <Select.Trigger variant="select-ghost-md">
                <Select.Value />
              </Select.Trigger>
            </Select>
          </div>
          <span className="flex items-center gap-2 text-caption-md-regular text-tertiary">
            <Switch
              size="sm"
              checked={release.is_prerelease}
              onCheckedChange={(checked) => void save({ is_prerelease: checked })}
              disabled={!canEdit}
              aria-label={t("releases.prerelease")}
            />
            {t("releases.prerelease")}
          </span>
          {canEdit && (
            <div className="ml-auto">
              <Button
                variant="danger-outline"
                size="sm"
                stretch="auto"
                label={t("releases.delete")}
                onClick={() => setIsDeleting(true)}
              />
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex-1">
            <LinearProgress value={release.progress.percent} size="sm" variant="brand" aria-label={release.name} />
          </div>
          <span className="w-12 text-right text-caption-md-regular text-tertiary">
            {release.progress.completed}/{release.progress.total - release.progress.cancelled}
          </span>
        </div>
        {(labels ?? []).length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-caption-md-regular text-tertiary">{t("releases.labels")}</span>
            {(labels ?? []).map((label) => {
              const active = release.label_ids.includes(label.id);
              return (
                <ReleaseLabelChip
                  key={label.id}
                  label={label}
                  active={active}
                  onClick={
                    canEdit
                      ? () =>
                          void run(() =>
                            active
                              ? service.detachLabels(workspaceSlug, releaseId, [label.id])
                              : service.attachLabels(workspaceSlug, releaseId, [label.id])
                          )
                      : undefined
                  }
                />
              );
            })}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="text-h5-medium text-primary">{t("releases.description")}</h3>
        <DescriptionInput
          key={`release-${release.id}`}
          entityId={release.id}
          fileAssetType={EFileAssetType.PROJECT_DESCRIPTION}
          initialValue={release.description_html}
          workspaceSlug={workspaceSlug}
          disabled={!canEdit}
          disabledExtensions={["image"]}
          setIsSubmitting={() => {}}
          containerClassName="min-h-24 rounded-lg border border-subtle px-4 py-3"
          onSubmit={async (value) => {
            await service.update(workspaceSlug, releaseId, { description_html: value.description_html });
          }}
        />
      </section>

      {changelog !== undefined && (
        <section className="flex flex-col gap-2">
          <h3 className="text-h5-medium text-primary">{t("releases.changelog")}</h3>
          <DescriptionInput
            key={`release-changelog-${release.id}`}
            entityId={`${release.id}-changelog`}
            fileAssetType={EFileAssetType.PROJECT_DESCRIPTION}
            initialValue={changelog}
            workspaceSlug={workspaceSlug}
            disabled={!canEdit}
            disabledExtensions={["image"]}
            setIsSubmitting={() => {}}
            placeholder={t("releases.changelog_placeholder")}
            containerClassName="min-h-32 rounded-lg border border-subtle px-4 py-3"
            onSubmit={async (value) => {
              await service.updateChangelog(workspaceSlug, releaseId, value.description_html);
            }}
          />
        </section>
      )}

      <section className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <h3 className="flex-1 text-h5-medium text-primary">{t("releases.work_items")}</h3>
          {canEdit && anyProjectId && (
            <Button
              variant="secondary"
              size="sm"
              stretch="auto"
              label={t("releases.add_work_items")}
              onClick={() => setIsPicking(true)}
            />
          )}
        </div>
        {!workItems || workItems.length === 0 ? (
          <p className="text-body-xs-regular text-tertiary">{t("releases.no_work_items")}</p>
        ) : (
          <div className="divide-y divide-subtle rounded-lg border border-subtle">
            {workItems.map((item) => {
              const identifier = `${item.project_identifier}-${item.sequence_id}`;
              return (
                <div key={item.id} className="flex items-center gap-3 px-4 py-2.5">
                  <span className="w-20 shrink-0 text-caption-md-medium text-tertiary">{identifier}</span>
                  <Link
                    href={`/${workspaceSlug}/browse/${identifier}/`}
                    className="flex-1 truncate text-body-sm-regular text-primary hover:underline"
                  >
                    {item.name}
                  </Link>
                  {item.state_name && (
                    <span className="shrink-0 text-caption-md-regular text-tertiary">{item.state_name}</span>
                  )}
                  {canEdit && (
                    <Button
                      variant="ghost"
                      size="sm"
                      stretch="auto"
                      label={t("releases.remove")}
                      onClick={() => void run(() => service.removeWorkItems(workspaceSlug, releaseId, [item.id]))}
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {anyProjectId && (
        <ExistingIssuesListModal
          workspaceSlug={workspaceSlug}
          isOpen={isPicking}
          handleClose={() => setIsPicking(false)}
          searchParams={{}}
          selectedWorkItemIds={(workItems ?? []).map((item) => item.id)}
          workItemSearchServiceCallback={(params) =>
            // The search endpoint is project-scoped; workspace_search widens it to every project.
            projectService.projectIssuesSearch(workspaceSlug, anyProjectId, { ...params, workspace_search: true })
          }
          handleOnSubmit={async (selected) => {
            await run(() =>
              service.addWorkItems(
                workspaceSlug,
                releaseId,
                selected.map((item) => item.id)
              )
            );
          }}
        />
      )}
      <ConfirmDialog
        isOpen={isDeleting}
        handleClose={() => setIsDeleting(false)}
        handleSubmit={async () => {
          try {
            await service.remove(workspaceSlug, releaseId);
            await globalMutate(getReleasesKey(workspaceSlug));
            router.push(`/${workspaceSlug}/releases`);
          } catch {
            setToast({ type: "error", title: t("releases.save_error") });
          } finally {
            setIsDeleting(false);
          }
        }}
        isSubmitting={false}
        title={t("releases.delete")}
        content={t("releases.delete_description")}
      />
    </div>
  );
});
