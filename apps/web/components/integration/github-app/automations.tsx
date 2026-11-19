/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
import { Switch } from "@makeplane/propel/components/switch";
import { Select } from "@plane/blocks/select";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { IState, TGitHubAutomation, TGitHubAutomationRule } from "@plane/types";
import { useProject } from "@/hooks/store/use-project";
import { useProjectState } from "@/hooks/store/use-project-state";
import { GitHubAppService } from "@/services/github-app.service";

const service = new GitHubAppService();

const RULES: TGitHubAutomationRule[] = ["draft_state", "open_state", "review_requested_state", "merge_state"];

/** Per project: which state a work item moves to on each pull request event. */
export function GitHubAutomations({ workspaceSlug, refreshKey }: { workspaceSlug: string; refreshKey: string }) {
  const { t } = useTranslation();
  const { data, mutate } = useSWR(`GITHUB_AUTOMATIONS_${workspaceSlug}_${refreshKey}`, () =>
    service.listAutomations(workspaceSlug)
  );
  if (!data || data.length === 0) return null;

  const save = async (projectId: string, change: Partial<TGitHubAutomation>) => {
    try {
      const updated = await service.updateAutomation(workspaceSlug, projectId, change);
      await mutate((rows) => rows?.map((row) => (row.project === projectId ? updated : row)), { revalidate: false });
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error;
      setToast({ type: "error", title: message ?? t("github_app.save_error") });
    }
  };

  return (
    <section className="flex flex-col gap-3">
      <div>
        <h3 className="text-h5-medium text-primary">{t("github_app.automations.title")}</h3>
        <p className="text-body-xs-regular text-tertiary">{t("github_app.automations.description")}</p>
      </div>
      <div className="flex flex-col gap-3">
        {data.map((rules) => (
          <ProjectRules
            key={rules.project}
            workspaceSlug={workspaceSlug}
            rules={rules}
            onChange={(change) => void save(rules.project, change)}
          />
        ))}
      </div>
    </section>
  );
}

const ProjectRules = observer(function ProjectRules(props: {
  workspaceSlug: string;
  rules: TGitHubAutomation;
  onChange: (change: Partial<TGitHubAutomation>) => void;
}) {
  const { workspaceSlug, rules, onChange } = props;
  const { t } = useTranslation();
  const { getProjectById } = useProject();
  const { getProjectStates, fetchProjectStates } = useProjectState();
  const project = getProjectById(rules.project);
  const states = getProjectStates(rules.project) ?? [];

  useEffect(() => {
    if (!getProjectStates(rules.project)) void fetchProjectStates(workspaceSlug, rules.project);
  }, [workspaceSlug, rules.project, getProjectStates, fetchProjectStates]);

  return (
    <div className="rounded-lg border border-subtle">
      <div className="flex items-center gap-3 border-b border-subtle px-4 py-3">
        <span className="text-body-sm-medium text-primary">
          {project ? `${project.name} (${project.identifier})` : rules.project}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-caption-md-regular text-tertiary">{t("github_app.automations.enabled")}</span>
          <Switch
            size="sm"
            checked={rules.enabled}
            onCheckedChange={(checked) => onChange({ enabled: checked })}
            aria-label={t("github_app.automations.enabled")}
          />
        </div>
      </div>
      <div className={rules.enabled ? "flex flex-col gap-2 px-4 py-3" : "flex flex-col gap-2 px-4 py-3 opacity-60"}>
        {RULES.map((rule) => (
          <div key={rule} className="flex flex-wrap items-center gap-3">
            <span className="w-48 text-body-xs-regular text-secondary">
              {t(`github_app.automations.rules.${rule}`)}
            </span>
            <div className="min-w-48 flex-1">
              <Select<IState | { id: ""; name: string }>
                getValues={() => [{ id: "", name: t("github_app.automations.no_change") }, ...states]}
                value={
                  states.find((s) => s.id === rules[rule]) ?? { id: "", name: t("github_app.automations.no_change") }
                }
                onChange={(next) => onChange({ [rule]: next || null })}
                getOptionValue={(option) => option.id}
                getOptionLabel={(option) => option.name}
                showSearch={false}
                pinSelected={false}
                disabled={!rules.enabled}
              >
                <Select.Trigger variant="select-md">
                  <Select.Value />
                </Select.Trigger>
              </Select>
            </div>
          </div>
        ))}
        <div className="flex items-center gap-3 pt-1">
          <Switch
            size="sm"
            checked={rules.close_keywords}
            onCheckedChange={(checked) => onChange({ close_keywords: checked })}
            disabled={!rules.enabled}
            aria-label={t("github_app.automations.close_keywords")}
          />
          <span className="text-body-xs-regular text-secondary">{t("github_app.automations.close_keywords")}</span>
        </div>
      </div>
    </div>
  );
});
