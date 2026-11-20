/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
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
import type { TProject, TTeamWorkItem } from "@plane/types";
import { EFileAssetType } from "@plane/types";
import { renderFormattedDate } from "@plane/utils";
import { PageHead } from "@/components/core/page-title";
import { DescriptionInput } from "@/components/editor/rich-text/description-input/root";
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";
import { IssueService } from "@/services/issue/issue.service";
import type { TTeamWorkFilters } from "@/services/teamspace.service";
import { TeamspaceService } from "@/services/teamspace.service";
import type { TMemberOption } from "./common";
import { getTeamKey, getTeamsKey, MemberAvatar, useMemberOptions } from "./common";

const service = new TeamspaceService();
const issueService = new IssueService();

const OPEN_GROUPS = "backlog,unstarted,started";
type TOption = { id: string; name: string };

const errorMessage = (error: unknown) => (error as { error?: string } | undefined)?.error;

/** One team: its lead, members, projects, workload and work. */
export const TeamDetail = observer(function TeamDetail(props: { workspaceSlug: string; teamId: string }) {
  const { workspaceSlug, teamId } = props;
  const { t } = useTranslation();
  const router = useAppRouter();
  const { allowPermissions } = useUserPermissions();
  const { workspaceProjectIds, getProjectById } = useProject();
  const canEdit = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.WORKSPACE,
    workspaceSlug
  );
  const members = useMemberOptions();
  const { data: team, error, mutate } = useSWR(getTeamKey(teamId), () => service.retrieve(workspaceSlug, teamId));
  const { data: workload, mutate: mutateWorkload } = useSWR(`${getTeamKey(teamId)}_WORKLOAD`, () =>
    service.workload(workspaceSlug, teamId)
  );
  const [name, setName] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [workVersion, setWorkVersion] = useState(0);

  const projects = useMemo(
    () =>
      (workspaceProjectIds ?? []).map((id) => getProjectById(id)).filter((p): p is TProject => !!p && !p.archived_at),
    [workspaceProjectIds, getProjectById]
  );

  if (error) return <p className="px-6 py-6 text-body-sm-regular text-tertiary">{t("teams.not_found")}</p>;
  if (!team) return null;

  const teamMembers = team.member_ids
    .map((id) => members.find((m) => m.id === id))
    .filter((m): m is TMemberOption => !!m);
  const otherMembers = members.filter((m) => !team.member_ids.includes(m.id));
  const teamProjects = projects.filter((p) => team.project_ids.includes(p.id));
  const otherProjects = projects.filter((p) => !team.project_ids.includes(p.id));
  const lead = members.find((m) => m.id === team.lead) ?? null;

  const refresh = async () => {
    await Promise.all([mutate(), mutateWorkload(), globalMutate(getTeamsKey(workspaceSlug))]);
    setWorkVersion((v) => v + 1);
  };
  const run = async (action: () => Promise<unknown>) => {
    try {
      await action();
      await refresh();
    } catch (err) {
      setToast({ type: "error", title: errorMessage(err) ?? t("teams.save_error") });
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-6 py-6">
      <PageHead title={`${team.name} - ${t("teams.title")}`} />
      <section className="flex flex-col gap-3">
        <InputField
          size="xl"
          orientation="vertical"
          value={name ?? team.name}
          maxLength={255}
          disabled={!canEdit}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => {
            if (name !== null && name.trim() && name.trim() !== team.name)
              void run(() => service.update(workspaceSlug, teamId, { name: name.trim() }));
            setName(null);
          }}
          aria-label={t("teams.name_placeholder")}
        />
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-caption-md-regular text-tertiary">{t("teams.lead")}</span>
          <div className="w-48">
            <Select<TMemberOption>
              getValues={() => members}
              value={lead}
              onChange={(next) => void run(() => service.update(workspaceSlug, teamId, { lead: next || null }))}
              getOptionValue={(option) => option.id}
              getOptionLabel={(option) => option.name}
              pinSelected={false}
              disabled={!canEdit}
              placeholder={t("teams.no_lead")}
            >
              <Select.Trigger variant="select-ghost-md" aria-label={t("teams.lead")}>
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
                label={t("teams.delete")}
                onClick={() => setIsDeleting(true)}
              />
            </div>
          )}
        </div>
        <DescriptionInput
          key={`team-${team.id}`}
          entityId={team.id}
          fileAssetType={EFileAssetType.PROJECT_DESCRIPTION}
          initialValue={team.description_html}
          workspaceSlug={workspaceSlug}
          disabled={!canEdit}
          disabledExtensions={["image"]}
          setIsSubmitting={() => {}}
          placeholder={t("teams.description_placeholder")}
          containerClassName="min-h-16 rounded-lg border border-subtle px-4 py-3"
          onSubmit={async (value) => {
            await service.update(workspaceSlug, teamId, { description_html: value.description_html });
          }}
        />
      </section>

      <div className="grid gap-6 md:grid-cols-2">
        <section className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <h3 className="flex-1 text-h5-medium text-primary">{t("teams.members")}</h3>
            {canEdit && otherMembers.length > 0 && (
              <div className="w-48">
                <Select<TMemberOption>
                  getValues={() => otherMembers}
                  value={null}
                  onChange={(next) => {
                    if (next) void run(() => service.addMembers(workspaceSlug, teamId, [next]));
                  }}
                  getOptionValue={(option) => option.id}
                  getOptionLabel={(option) => option.name}
                  pinSelected={false}
                  placeholder={t("teams.add_member")}
                >
                  <Select.Trigger variant="select-md" aria-label={t("teams.add_member")}>
                    <Select.Value />
                  </Select.Trigger>
                </Select>
              </div>
            )}
          </div>
          <div className="divide-y divide-subtle rounded-lg border border-subtle">
            {teamMembers.map((member) => {
              const load = workload?.members.find((row) => row.member_id === member.id);
              return (
                <div key={member.id} className="flex items-center gap-3 px-3 py-2">
                  <MemberAvatar member={member} />
                  <span className="min-w-0 flex-1 truncate text-body-xs-medium text-primary">
                    {member.name}
                    {member.id === team.lead && (
                      <span className="ml-2 text-caption-md-regular text-tertiary">{t("teams.lead")}</span>
                    )}
                  </span>
                  {load && (
                    <span className="text-caption-md-regular text-tertiary">
                      {t("teams.member_load", { open: load.open, started: load.started })}
                    </span>
                  )}
                  {canEdit && member.id !== team.lead && (
                    <Button
                      variant="ghost"
                      size="sm"
                      stretch="auto"
                      label={t("teams.remove")}
                      onClick={() => void run(() => service.removeMembers(workspaceSlug, teamId, [member.id]))}
                    />
                  )}
                </div>
              );
            })}
            {teamMembers.length === 0 && (
              <p className="px-3 py-3 text-body-xs-regular text-tertiary">{t("teams.no_members")}</p>
            )}
          </div>
        </section>

        <section className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <h3 className="flex-1 text-h5-medium text-primary">{t("teams.projects")}</h3>
            {canEdit && otherProjects.length > 0 && (
              <div className="w-48">
                <Select<TProject>
                  getValues={() => otherProjects}
                  value={null}
                  onChange={(next) => {
                    if (next) void run(() => service.addProjects(workspaceSlug, teamId, [next]));
                  }}
                  getOptionValue={(option) => option.id}
                  getOptionLabel={(option) => `${option.name} (${option.identifier})`}
                  pinSelected={false}
                  placeholder={t("teams.add_project")}
                >
                  <Select.Trigger variant="select-md" aria-label={t("teams.add_project")}>
                    <Select.Value />
                  </Select.Trigger>
                </Select>
              </div>
            )}
          </div>
          <div className="divide-y divide-subtle rounded-lg border border-subtle">
            {teamProjects.map((project) => (
              <div key={project.id} className="flex items-center gap-3 px-3 py-2">
                <Logo logo={project.logo_props} size={16} />
                <span className="min-w-0 flex-1 truncate text-body-xs-medium text-primary">{project.name}</span>
                <span className="text-caption-md-regular text-tertiary">{project.identifier}</span>
                {canEdit && (
                  <Button
                    variant="ghost"
                    size="sm"
                    stretch="auto"
                    label={t("teams.remove")}
                    onClick={() => void run(() => service.removeProjects(workspaceSlug, teamId, [project.id]))}
                  />
                )}
              </div>
            ))}
            {teamProjects.length === 0 && (
              <p className="px-3 py-3 text-body-xs-regular text-tertiary">{t("teams.no_projects")}</p>
            )}
          </div>
        </section>
      </div>

      <TeamWork
        version={workVersion}
        workspaceSlug={workspaceSlug}
        teamId={teamId}
        teamMembers={teamMembers}
        hasProjects={team.project_ids.length > 0}
        unassignedOpen={workload?.unassigned_open ?? 0}
        canAssign={canEdit}
        onAssigned={refresh}
      />

      <ConfirmDialog
        isOpen={isDeleting}
        handleClose={() => setIsDeleting(false)}
        handleSubmit={async () => {
          try {
            await service.remove(workspaceSlug, teamId);
            await globalMutate(getTeamsKey(workspaceSlug));
            router.push(`/${workspaceSlug}/teams`);
          } catch {
            setToast({ type: "error", title: t("teams.save_error") });
          } finally {
            setIsDeleting(false);
          }
        }}
        isSubmitting={false}
        title={t("teams.delete")}
        content={t("teams.delete_description")}
      />
    </div>
  );
});

function TeamWork(props: {
  version: number;
  workspaceSlug: string;
  teamId: string;
  teamMembers: TMemberOption[];
  hasProjects: boolean;
  unassignedOpen: number;
  canAssign: boolean;
  onAssigned: () => Promise<void>;
}) {
  const { version, workspaceSlug, teamId, teamMembers, hasProjects, unassignedOpen, canAssign, onAssigned } = props;
  const { t } = useTranslation();
  const [chosenView, setView] = useState<"assigned" | "unassigned">("assigned");
  // Unassigned work needs team projects; fall back when the last one is removed.
  const view = hasProjects ? chosenView : "assigned";
  const [memberId, setMemberId] = useState<string | null>(null);
  const [openOnly, setOpenOnly] = useState(true);
  const filters: TTeamWorkFilters = {
    view,
    state_group: openOnly ? OPEN_GROUPS : undefined,
    member_id: view === "assigned" ? (memberId ?? undefined) : undefined,
  };
  const { data: items, mutate } = useSWR(`${getTeamKey(teamId)}_WORK_${version}_${JSON.stringify(filters)}`, () =>
    service.workItems(workspaceSlug, teamId, filters)
  );
  const statusOptions: TOption[] = [
    { id: "open", name: t("teams.filter_open") },
    { id: "all", name: t("teams.filter_all") },
  ];
  const everyone: TMemberOption = { id: "", name: t("teams.filter_everyone"), avatar: "" };
  const memberOptions = [everyone, ...teamMembers];

  const assign = async (item: TTeamWorkItem, assigneeId: string) => {
    try {
      await issueService.patchIssue(workspaceSlug, item.project_id, item.id, { assignee_ids: [assigneeId] });
      await mutate();
      await onAssigned();
    } catch {
      setToast({ type: "error", title: t("teams.assign_error") });
    }
  };

  const tab = (value: "assigned" | "unassigned", label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={view === value}
      onClick={() => setView(value)}
      className={`rounded-md border px-3 py-1.5 text-body-xs-medium ${
        view === value ? "border-strong bg-layer-1 text-primary" : "border-subtle text-secondary hover:bg-layer-1"
      }`}
    >
      {label}
    </button>
  );

  return (
    <section className="flex flex-col gap-3">
      <div>
        <h3 className="text-h5-medium text-primary">{t("teams.work")}</h3>
        <p className="text-body-xs-regular text-tertiary">
          {hasProjects ? t("teams.work_description_projects") : t("teams.work_description_all")}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2" role="tablist">
          {tab("assigned", t("teams.view_assigned"))}
          {hasProjects && tab("unassigned", t("teams.view_unassigned", { count: unassignedOpen }))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          {view === "assigned" && (
            <div className="w-40">
              <Select<TMemberOption>
                getValues={() => memberOptions}
                value={memberOptions.find((m) => m.id === (memberId ?? "")) ?? everyone}
                onChange={(next) => setMemberId(next || null)}
                getOptionValue={(option) => option.id || "everyone"}
                getOptionLabel={(option) => option.name}
                pinSelected={false}
              >
                <Select.Trigger variant="select-md" aria-label={t("teams.filter_member")}>
                  <Select.Value />
                </Select.Trigger>
              </Select>
            </div>
          )}
          <div className="w-32">
            <Select<TOption>
              getValues={() => statusOptions}
              value={statusOptions[openOnly ? 0 : 1]}
              onChange={(next) => setOpenOnly(next !== "all")}
              getOptionValue={(option) => option.id}
              getOptionLabel={(option) => option.name}
              pinSelected={false}
            >
              <Select.Trigger variant="select-md" aria-label={t("teams.filter_status")}>
                <Select.Value />
              </Select.Trigger>
            </Select>
          </div>
        </div>
      </div>

      {items && items.length === 0 && (
        <p className="rounded-lg border border-subtle px-4 py-6 text-center text-body-xs-regular text-tertiary">
          {view === "assigned" ? t("teams.no_work") : t("teams.no_unassigned")}
        </p>
      )}
      {items && items.length > 0 && (
        <div className="divide-y divide-subtle rounded-lg border border-subtle">
          {items.map((item) => {
            const identifier = `${item.project_identifier}-${item.sequence_id}`;
            return (
              <div key={item.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5">
                <span className="font-mono w-20 shrink-0 text-caption-md-medium text-tertiary">{identifier}</span>
                <Link
                  href={`/${workspaceSlug}/browse/${identifier}/`}
                  className="min-w-0 flex-1 truncate text-body-xs-medium text-primary hover:underline"
                >
                  {item.name}
                </Link>
                {item.target_date && (
                  <span className="text-caption-md-regular text-tertiary">{renderFormattedDate(item.target_date)}</span>
                )}
                <span className="w-24 truncate text-caption-md-regular text-secondary">{item.state_name}</span>
                {view === "assigned" ? (
                  <div className="flex w-20 justify-end gap-1">
                    {item.assignee_ids
                      .map((id) => teamMembers.find((m) => m.id === id))
                      .filter((m): m is TMemberOption => !!m)
                      .slice(0, 3)
                      .map((m) => (
                        <MemberAvatar key={m.id} member={m} size="xs" />
                      ))}
                  </div>
                ) : (
                  canAssign && (
                    <div className="w-40">
                      <Select<TMemberOption>
                        getValues={() => teamMembers}
                        value={null}
                        onChange={(next) => {
                          if (next) void assign(item, next);
                        }}
                        getOptionValue={(option) => option.id}
                        getOptionLabel={(option) => option.name}
                        pinSelected={false}
                        placeholder={t("teams.assign")}
                      >
                        <Select.Trigger variant="select-md" aria-label={t("teams.assign")}>
                          <Select.Value />
                        </Select.Trigger>
                      </Select>
                    </div>
                  )
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
