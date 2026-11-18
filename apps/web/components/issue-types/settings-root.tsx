/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { CheckboxField } from "@makeplane/propel/components/checkbox-field";
import { InputField } from "@makeplane/propel/components/input-field";
import { Switch } from "@makeplane/propel/components/switch";
import { EpicOutline, LayerStackOutline } from "@makeplane/propel/icons";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TIssueType } from "@plane/types";
import { useMilestone } from "@/hooks/store/use-milestone";
import { IssuePropertiesSettings } from "./properties-settings";

type Props = {
  workspaceSlug: string;
  projectId: string;
};

const errorMessage = (err: unknown, fallback: string) => {
  if (err && typeof err === "object" && "error" in err && typeof err.error === "string") return err.error;
  return fallback;
};

export const IssueTypesSettingsRoot = observer(function IssueTypesSettingsRoot(props: Props) {
  const { workspaceSlug, projectId } = props;
  const { t } = useTranslation();
  const { getProjectIssueTypes, fetchIssueTypes, createIssueType, updateIssueType, deleteIssueType } = useMilestone();
  // state
  const [name, setName] = useState("");
  const [isEpic, setIsEpic] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [toDelete, setToDelete] = useState<TIssueType | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useSWR(`PROJECT_ISSUE_TYPES_${projectId}`, () => fetchIssueTypes(workspaceSlug, projectId));
  const issueTypes = getProjectIssueTypes(projectId) ?? [];
  const hasEpic = issueTypes.some((type) => type.is_epic);

  const handleCreate = async (data: { name: string; is_epic: boolean }) => {
    if (!data.name.trim()) return;
    setIsSubmitting(true);
    try {
      await createIssueType(workspaceSlug, projectId, { name: data.name.trim(), is_epic: data.is_epic });
      setName("");
      setIsEpic(false);
      setToast({ type: "success", title: t("issue_types_feature.toast.created") });
    } catch (err) {
      setToast({ type: "error", title: errorMessage(err, t("issue_types_feature.toast.error")) });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleUpdate = async (issueType: TIssueType, data: Partial<TIssueType>) => {
    try {
      await updateIssueType(workspaceSlug, projectId, issueType.id, data);
      setToast({ type: "success", title: t("issue_types_feature.toast.updated") });
    } catch (err) {
      setToast({ type: "error", title: errorMessage(err, t("issue_types_feature.toast.error")) });
    }
  };

  const handleDelete = async () => {
    if (!toDelete) return;
    setIsDeleting(true);
    try {
      await deleteIssueType(workspaceSlug, projectId, toDelete.id);
      setToast({ type: "success", title: t("issue_types_feature.toast.deleted") });
      setToDelete(null);
    } catch (err) {
      setToast({ type: "error", title: errorMessage(err, t("issue_types_feature.toast.error")) });
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="divide-y divide-subtle rounded-lg border border-subtle">
        {issueTypes.length === 0 && (
          <p className="px-4 py-3 text-body-sm-regular text-tertiary">{t("issue_types_feature.empty")}</p>
        )}
        {issueTypes.map((issueType) => (
          <div key={issueType.id} className="flex items-center gap-3 px-4 py-3">
            {issueType.is_epic ? (
              <EpicOutline className="size-4 shrink-0 text-secondary" />
            ) : (
              <LayerStackOutline className="size-4 shrink-0 text-secondary" />
            )}
            <span className="truncate text-body-sm-medium text-primary">{issueType.name}</span>
            {issueType.is_epic && <Badge variant="purple" size="sm" label={t("issue_types_feature.epic")} />}
            {issueType.is_default && <Badge variant="neutral" size="sm" label={t("issue_types_feature.default")} />}
            <div className="ml-auto flex items-center gap-2">
              <label className="flex items-center gap-2 text-body-xs-medium text-secondary">
                {t("issue_types_feature.is_epic")}
                <Switch
                  size="sm"
                  checked={issueType.is_epic}
                  onCheckedChange={(checked) => handleUpdate(issueType, { is_epic: !!checked })}
                />
              </label>
              <Button
                variant="ghost"
                size="sm"
                stretch="auto"
                label={
                  issueType.is_default ? t("issue_types_feature.unset_default") : t("issue_types_feature.set_default")
                }
                onClick={() => handleUpdate(issueType, { is_default: !issueType.is_default })}
              />
              <Button
                variant="danger-outline"
                size="sm"
                stretch="auto"
                label={t("delete")}
                onClick={() => setToDelete(issueType)}
              />
            </div>
          </div>
        ))}
      </div>

      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void handleCreate({ name, is_epic: isEpic });
        }}
      >
        <div className="min-w-56 flex-1">
          <InputField
            size="lg"
            orientation="vertical"
            id="issueTypeName"
            name="name"
            type="text"
            value={name}
            maxLength={255}
            onChange={(e) => setName(e.target.value)}
            aria-label={t("issue_types_feature.add")}
            placeholder={t("issue_types_feature.name_placeholder")}
          />
        </div>
        <CheckboxField
          size="lg"
          label={t("issue_types_feature.is_epic")}
          description={t("issue_types_feature.is_epic_help")}
          checked={isEpic}
          onCheckedChange={(checked) => setIsEpic(!!checked)}
        />
        <Button
          type="submit"
          variant="primary"
          size="lg"
          stretch="auto"
          loading={isSubmitting}
          disabled={!name.trim()}
          label={t("issue_types_feature.add")}
        />
        {!hasEpic && (
          <Button
            type="button"
            variant="secondary"
            size="lg"
            stretch="auto"
            disabled={isSubmitting}
            label={t("issue_types_feature.add_epic")}
            onClick={() => void handleCreate({ name: t("issue_types_feature.epic"), is_epic: true })}
          />
        )}
      </form>
      <p className="text-body-xs-regular text-tertiary">{t("issue_types_feature.default_help")}</p>

      <IssuePropertiesSettings workspaceSlug={workspaceSlug} projectId={projectId} issueTypes={issueTypes} />

      <ConfirmDialog
        isOpen={!!toDelete}
        handleClose={() => setToDelete(null)}
        handleSubmit={handleDelete}
        isSubmitting={isDeleting}
        title={t("issue_types_feature.delete.title")}
        content={t("issue_types_feature.delete.description", { name: toDelete?.name ?? "" })}
      />
    </div>
  );
});
