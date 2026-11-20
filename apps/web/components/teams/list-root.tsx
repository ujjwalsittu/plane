/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR from "swr";
import { AvatarGroup } from "@makeplane/propel/components/avatar-group";
import { Button } from "@makeplane/propel/components/button";
import { InputField } from "@makeplane/propel/components/input-field";
import { TeamspacesOutline } from "@makeplane/propel/icons";
import { setToast } from "@plane/blocks/toast";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { useUserPermissions } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";
import { TeamspaceService } from "@/services/teamspace.service";
import { getTeamsKey, MemberAvatar, useMemberOptions } from "./common";

const service = new TeamspaceService();

/** Every team in the workspace, and a form to start one. */
export const TeamsRoot = observer(function TeamsRoot({ workspaceSlug }: { workspaceSlug: string }) {
  const { t } = useTranslation();
  const router = useAppRouter();
  const { allowPermissions } = useUserPermissions();
  const canEdit = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.WORKSPACE,
    workspaceSlug
  );
  const members = useMemberOptions();
  const { data: teams } = useSWR(getTeamsKey(workspaceSlug), () => service.list(workspaceSlug));
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);

  const create = async () => {
    if (!name.trim()) return;
    setCreating(true);
    try {
      const created = await service.create(workspaceSlug, { name: name.trim() });
      router.push(`/${workspaceSlug}/teams/${created.id}`);
    } catch (error) {
      setToast({ type: "error", title: (error as { error?: string })?.error ?? t("teams.save_error") });
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 py-6">
      {canEdit && (
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void create();
          }}
        >
          <div className="flex-1">
            <InputField
              size="lg"
              orientation="vertical"
              value={name}
              maxLength={255}
              onChange={(e) => setName(e.target.value)}
              aria-label={t("teams.name_placeholder")}
              placeholder={t("teams.name_placeholder")}
            />
          </div>
          <Button
            type="submit"
            variant="primary"
            size="lg"
            stretch="auto"
            loading={creating}
            disabled={!name.trim()}
            label={t("teams.new")}
          />
        </form>
      )}

      {teams && teams.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-subtle px-6 py-12 text-center">
          <TeamspacesOutline className="size-8 text-tertiary" />
          <p className="text-body-sm-medium text-primary">{t("teams.empty_title")}</p>
          <p className="max-w-md text-body-xs-regular text-tertiary">{t("teams.empty_description")}</p>
        </div>
      )}
      {teams && teams.length > 0 && (
        <div className="divide-y divide-subtle rounded-lg border border-subtle">
          {teams.map((team) => {
            const lead = members.find((m) => m.id === team.lead);
            return (
              <Link
                key={team.id}
                href={`/${workspaceSlug}/teams/${team.id}`}
                className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 hover:bg-layer-1"
              >
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <TeamspacesOutline className="size-4 shrink-0 text-tertiary" />
                  <span className="truncate text-body-sm-medium text-primary">{team.name}</span>
                  {lead && (
                    <span className="text-caption-md-regular text-tertiary">
                      {t("teams.led_by", { name: lead.name })}
                    </span>
                  )}
                </div>
                <span className="text-caption-md-regular text-tertiary">
                  {t("teams.project_count", { count: team.project_ids.length })}
                </span>
                <div className="flex w-32 items-center justify-end gap-2">
                  <AvatarGroup size="xs" max={4}>
                    {team.member_ids.map((id) => (
                      <MemberAvatar key={id} member={members.find((m) => m.id === id)} size="xs" />
                    ))}
                  </AvatarGroup>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
});
