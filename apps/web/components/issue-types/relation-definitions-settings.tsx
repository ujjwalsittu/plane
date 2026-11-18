/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { InputField } from "@makeplane/propel/components/input-field";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TRelationDefinition } from "@plane/types";
import { getRelationDefinitionsKey } from "@/components/issues/issue-detail-widgets/custom-relations/use-custom-relations";
import { RelationDefinitionService } from "@/services/relation-definition.service";

const service = new RelationDefinitionService();

/** The workspace's relation types: the built-in ones (read-only) and its own. */
export function RelationDefinitionsSettings({ workspaceSlug }: { workspaceSlug: string }) {
  const { t } = useTranslation();
  const { data: definitions, mutate } = useSWR(getRelationDefinitionsKey(workspaceSlug), () =>
    service.listDefinitions(workspaceSlug)
  );
  const [name, setName] = useState("");
  const [outward, setOutward] = useState("");
  const [inward, setInward] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [toDelete, setToDelete] = useState<TRelationDefinition | null>(null);

  const handleCreate = async () => {
    setSubmitting(true);
    try {
      await service.createDefinition(workspaceSlug, {
        name: name.trim(),
        outward: outward.trim() || name.trim().toLowerCase(),
        inward: inward.trim() || outward.trim() || name.trim().toLowerCase(),
      });
      setName("");
      setOutward("");
      setInward("");
      await mutate();
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error;
      setToast({ type: "error", title: message ?? t("custom_relations.save_error") });
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!toDelete) return;
    try {
      await service.deleteDefinition(workspaceSlug, toDelete.id);
      await mutate();
    } catch {
      setToast({ type: "error", title: t("custom_relations.save_error") });
    } finally {
      setToDelete(null);
    }
  };

  return (
    <section className="flex flex-col gap-3">
      <div>
        <h3 className="text-h5-medium text-primary">{t("custom_relations.settings_title")}</h3>
        <p className="text-body-xs-regular text-tertiary">{t("custom_relations.settings_description")}</p>
      </div>
      <div className="divide-y divide-subtle rounded-lg border border-subtle">
        {(definitions ?? []).map((definition) => (
          <div key={definition.id} className="flex flex-wrap items-center gap-2 px-4 py-3">
            <span className="text-body-sm-medium text-primary">{definition.name}</span>
            <span className="text-caption-md-regular text-tertiary">
              {definition.outward === definition.inward
                ? definition.outward
                : `${definition.outward} / ${definition.inward}`}
            </span>
            {definition.is_default ? (
              <div className="ml-auto">
                <Badge variant="neutral" size="sm" label={t("custom_relations.built_in")} />
              </div>
            ) : (
              <div className="ml-auto">
                <Button
                  variant="danger-outline"
                  size="sm"
                  stretch="auto"
                  label={t("delete")}
                  onClick={() => setToDelete(definition)}
                />
              </div>
            )}
          </div>
        ))}
      </div>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) void handleCreate();
        }}
      >
        <div className="min-w-40 flex-1">
          <InputField
            size="lg"
            orientation="vertical"
            value={name}
            maxLength={255}
            onChange={(e) => setName(e.target.value)}
            aria-label={t("custom_relations.name")}
            placeholder={t("custom_relations.name_placeholder")}
          />
        </div>
        <div className="min-w-40 flex-1">
          <InputField
            size="lg"
            orientation="vertical"
            value={outward}
            maxLength={255}
            onChange={(e) => setOutward(e.target.value)}
            aria-label={t("custom_relations.outward")}
            placeholder={t("custom_relations.outward_placeholder")}
          />
        </div>
        <div className="min-w-40 flex-1">
          <InputField
            size="lg"
            orientation="vertical"
            value={inward}
            maxLength={255}
            onChange={(e) => setInward(e.target.value)}
            aria-label={t("custom_relations.inward")}
            placeholder={t("custom_relations.inward_placeholder")}
          />
        </div>
        <Button
          type="submit"
          variant="primary"
          size="lg"
          stretch="auto"
          loading={submitting}
          disabled={!name.trim()}
          label={t("custom_relations.add_type")}
        />
      </form>
      <ConfirmDialog
        isOpen={!!toDelete}
        handleClose={() => setToDelete(null)}
        handleSubmit={handleDelete}
        isSubmitting={false}
        title={t("custom_relations.delete_title")}
        content={t("custom_relations.delete_description", { name: toDelete?.name ?? "" })}
      />
    </section>
  );
}
