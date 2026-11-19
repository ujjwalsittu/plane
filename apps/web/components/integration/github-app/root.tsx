/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useMemo, useState } from "react";
import { sortBy } from "lodash-es";
import { observer } from "mobx-react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { Switch } from "@makeplane/propel/components/switch";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { Select } from "@plane/blocks/select";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type {
  TGitHubAvailableInstallation,
  TGitHubInstallation,
  TGitHubRepository,
  TGitHubRepositoryLink,
  TProject,
} from "@plane/types";
import { useProject } from "@/hooks/store/use-project";
import { GitHubAppService } from "@/services/github-app.service";
import { GitHubAutomations } from "./automations";
import { GitHubMarkIcon } from "./github-mark-icon";
import { GitHubPeople } from "./people";

const service = new GitHubAppService();

const errorMessage = (error: unknown) => (error as { error?: string } | undefined)?.error;

/** Workspace settings: connect GitHub accounts (app installations) and link repositories to projects. */
export const GitHubIntegrationRoot = observer(function GitHubIntegrationRoot({
  workspaceSlug,
}: {
  workspaceSlug: string;
}) {
  const { t } = useTranslation();
  const searchParams = useSearchParams();
  const { data, mutate, isLoading } = useSWR(`GITHUB_INTEGRATION_${workspaceSlug}`, () =>
    service.getIntegration(workspaceSlug)
  );
  const [connecting, setConnecting] = useState(false);
  const [toDisconnect, setToDisconnect] = useState<TGitHubInstallation | null>(null);

  // Result of the round trip through GitHub's install page.
  useEffect(() => {
    const failure = searchParams.get("github_error");
    if (failure) setToast({ type: "error", title: t("github_app.connect_error"), message: failure });
    else if (searchParams.get("github_connected")) setToast({ type: "success", title: t("github_app.connected") });
    if (failure || searchParams.get("github_connected")) {
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, [searchParams, t]);

  const handleConnect = async () => {
    setConnecting(true);
    try {
      const { url } = await service.getInstallUrl(workspaceSlug);
      window.location.assign(url);
    } catch (error) {
      setToast({ type: "error", title: errorMessage(error) ?? t("github_app.connect_error") });
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    if (!toDisconnect) return;
    try {
      await service.disconnect(workspaceSlug, toDisconnect.id);
      await mutate();
    } catch (error) {
      setToast({ type: "error", title: errorMessage(error) ?? t("github_app.save_error") });
    } finally {
      setToDisconnect(null);
    }
  };

  if (isLoading || !data) return <div className="text-body-sm-regular text-tertiary">{t("loading")}</div>;

  if (!data.configured)
    return (
      <div className="rounded-lg border border-subtle bg-surface-2 px-4 py-3">
        <p className="text-body-sm-medium text-primary">{t("github_app.not_configured_title")}</p>
        <p className="mt-1 text-body-xs-regular text-tertiary">{t("github_app.not_configured_description")}</p>
      </div>
    );

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-h5-medium text-primary">{t("github_app.accounts_title")}</h3>
            <p className="text-body-xs-regular text-tertiary">{t("github_app.accounts_description")}</p>
          </div>
          <Button
            variant="primary"
            size="md"
            stretch="auto"
            loading={connecting}
            icon={<GitHubMarkIcon className="size-3.5" />}
            label={t("github_app.connect")}
            onClick={() => void handleConnect()}
          />
        </div>
        {data.installations.length === 0 ? (
          <p className="rounded-lg border border-subtle px-4 py-3 text-body-xs-regular text-tertiary">
            {t("github_app.no_accounts")}
          </p>
        ) : (
          <div className="divide-y divide-subtle rounded-lg border border-subtle">
            {data.installations.map((installation) => (
              <div key={installation.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                {installation.account_avatar_url ? (
                  <img src={installation.account_avatar_url} alt="" className="size-6 rounded-full" />
                ) : (
                  <GitHubMarkIcon className="size-5 text-secondary" />
                )}
                <span className="text-body-sm-medium text-primary">{installation.account_login}</span>
                <span className="text-caption-md-regular text-tertiary">
                  {installation.account_type === "Organization"
                    ? t("github_app.organization")
                    : t("github_app.personal_account")}
                  {" · "}
                  {installation.repository_selection === "all"
                    ? t("github_app.all_repositories")
                    : t("github_app.selected_repositories")}
                </span>
                {installation.suspended_at && <Badge variant="warning" size="sm" label={t("github_app.suspended")} />}
                <div className="ml-auto flex items-center gap-2">
                  <a
                    href={installation.manage_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-body-xs-medium text-accent-primary hover:underline"
                  >
                    {t("github_app.manage_on_github")}
                  </a>
                  <Button
                    variant="danger-outline"
                    size="sm"
                    stretch="auto"
                    label={t("github_app.disconnect")}
                    onClick={() => setToDisconnect(installation)}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <AvailableInstallations workspaceSlug={workspaceSlug} onConnected={() => void mutate()} />

      {data.installations.length > 0 && (
        <RepositoryLinks
          workspaceSlug={workspaceSlug}
          installations={data.installations}
          links={data.links}
          onChange={() => void mutate()}
        />
      )}

      {data.links.some((link) => link.issue_sync) && <GitHubPeople workspaceSlug={workspaceSlug} />}

      {data.links.length > 0 && (
        <GitHubAutomations
          workspaceSlug={workspaceSlug}
          refreshKey={data.links.map((link) => link.project).join(",")}
        />
      )}

      <ConfirmDialog
        isOpen={!!toDisconnect}
        handleClose={() => setToDisconnect(null)}
        handleSubmit={handleDisconnect}
        isSubmitting={false}
        title={t("github_app.disconnect_title")}
        content={t("github_app.disconnect_description", { account: toDisconnect?.account_login ?? "" })}
      />
    </div>
  );
});

/** Installations of the app made from GitHub directly, which Plane's install link didn't see. */
function AvailableInstallations({ workspaceSlug, onConnected }: { workspaceSlug: string; onConnected: () => void }) {
  const { t } = useTranslation();
  const { data, mutate } = useSWR(`GITHUB_AVAILABLE_INSTALLATIONS_${workspaceSlug}`, () =>
    service.listAvailableInstallations(workspaceSlug)
  );
  const [busy, setBusy] = useState<number | null>(null);

  if (!data || data.length === 0) return null;

  const connect = async (installation: TGitHubAvailableInstallation) => {
    setBusy(installation.installation_id);
    try {
      await service.connectInstallation(workspaceSlug, installation.installation_id);
      setToast({ type: "success", title: t("github_app.connected") });
      await mutate();
      onConnected();
    } catch (error) {
      setToast({ type: "error", title: errorMessage(error) ?? t("github_app.connect_error") });
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="flex flex-col gap-3">
      <div>
        <h3 className="text-h5-medium text-primary">{t("github_app.available_title")}</h3>
        <p className="text-body-xs-regular text-tertiary">{t("github_app.available_description")}</p>
      </div>
      <div className="divide-y divide-subtle rounded-lg border border-subtle">
        {data.map((installation) => (
          <div key={installation.installation_id} className="flex flex-wrap items-center gap-3 px-4 py-3">
            {installation.account_avatar_url ? (
              <img src={installation.account_avatar_url} alt="" className="size-6 rounded-full" />
            ) : (
              <GitHubMarkIcon className="size-5 text-secondary" />
            )}
            <span className="text-body-sm-medium text-primary">{installation.account_login}</span>
            <span className="text-caption-md-regular text-tertiary">
              {installation.account_type === "Organization"
                ? t("github_app.organization")
                : t("github_app.personal_account")}
            </span>
            <div className="ml-auto">
              <Button
                variant="secondary"
                size="sm"
                stretch="auto"
                loading={busy === installation.installation_id}
                label={t("github_app.connect_account")}
                onClick={() => void connect(installation)}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

type TRepoOption = TGitHubRepository & { installation: string };

// The same repository can be visible through two installations.
const repoKey = (repo: TRepoOption) => `${repo.installation}:${repo.id}`;

const RepositoryLinks = observer(function RepositoryLinks(props: {
  workspaceSlug: string;
  installations: TGitHubInstallation[];
  links: TGitHubRepositoryLink[];
  onChange: () => void;
}) {
  const { workspaceSlug, installations, links, onChange } = props;
  const { t } = useTranslation();
  const { workspaceProjectIds, getProjectById } = useProject();
  const [repositoryKey, setRepositoryKey] = useState<string | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const active = installations.filter((installation) => !installation.suspended_at);
  const { data: repositories, error: repositoriesError } = useSWR(
    `GITHUB_REPOSITORIES_${workspaceSlug}_${active.map((i) => i.id).join(",")}`,
    async () => {
      const lists = await Promise.all(
        active.map(async (installation) =>
          (await service.listRepositories(workspaceSlug, installation.id)).map(
            (repo): TRepoOption => Object.assign(repo, { installation: installation.id })
          )
        )
      );
      return sortBy(lists.flat(), (repo) => repo.full_name.toLowerCase());
    }
  );

  const projects = useMemo(
    () =>
      sortBy(
        (workspaceProjectIds ?? []).map((id) => getProjectById(id)).filter((p): p is TProject => !!p && !p.archived_at),
        (p) => p.name.toLowerCase()
      ),
    [workspaceProjectIds, getProjectById]
  );

  const repository = repositories?.find((repo) => repoKey(repo) === repositoryKey) ?? null;
  const project = projects.find((p) => p.id === projectId) ?? null;

  const handleLink = async () => {
    if (!repository || !project) return;
    setSubmitting(true);
    try {
      await service.linkRepository(workspaceSlug, {
        installation: repository.installation,
        project: project.id,
        repository_id: repository.id,
      });
      setRepositoryKey(null);
      onChange();
    } catch (error) {
      setToast({ type: "error", title: errorMessage(error) ?? t("github_app.save_error") });
    } finally {
      setSubmitting(false);
    }
  };

  const handleIssueSync = async (link: TGitHubRepositoryLink, value: boolean) => {
    try {
      await service.setIssueSync(workspaceSlug, link.id, value);
      if (value) setToast({ type: "success", title: t("github_app.sync_issues_on"), message: link.full_name });
      onChange();
    } catch (error) {
      setToast({ type: "error", title: errorMessage(error) ?? t("github_app.save_error") });
    }
  };

  const handleSync = async (link: TGitHubRepositoryLink) => {
    try {
      await service.syncRepository(workspaceSlug, link.id);
      setToast({ type: "success", title: t("github_app.sync_started"), message: link.full_name });
    } catch (error) {
      setToast({ type: "error", title: errorMessage(error) ?? t("github_app.save_error") });
    }
  };

  const handleUnlink = async (link: TGitHubRepositoryLink) => {
    try {
      await service.unlinkRepository(workspaceSlug, link.id);
      onChange();
    } catch (error) {
      setToast({ type: "error", title: errorMessage(error) ?? t("github_app.save_error") });
    }
  };

  return (
    <section className="flex flex-col gap-3">
      <div>
        <h3 className="text-h5-medium text-primary">{t("github_app.links_title")}</h3>
        <p className="text-body-xs-regular text-tertiary">{t("github_app.links_description")}</p>
      </div>
      {links.length > 0 && (
        <div className="divide-y divide-subtle rounded-lg border border-subtle">
          {links.map((link) => {
            const linkedProject = getProjectById(link.project);
            return (
              <div key={link.id} className="flex flex-wrap items-center gap-2 px-4 py-3">
                <GitHubMarkIcon className="size-4 text-secondary" />
                <a
                  href={link.html_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-body-sm-medium text-primary hover:underline"
                >
                  {link.full_name}
                </a>
                {link.is_private && <Badge variant="neutral" size="sm" label={t("github_app.private")} />}
                <span className="text-caption-md-regular text-tertiary">→</span>
                <span className="text-body-sm-regular text-secondary">
                  {linkedProject ? `${linkedProject.name} (${linkedProject.identifier})` : link.project}
                </span>
                <div className="ml-auto flex items-center gap-1">
                  <span className="text-caption-md-regular text-tertiary" title={t("github_app.sync_issues_hint")}>
                    {t("github_app.sync_issues")}
                  </span>
                  <Switch
                    size="sm"
                    checked={link.issue_sync}
                    onCheckedChange={(checked) => void handleIssueSync(link, checked)}
                    aria-label={t("github_app.sync_issues_hint")}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    stretch="auto"
                    label={t("github_app.sync")}
                    onClick={() => void handleSync(link)}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    stretch="auto"
                    label={t("github_app.unlink")}
                    onClick={() => void handleUnlink(link)}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
      {repositoriesError ? (
        <p className="text-body-xs-regular text-danger-primary">
          {errorMessage(repositoriesError) ?? t("github_app.repositories_error")}
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-56 flex-1">
            <Select<TRepoOption>
              getValues={() => repositories ?? []}
              value={repository}
              onChange={(next) => setRepositoryKey(next)}
              getOptionValue={repoKey}
              getOptionLabel={(option) => option.full_name}
              pinSelected={false}
              placeholder={repositories ? t("github_app.choose_repository") : t("loading")}
            >
              <Select.Trigger variant="select-lg">
                <Select.Value />
              </Select.Trigger>
            </Select>
          </div>
          <div className="min-w-56 flex-1">
            <Select<TProject>
              getValues={() => projects}
              value={project}
              onChange={(next) => setProjectId(next)}
              getOptionValue={(option) => option.id}
              getOptionLabel={(option) => `${option.name} (${option.identifier})`}
              pinSelected={false}
              placeholder={t("github_app.choose_project")}
            >
              <Select.Trigger variant="select-lg">
                <Select.Value />
              </Select.Trigger>
            </Select>
          </div>
          <Button
            variant="primary"
            size="lg"
            stretch="auto"
            loading={submitting}
            disabled={!repository || !project}
            label={t("github_app.link")}
            onClick={() => void handleLink()}
          />
        </div>
      )}
    </section>
  );
});
