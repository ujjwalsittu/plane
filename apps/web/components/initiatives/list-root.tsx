/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR from "swr";
import { Button } from "@makeplane/propel/components/button";
import { InputField } from "@makeplane/propel/components/input-field";
import { InitiativeOutline } from "@makeplane/propel/icons";
import { setToast } from "@plane/blocks/toast";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { renderFormattedDate } from "@plane/utils";
import { useMember } from "@/hooks/store/use-member";
import { useUserPermissions } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";
import { InitiativeService } from "@/services/initiative.service";
import { getInitiativesKey, InitiativeProgressBar, InitiativeStateBadge } from "./common";

const service = new InitiativeService();

/** Every initiative of the workspace with its state, dates, lead and rolled-up progress. */
export const InitiativesRoot = observer(function InitiativesRoot({ workspaceSlug }: { workspaceSlug: string }) {
  const { t } = useTranslation();
  const router = useAppRouter();
  const { getUserDetails } = useMember();
  const { allowPermissions } = useUserPermissions();
  const canEdit = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.WORKSPACE,
    workspaceSlug
  );
  const { data: initiatives, mutate } = useSWR(getInitiativesKey(workspaceSlug), () => service.list(workspaceSlug));
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);

  const create = async () => {
    if (!name.trim()) return;
    setCreating(true);
    try {
      const created = await service.create(workspaceSlug, { name: name.trim() });
      setName("");
      await mutate();
      router.push(`/${workspaceSlug}/initiatives/${created.id}`);
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error;
      setToast({ type: "error", title: message ?? t("initiatives.save_error") });
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
              aria-label={t("initiatives.name_placeholder")}
              placeholder={t("initiatives.name_placeholder")}
            />
          </div>
          <Button
            type="submit"
            variant="primary"
            size="lg"
            stretch="auto"
            loading={creating}
            disabled={!name.trim()}
            label={t("initiatives.new")}
          />
        </form>
      )}
      {initiatives && initiatives.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-subtle px-6 py-12 text-center">
          <InitiativeOutline className="size-8 text-tertiary" />
          <p className="text-body-sm-medium text-primary">{t("initiatives.empty_title")}</p>
          <p className="max-w-md text-body-xs-regular text-tertiary">{t("initiatives.empty_description")}</p>
        </div>
      )}
      {initiatives && initiatives.length > 0 && (
        <div className="divide-y divide-subtle rounded-lg border border-subtle">
          {initiatives.map((initiative) => {
            const lead = initiative.lead ? getUserDetails(initiative.lead) : undefined;
            const dates = [initiative.start_date, initiative.end_date]
              .map((value) => (value ? renderFormattedDate(value) : null))
              .filter(Boolean)
              .join(" → ");
            return (
              <Link
                key={initiative.id}
                href={`/${workspaceSlug}/initiatives/${initiative.id}`}
                className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 hover:bg-layer-1"
              >
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <InitiativeOutline className="size-4 shrink-0 text-tertiary" />
                  <span className="truncate text-body-sm-medium text-primary">{initiative.name}</span>
                  <InitiativeStateBadge state={initiative.state} />
                </div>
                <span className="text-caption-md-regular text-tertiary">
                  {t("initiatives.projects")}: {initiative.project_ids.length}
                </span>
                {dates && <span className="text-caption-md-regular text-tertiary">{dates}</span>}
                {lead && <span className="text-caption-md-regular text-secondary">{lead.display_name}</span>}
                <div className="w-64">
                  <InitiativeProgressBar progress={initiative.progress} label={initiative.name} />
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
});
