/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { sortBy } from "lodash-es";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR, { mutate as globalMutate } from "swr";
import { Button } from "@makeplane/propel/components/button";
import { InputField } from "@makeplane/propel/components/input-field";
import { Logo } from "@plane/blocks/emoji-icon-picker";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { Select } from "@plane/blocks/select";
import { setToast } from "@plane/blocks/toast";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import type { TInitiative, TProject } from "@plane/types";
import { EFileAssetType } from "@plane/types";
import { ExistingIssuesListModal } from "@/components/core/modals/existing-issues-list-modal";
import { DescriptionInput } from "@/components/editor/rich-text/description-input/root";
import { ProjectDateSelect } from "@/components/project/planning";
import { useMember } from "@/hooks/store/use-member";
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";
import { InitiativeService } from "@/services/initiative.service";
import { ProjectService } from "@/services/project";
import { getInitiativeKey, getInitiativesKey, InitiativeProgressBar, InitiativeStateSelect } from "./common";

const service = new InitiativeService();
const projectService = new ProjectService();

type TLeadOption = { id: string; name: string };

/** One initiative: its details, the projects and work items it groups, and their rolled-up progress. */
export const InitiativeDetail = observer(function InitiativeDetail(props: {
  workspaceSlug: string;
  initiativeId: string;
}) {
  const { workspaceSlug, initiativeId } = props;
  const { t } = useTranslation();
  const router = useAppRouter();
  const { allowPermissions } = useUserPermissions();
  const { workspaceProjectIds, getProjectById } = useProject();
  const {
    workspace: { workspaceMemberIds, getWorkspaceMemberDetails },
  } = useMember();
  const canEdit = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.WORKSPACE,
    workspaceSlug
  );
  const {
    data: initiative,
    error,
    mutate,
  } = useSWR(getInitiativeKey(initiativeId), () => service.retrieve(workspaceSlug, initiativeId));
  const { data: workItems, mutate: mutateWorkItems } = useSWR(`${getInitiativeKey(initiativeId)}_WORK_ITEMS`, () =>
    service.listWorkItems(workspaceSlug, initiativeId)
  );
  const [name, setName] = useState<string | null>(null);
  const [isPicking, setIsPicking] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const projects = useMemo(
    () =>
      sortBy(
        (workspaceProjectIds ?? []).map((id) => getProjectById(id)).filter((p): p is TProject => !!p && !p.archived_at),
        (p) => p.name.toLowerCase()
      ),
    [workspaceProjectIds, getProjectById]
  );
  const leads: TLeadOption[] = useMemo(
    () =>
      (workspaceMemberIds ?? [])
        .map((id) => getWorkspaceMemberDetails(id)?.member)
        .filter((m): m is NonNullable<typeof m> => !!m)
        .map((m) => ({ id: m.id, name: m.display_name || m.first_name || m.id })),
    [workspaceMemberIds, getWorkspaceMemberDetails]
  );

  if (error) return <p className="px-6 py-6 text-body-sm-regular text-tertiary">{t("initiatives.not_found")}</p>;
  if (!initiative) return null;

  const refresh = async () => {
    await Promise.all([mutate(), mutateWorkItems(), globalMutate(getInitiativesKey(workspaceSlug))]);
  };

  const run = async (action: () => Promise<unknown>) => {
    try {
      await action();
      await refresh();
    } catch (err) {
      const message = (err as { error?: string } | undefined)?.error;
      setToast({ type: "error", title: message ?? t("initiatives.save_error") });
    }
  };

  const save = (data: Partial<TInitiative>) => run(() => service.update(workspaceSlug, initiativeId, data));
  const linkedProjects = projects.filter((p) => initiative.project_ids.includes(p.id));
  const unlinkedProjects = projects.filter((p) => !initiative.project_ids.includes(p.id));
  const leadOption = leads.find((lead) => lead.id === initiative.lead) ?? null;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 py-6">
      <section className="flex flex-col gap-3">
        <InputField
          size="xl"
          orientation="vertical"
          value={name ?? initiative.name}
          maxLength={255}
          disabled={!canEdit}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => {
            if (name !== null && name.trim() && name.trim() !== initiative.name) void save({ name: name.trim() });
            setName(null);
          }}
          aria-label={t("initiatives.name_placeholder")}
        />
        <div className="flex flex-wrap items-center gap-2">
          <InitiativeStateSelect
            value={initiative.state}
            onChange={(state) => void save({ state })}
            disabled={!canEdit}
          />
          <ProjectDateSelect
            value={initiative.start_date}
            onChange={(start_date) => void save({ start_date })}
            placeholder={t("initiatives.start_date")}
            maxDate={initiative.end_date}
            disabled={!canEdit}
          />
          <ProjectDateSelect
            value={initiative.end_date}
            onChange={(end_date) => void save({ end_date })}
            placeholder={t("initiatives.end_date")}
            minDate={initiative.start_date}
            disabled={!canEdit}
          />
          <div className="w-48">
            <Select<TLeadOption>
              getValues={() => leads}
              value={leadOption}
              onChange={(next) => void save({ lead: next || null })}
              getOptionValue={(option) => option.id}
              getOptionLabel={(option) => option.name}
              pinSelected={false}
              disabled={!canEdit}
              placeholder={t("initiatives.no_lead")}
            >
              <Select.Trigger variant="select-ghost-md">
                <Select.Value />
              </Select.Trigger>
            </Select>
          </div>
          {canEdit && (
            <div className="ml-auto">
              <Button
                variant="danger-outline"
                size="sm"
                stretch="auto"
                label={t("initiatives.delete")}
                onClick={() => setIsDeleting(true)}
              />
            </div>
          )}
        </div>
        <InitiativeProgressBar progress={initiative.progress} label={initiative.name} />
        <p className="text-caption-md-regular text-tertiary">{t("initiatives.work_items_hint")}</p>
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="text-h5-medium text-primary">{t("initiatives.description")}</h3>
        <DescriptionInput
          key={`initiative-${initiative.id}`}
          entityId={initiative.id}
          fileAssetType={EFileAssetType.PROJECT_DESCRIPTION}
          initialValue={initiative.description_html}
          workspaceSlug={workspaceSlug}
          disabled={!canEdit}
          disabledExtensions={["image"]}
          setIsSubmitting={() => {}}
          placeholder={t("initiatives.no_description")}
          containerClassName="min-h-32 rounded-lg border border-subtle px-4 py-3"
          onSubmit={async (value) => {
            await service.update(workspaceSlug, initiativeId, { description_html: value.description_html });
          }}
        />
      </section>

      <section className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="flex-1 text-h5-medium text-primary">{t("initiatives.projects")}</h3>
          {canEdit && unlinkedProjects.length > 0 && (
            <div className="w-64">
              <Select<TProject>
                getValues={() => unlinkedProjects}
                value={null}
                onChange={(next) => {
                  if (next) void run(() => service.addProjects(workspaceSlug, initiativeId, [next]));
                }}
                getOptionValue={(option) => option.id}
                getOptionLabel={(option) => `${option.name} (${option.identifier})`}
                pinSelected={false}
                placeholder={t("initiatives.add_projects")}
              >
                <Select.Trigger variant="select-md">
                  <Select.Value />
                </Select.Trigger>
              </Select>
            </div>
          )}
        </div>
        {linkedProjects.length === 0 ? (
          <p className="text-body-xs-regular text-tertiary">{t("initiatives.no_projects")}</p>
        ) : (
          <div className="divide-y divide-subtle rounded-lg border border-subtle">
            {linkedProjects.map((project) => (
              <div key={project.id} className="flex items-center gap-3 px-4 py-2.5">
                <Logo logo={project.logo_props} size={16} />
                <Link
                  href={`/${workspaceSlug}/projects/${project.id}/issues/`}
                  className="flex-1 truncate text-body-sm-medium text-primary hover:underline"
                >
                  {project.name}
                </Link>
                <span className="text-caption-md-regular text-tertiary">{project.identifier}</span>
                {canEdit && (
                  <Button
                    variant="ghost"
                    size="sm"
                    stretch="auto"
                    label={t("initiatives.remove")}
                    onClick={() => void run(() => service.removeProjects(workspaceSlug, initiativeId, [project.id]))}
                  />
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <h3 className="flex-1 text-h5-medium text-primary">{t("initiatives.work_items")}</h3>
          {canEdit && projects.length > 0 && (
            <Button
              variant="secondary"
              size="sm"
              stretch="auto"
              label={t("initiatives.add_work_items")}
              onClick={() => setIsPicking(true)}
            />
          )}
        </div>
        {!workItems || workItems.length === 0 ? (
          <p className="text-body-xs-regular text-tertiary">{t("initiatives.no_work_items")}</p>
        ) : (
          <div className="divide-y divide-subtle rounded-lg border border-subtle">
            {workItems.map((item) => {
              const project = getProjectById(item.project_id);
              const identifier = project ? `${project.identifier}-${item.sequence_id}` : `#${item.sequence_id}`;
              return (
                <div key={item.id} className="flex items-center gap-3 px-4 py-2.5">
                  <span className="w-20 shrink-0 text-caption-md-medium text-tertiary">{identifier}</span>
                  <Link
                    href={`/${workspaceSlug}/browse/${identifier}/`}
                    className="flex-1 truncate text-body-sm-regular text-primary hover:underline"
                  >
                    {item.name}
                  </Link>
                  {canEdit && (
                    <Button
                      variant="ghost"
                      size="sm"
                      stretch="auto"
                      label={t("initiatives.remove")}
                      onClick={() => void run(() => service.removeWorkItems(workspaceSlug, initiativeId, [item.id]))}
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {projects.length > 0 && (
        <ExistingIssuesListModal
          workspaceSlug={workspaceSlug}
          isOpen={isPicking}
          handleClose={() => setIsPicking(false)}
          searchParams={{}}
          selectedWorkItemIds={initiative.work_item_ids}
          workItemSearchServiceCallback={(params) =>
            // The search endpoint is project-scoped; workspace_search widens it to every project.
            projectService.projectIssuesSearch(workspaceSlug, initiative.project_ids[0] ?? projects[0].id, {
              ...params,
              workspace_search: true,
            })
          }
          handleOnSubmit={async (selected) => {
            await run(() =>
              service.addWorkItems(
                workspaceSlug,
                initiativeId,
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
            await service.remove(workspaceSlug, initiativeId);
            await globalMutate(getInitiativesKey(workspaceSlug));
            router.push(`/${workspaceSlug}/initiatives`);
          } catch {
            setToast({ type: "error", title: t("initiatives.save_error") });
          } finally {
            setIsDeleting(false);
          }
        }}
        isSubmitting={false}
        title={t("initiatives.delete")}
        content={t("initiatives.delete_description")}
      />
    </div>
  );
});
