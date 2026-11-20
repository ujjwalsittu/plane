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
import { TemplatesOutline } from "@makeplane/propel/icons";
import { Select } from "@plane/blocks/select";
import { setToast } from "@plane/blocks/toast";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import type { TProject, TTemplateKind } from "@plane/types";
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";
import { TemplateService } from "@/services/template.service";
import { getTemplatesKey, TEMPLATE_KINDS, TemplateKindIcon, useWritableProjects } from "./common";

const service = new TemplateService();

type TScope = { id: string; name: string };

/** Every template the user can see, by kind, and a form to start a new one. */
export const TemplatesRoot = observer(function TemplatesRoot({ workspaceSlug }: { workspaceSlug: string }) {
  const { t } = useTranslation();
  const router = useAppRouter();
  const { allowPermissions } = useUserPermissions();
  const { getProjectById } = useProject();
  const canEdit = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.WORKSPACE,
    workspaceSlug
  );
  const projects = useWritableProjects();
  const { data: templates } = useSWR(getTemplatesKey(workspaceSlug), () => service.list(workspaceSlug));
  const [kind, setKind] = useState<TTemplateKind>("workitem");
  const [name, setName] = useState("");
  const workspaceScope: TScope = { id: "", name: t("workspace_templates.scope_workspace") };
  const [scope, setScope] = useState<TScope>(workspaceScope);
  const [creating, setCreating] = useState(false);

  const scopes: TScope[] = [
    workspaceScope,
    ...projects.map((project: TProject) => ({ id: project.id, name: `${project.name} (${project.identifier})` })),
  ];
  const shown = (templates ?? []).filter((template) => template.kind === kind);

  const create = async () => {
    if (!name.trim()) return;
    setCreating(true);
    try {
      const created = await service.create(workspaceSlug, {
        kind,
        name: name.trim(),
        project_id: kind !== "project" && scope.id ? scope.id : null,
        template_data: {},
      });
      router.push(`/${workspaceSlug}/templates/${created.id}`);
    } catch (error) {
      setToast({ type: "error", title: (error as { error?: string })?.error ?? t("workspace_templates.save_error") });
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 py-6">
      <div className="flex flex-wrap items-center gap-2" role="tablist">
        {TEMPLATE_KINDS.map((option) => {
          const count = (templates ?? []).filter((template) => template.kind === option).length;
          const active = option === kind;
          return (
            <button
              key={option}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setKind(option)}
              className={`flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-body-xs-medium ${
                active ? "border-strong bg-layer-1 text-primary" : "border-subtle text-secondary hover:bg-layer-1"
              }`}
            >
              <TemplateKindIcon kind={option} className="size-3.5" />
              {t(`workspace_templates.kinds.${option}`)}
              <span className="text-tertiary">{count}</span>
            </button>
          );
        })}
      </div>

      {canEdit && (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void create();
          }}
        >
          <div className="min-w-60 flex-1">
            <InputField
              size="lg"
              orientation="vertical"
              value={name}
              maxLength={255}
              onChange={(e) => setName(e.target.value)}
              aria-label={t("workspace_templates.name_placeholder")}
              placeholder={t("workspace_templates.name_placeholder")}
            />
          </div>
          {kind !== "project" && (
            <div className="w-56">
              <Select<TScope>
                getValues={() => scopes}
                value={scope}
                onChange={(next) =>
                  setScope(scopes.find((option) => (option.id || "workspace") === next) ?? workspaceScope)
                }
                getOptionValue={(option) => option.id || "workspace"}
                getOptionLabel={(option) => option.name}
                pinSelected={false}
              >
                <Select.Trigger variant="select-md" aria-label={t("workspace_templates.scope")}>
                  <Select.Value />
                </Select.Trigger>
              </Select>
            </div>
          )}
          <Button
            type="submit"
            variant="primary"
            size="lg"
            stretch="auto"
            loading={creating}
            disabled={!name.trim()}
            label={t(`workspace_templates.new.${kind}`)}
          />
        </form>
      )}

      {templates && shown.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-subtle px-6 py-12 text-center">
          <TemplatesOutline className="size-8 text-tertiary" />
          <p className="text-body-sm-medium text-primary">{t(`workspace_templates.empty.${kind}`)}</p>
          <p className="max-w-md text-body-xs-regular text-tertiary">{t("workspace_templates.empty_description")}</p>
        </div>
      )}
      {shown.length > 0 && (
        <div className="divide-y divide-subtle rounded-lg border border-subtle">
          {shown.map((template) => {
            const project = template.project ? getProjectById(template.project) : undefined;
            return (
              <Link
                key={template.id}
                href={`/${workspaceSlug}/templates/${template.id}`}
                className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 hover:bg-layer-1"
              >
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <TemplateKindIcon kind={template.kind} className="size-4 shrink-0 text-tertiary" />
                  <span className="truncate text-body-sm-medium text-primary">{template.name}</span>
                  <Badge
                    variant="neutral"
                    size="sm"
                    label={project ? project.identifier : t("workspace_templates.scope_workspace")}
                  />
                </div>
                {template.description && (
                  <span className="max-w-md truncate text-caption-md-regular text-tertiary">
                    {template.description}
                  </span>
                )}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
});
