/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR from "swr";
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { InputField } from "@makeplane/propel/components/input-field";
import { LinearProgress } from "@makeplane/propel/components/linear-progress";
import {
  Menu,
  MenuCheckboxItem,
  MenuContent,
  MenuItem,
  MenuSeparator,
  MenuTrigger,
} from "@makeplane/propel/components/menu";
import { MilestoneOutline, ModuleOutline, PagesOutline } from "@makeplane/propel/icons";
import { Logo } from "@plane/blocks/emoji-icon-picker";
import { setToast } from "@plane/blocks/toast";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import type { TNameDescriptionLoader, TProjectOverviewUpdate } from "@plane/types";
import { EFileAssetType } from "@plane/types";
import { cn } from "@plane/utils";
import { DescriptionInput } from "@/components/editor/rich-text/description-input/root";
import { getMilestoneProgress, MilestoneStatusIcon } from "@/components/milestones/milestones-list";
import { useMilestone } from "@/hooks/store/use-milestone";
import { useModule } from "@/hooks/store/use-module";
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
import { MilestoneService } from "@/services/milestone.service";
import { ProjectPageService } from "@/services/page";

const milestoneService = new MilestoneService();
const projectPageService = new ProjectPageService();

type Props = {
  workspaceSlug: string;
  projectId: string;
};

function Panel(props: { title: string; icon: React.ReactNode; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2 rounded-lg border border-subtle p-4">
      <div className="flex items-center gap-2">
        {props.icon}
        <h2 className="text-body-sm-medium text-primary">{props.title}</h2>
        <div className="ml-auto">{props.action}</div>
      </div>
      {props.children}
    </section>
  );
}

export const ProjectOverviewRoot = observer(function ProjectOverviewRoot(props: Props) {
  const { workspaceSlug, projectId } = props;
  const { t } = useTranslation();
  const { getProjectById } = useProject();
  const { getProjectMilestones } = useMilestone();
  const { getProjectModuleDetails } = useModule();
  const { allowPermissions } = useUserPermissions();
  const [saving, setSaving] = useState<TNameDescriptionLoader>("saved");
  const [newTag, setNewTag] = useState("");

  const project = getProjectById(projectId);
  const canEdit = allowPermissions([EUserPermissions.ADMIN, EUserPermissions.MEMBER], EUserPermissionsLevel.PROJECT);

  const overviewKey = `PROJECT_OVERVIEW_${projectId}`;
  const { data: overview, mutate } = useSWR(overviewKey, () => milestoneService.getOverview(workspaceSlug, projectId));
  const { data: tags, mutate: mutateTags } = useSWR(`PROJECT_TAGS_${workspaceSlug}`, () =>
    milestoneService.listProjectTags(workspaceSlug)
  );
  const { data: pages } = useSWR(canEdit ? `PROJECT_PAGES_FOR_OVERVIEW_${projectId}` : null, () =>
    projectPageService.fetchAll(workspaceSlug, projectId)
  );

  const update = async (data: TProjectOverviewUpdate) => {
    try {
      const updated = await milestoneService.updateOverview(workspaceSlug, projectId, data);
      await mutate(updated, { revalidate: false });
      return updated;
    } catch (error) {
      setToast({ type: "error", title: t("project_overview.save_error") });
      throw error;
    }
  };

  if (!project || !overview) return null;

  const milestones = project.milestone_view ? (getProjectMilestones(projectId) ?? []) : [];
  const modules = project.module_view ? (getProjectModuleDetails(projectId) ?? []) : [];
  const tagIds = new Set(overview.tags.map((tag) => tag.id));
  const linkedIds = new Set(overview.overview_page_ids);
  const linkablePages = (pages ?? []).filter((page) => page.id && !linkedIds.has(page.id) && !page.archived_at);

  const toggleTag = (tagId: string) => {
    const next = tagIds.has(tagId) ? [...tagIds].filter((id) => id !== tagId) : [...tagIds, tagId];
    void update({ tag_ids: next });
  };

  const addTag = async () => {
    const name = newTag.trim();
    if (!name) return;
    try {
      const tag = await milestoneService.createProjectTag(workspaceSlug, { name });
      setNewTag("");
      await mutateTags();
      await update({ tag_ids: [...tagIds, tag.id] });
    } catch {
      setToast({ type: "error", title: t("project_overview.tag_error") });
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-page-x py-6">
      <header className="flex flex-wrap items-center gap-3">
        <div className="grid size-10 shrink-0 place-items-center rounded-md bg-layer-1">
          <Logo logo={project.logo_props} size={22} />
        </div>
        <div className="min-w-0">
          <h1 className="truncate text-h4-semibold text-primary">{project.name}</h1>
          <p className="text-body-xs-regular text-tertiary">{project.identifier}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 sm:ml-auto">
          {overview.tags.map((tag) => (
            <Badge key={tag.id} variant="neutral" size="sm" label={tag.name} />
          ))}
          {canEdit && (
            <Menu>
              <MenuTrigger
                render={<Button variant="ghost" size="sm" stretch="auto" label={t("project_overview.edit_tags")} />}
              />
              <MenuContent side="bottom" align="end">
                {(tags ?? []).map((tag) => (
                  <MenuCheckboxItem
                    key={tag.id}
                    label={tag.name}
                    checked={tagIds.has(tag.id)}
                    onCheckedChange={() => toggleTag(tag.id)}
                  />
                ))}
                {(tags ?? []).length > 0 && <MenuSeparator />}
                <div className="flex gap-1 p-1">
                  <InputField
                    size="md"
                    orientation="vertical"
                    value={newTag}
                    placeholder={t("project_overview.new_tag")}
                    aria-label={t("project_overview.new_tag")}
                    onChange={(e) => setNewTag(e.target.value)}
                    onKeyDown={(e) => {
                      e.stopPropagation();
                      if (e.key === "Enter") void addTag();
                    }}
                  />
                  <Button variant="secondary" size="sm" stretch="auto" label={t("add")} onClick={() => void addTag()} />
                </div>
              </MenuContent>
            </Menu>
          )}
        </div>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <section className="flex min-w-0 flex-col gap-2">
          <div className="flex items-center gap-2">
            <h2 className="text-body-sm-medium text-secondary">{t("project_overview.title")}</h2>
            {canEdit && (
              <span className="text-caption-sm-regular text-tertiary">
                {saving === "submitting" ? t("common.saving") : ""}
              </span>
            )}
          </div>
          <DescriptionInput
            key={`project-overview-${projectId}`}
            entityId={projectId}
            fileAssetType={EFileAssetType.PROJECT_DESCRIPTION}
            initialValue={overview.overview_html}
            projectId={projectId}
            workspaceSlug={workspaceSlug}
            disabled={!canEdit}
            setIsSubmitting={setSaving}
            placeholder={t("project_overview.placeholder")}
            containerClassName="min-h-64 rounded-lg border border-subtle px-4 py-3"
            onSubmit={async (value) => {
              await update({ overview_html: value.description_html });
            }}
          />
        </section>

        <aside className="flex flex-col gap-4">
          {project.milestone_view && (
            <Panel
              title={t("milestones_feature.label_plural")}
              icon={<MilestoneOutline className="size-4 text-secondary" />}
              action={
                <Link
                  href={`/${workspaceSlug}/projects/${projectId}/milestones`}
                  className="text-caption-sm-regular text-tertiary hover:text-primary"
                >
                  {t("project_overview.view_all")}
                </Link>
              }
            >
              {milestones.length === 0 && (
                <p className="text-caption-sm-regular text-tertiary">{t("milestones_feature.empty.title")}</p>
              )}
              {milestones.map((milestone) => {
                const progress = getMilestoneProgress(milestone);
                return (
                  <Link
                    key={milestone.id}
                    href={`/${workspaceSlug}/projects/${projectId}/milestones/${milestone.id}`}
                    className="flex flex-col gap-1 rounded-md px-1 py-1 hover:bg-layer-1"
                  >
                    <span className="flex items-center gap-2 text-body-xs-medium text-primary">
                      <MilestoneStatusIcon status={progress.status} className="size-3.5 shrink-0" />
                      <span className="truncate">{milestone.title}</span>
                      <span className="ml-auto shrink-0 text-caption-sm-regular text-tertiary">
                        {progress.completed}/{progress.total}
                      </span>
                    </span>
                    <LinearProgress
                      value={progress.percent}
                      size="sm"
                      variant={progress.status === "done" ? "success" : "brand"}
                      aria-label={milestone.title}
                    />
                  </Link>
                );
              })}
            </Panel>
          )}

          {project.module_view && (
            <Panel
              title={t("common.modules")}
              icon={<ModuleOutline className="size-4 text-secondary" />}
              action={
                <Link
                  href={`/${workspaceSlug}/projects/${projectId}/modules`}
                  className="text-caption-sm-regular text-tertiary hover:text-primary"
                >
                  {t("project_overview.view_all")}
                </Link>
              }
            >
              {modules.length === 0 && (
                <p className="text-caption-sm-regular text-tertiary">{t("project_overview.no_modules")}</p>
              )}
              {modules.map((module) => {
                const total = Math.max(module.total_issues - (module.cancelled_issues ?? 0), 0);
                const percent = total > 0 ? Math.round((module.completed_issues / total) * 100) : 0;
                return (
                  <Link
                    key={module.id}
                    href={`/${workspaceSlug}/projects/${projectId}/modules/${module.id}`}
                    className="flex flex-col gap-1 rounded-md px-1 py-1 hover:bg-layer-1"
                  >
                    <span className="flex items-center gap-2 text-body-xs-medium text-primary">
                      <span className="truncate">{module.name}</span>
                      <span className="ml-auto shrink-0 text-caption-sm-regular text-tertiary">
                        {module.completed_issues}/{total}
                      </span>
                    </span>
                    <LinearProgress value={percent} size="sm" variant="brand" aria-label={module.name} />
                  </Link>
                );
              })}
            </Panel>
          )}

          <Panel
            title={t("project_overview.linked_pages")}
            icon={<PagesOutline className="size-4 text-secondary" />}
            action={
              canEdit && linkablePages.length > 0 ? (
                <Menu>
                  <MenuTrigger
                    render={<Button variant="ghost" size="sm" stretch="auto" label={t("project_overview.link_page")} />}
                  />
                  <MenuContent side="bottom" align="end">
                    {linkablePages.map((page) => (
                      <MenuItem
                        key={page.id}
                        label={page.name || t("project_overview.untitled")}
                        onClick={() => void update({ overview_page_ids: [...overview.overview_page_ids, page.id!] })}
                      />
                    ))}
                  </MenuContent>
                </Menu>
              ) : undefined
            }
          >
            {overview.linked_pages.length === 0 && (
              <p className="text-caption-sm-regular text-tertiary">{t("project_overview.no_linked_pages")}</p>
            )}
            {overview.linked_pages.map((page) => (
              <div key={page.id} className="group flex items-center gap-2 rounded-md px-1 py-1 hover:bg-layer-1">
                <PagesOutline className="size-3.5 shrink-0 text-tertiary" />
                <Link
                  href={`/${workspaceSlug}/projects/${projectId}/pages/${page.id}`}
                  className={cn("min-w-0 flex-1 truncate text-body-xs-medium text-primary", {
                    "text-tertiary line-through": !!page.archived_at,
                  })}
                >
                  {page.name || t("project_overview.untitled")}
                </Link>
                {canEdit && (
                  <button
                    type="button"
                    className="hidden text-caption-sm-regular text-tertiary group-hover:block hover:text-danger-primary"
                    onClick={() =>
                      void update({
                        overview_page_ids: overview.overview_page_ids.filter((id) => id !== page.id),
                      })
                    }
                  >
                    {t("project_overview.unlink")}
                  </button>
                )}
              </div>
            ))}
          </Panel>
        </aside>
      </div>
    </div>
  );
});
