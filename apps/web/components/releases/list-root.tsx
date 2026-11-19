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
import { ReleasesOutline } from "@makeplane/propel/icons";
import { setToast } from "@plane/blocks/toast";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { renderFormattedDate } from "@plane/utils";
import { useUserPermissions } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";
import { ReleaseService } from "@/services/release.service";
import { getReleaseLabelsKey, getReleasesKey, getReleaseTagsKey, ReleaseLabelChip, ReleaseStatusBadge } from "./common";

const service = new ReleaseService();

const errorMessage = (error: unknown) => (error as { error?: string } | undefined)?.error;

/** Every release of the workspace, plus the shared tag and label palette. */
export const ReleasesRoot = observer(function ReleasesRoot({ workspaceSlug }: { workspaceSlug: string }) {
  const { t } = useTranslation();
  const router = useAppRouter();
  const { allowPermissions } = useUserPermissions();
  const canEdit = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.WORKSPACE,
    workspaceSlug
  );
  const { data: releases, mutate } = useSWR(getReleasesKey(workspaceSlug), () => service.list(workspaceSlug));
  const { data: labels } = useSWR(getReleaseLabelsKey(workspaceSlug), () => service.listLabels(workspaceSlug));
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);

  const create = async () => {
    if (!name.trim()) return;
    setCreating(true);
    try {
      const created = await service.create(workspaceSlug, { name: name.trim() });
      setName("");
      await mutate();
      router.push(`/${workspaceSlug}/releases/${created.id}`);
    } catch (error) {
      setToast({ type: "error", title: errorMessage(error) ?? t("releases.save_error") });
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
              aria-label={t("releases.name_placeholder")}
              placeholder={t("releases.name_placeholder")}
            />
          </div>
          <Button
            type="submit"
            variant="primary"
            size="lg"
            stretch="auto"
            loading={creating}
            disabled={!name.trim()}
            label={t("releases.new")}
          />
        </form>
      )}

      {releases && releases.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-subtle px-6 py-12 text-center">
          <ReleasesOutline className="size-8 text-tertiary" />
          <p className="text-body-sm-medium text-primary">{t("releases.empty_title")}</p>
          <p className="max-w-md text-body-xs-regular text-tertiary">{t("releases.empty_description")}</p>
        </div>
      )}
      {releases && releases.length > 0 && (
        <div className="divide-y divide-subtle rounded-lg border border-subtle">
          {releases.map((release) => (
            <Link
              key={release.id}
              href={`/${workspaceSlug}/releases/${release.id}`}
              className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 hover:bg-layer-1"
            >
              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                <ReleasesOutline className="size-4 shrink-0 text-tertiary" />
                <span className="truncate text-body-sm-medium text-primary">{release.name}</span>
                {release.tag_version && (
                  <span className="font-mono text-caption-md-medium text-secondary">{release.tag_version}</span>
                )}
                <ReleaseStatusBadge status={release.status} />
                {release.is_latest && <Badge variant="success" size="sm" label={t("releases.latest")} />}
                {release.is_prerelease && <Badge variant="warning" size="sm" label={t("releases.prerelease")} />}
                {(labels ?? [])
                  .filter((label) => release.label_ids.includes(label.id))
                  .map((label) => (
                    <ReleaseLabelChip key={label.id} label={label} />
                  ))}
              </div>
              {release.release_date && (
                <span className="text-caption-md-regular text-tertiary">
                  {renderFormattedDate(release.release_date)}
                </span>
              )}
              <div className="flex w-48 items-center gap-2">
                <div className="flex-1">
                  <LinearProgress
                    value={release.progress.percent}
                    size="sm"
                    variant="brand"
                    aria-label={release.name}
                  />
                </div>
                <span className="w-10 text-right text-caption-md-regular text-tertiary">
                  {release.progress.completed}/{release.progress.total - release.progress.cancelled}
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}

      {canEdit && <ReleasePalette workspaceSlug={workspaceSlug} />}
    </div>
  );
});

function ReleasePalette({ workspaceSlug }: { workspaceSlug: string }) {
  const { t } = useTranslation();
  const { data: tags, mutate: mutateTags } = useSWR(getReleaseTagsKey(workspaceSlug), () =>
    service.listTags(workspaceSlug)
  );
  const { data: labels, mutate: mutateLabels } = useSWR(getReleaseLabelsKey(workspaceSlug), () =>
    service.listLabels(workspaceSlug)
  );
  const [version, setVersion] = useState("");
  const [labelName, setLabelName] = useState("");
  const [color, setColor] = useState("#4E5355");

  const run = async (action: () => Promise<unknown>, after: () => Promise<unknown>) => {
    try {
      await action();
      await after();
    } catch (error) {
      setToast({ type: "error", title: errorMessage(error) ?? t("releases.save_error") });
    }
  };

  return (
    <section className="flex flex-col gap-3">
      <div>
        <h3 className="text-h5-medium text-primary">{t("releases.palette_title")}</h3>
        <p className="text-body-xs-regular text-tertiary">{t("releases.palette_description")}</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="flex flex-col gap-2 rounded-lg border border-subtle p-3">
          <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!version.trim()) return;
              void run(
                () => service.createTag(workspaceSlug, { version: version.trim() }),
                async () => {
                  setVersion("");
                  await mutateTags();
                }
              );
            }}
          >
            <div className="flex-1">
              <InputField
                size="md"
                orientation="vertical"
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                aria-label={t("releases.new_tag")}
                placeholder={t("releases.new_tag")}
              />
            </div>
            <Button type="submit" variant="secondary" size="md" stretch="auto" label={t("releases.add_tag")} />
          </form>
          {(tags ?? []).length === 0 && (
            <p className="text-caption-md-regular text-tertiary">{t("releases.no_tags")}</p>
          )}
          {(tags ?? []).map((tag) => (
            <div key={tag.id} className="flex items-center gap-2">
              <span className="font-mono flex-1 text-body-xs-medium text-primary">{tag.version}</span>
              <Button
                variant="ghost"
                size="sm"
                stretch="auto"
                label={t("releases.delete_tag")}
                onClick={() =>
                  void run(
                    () => service.deleteTag(workspaceSlug, tag.id),
                    () => mutateTags()
                  )
                }
              />
            </div>
          ))}
        </div>
        <div className="flex flex-col gap-2 rounded-lg border border-subtle p-3">
          <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!labelName.trim()) return;
              void run(
                () => service.createLabel(workspaceSlug, { name: labelName.trim(), color }),
                async () => {
                  setLabelName("");
                  await mutateLabels();
                }
              );
            }}
          >
            <input
              type="color"
              value={color}
              onChange={(e) => setColor(e.target.value)}
              aria-label={t("releases.new_label")}
              className="size-7 shrink-0 cursor-pointer rounded border border-subtle bg-transparent"
            />
            <div className="flex-1">
              <InputField
                size="md"
                orientation="vertical"
                value={labelName}
                onChange={(e) => setLabelName(e.target.value)}
                aria-label={t("releases.new_label")}
                placeholder={t("releases.new_label")}
              />
            </div>
            <Button type="submit" variant="secondary" size="md" stretch="auto" label={t("releases.add_label")} />
          </form>
          {(labels ?? []).length === 0 && (
            <p className="text-caption-md-regular text-tertiary">{t("releases.no_labels")}</p>
          )}
          {(labels ?? []).map((label) => (
            <div key={label.id} className="flex items-center gap-2">
              <div className="flex-1">
                <ReleaseLabelChip label={label} />
              </div>
              <Button
                variant="ghost"
                size="sm"
                stretch="auto"
                label={t("releases.delete_label")}
                onClick={() =>
                  void run(
                    () => service.deleteLabel(workspaceSlug, label.id),
                    () => mutateLabels()
                  )
                }
              />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
