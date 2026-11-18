/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { CheckboxField } from "@makeplane/propel/components/checkbox-field";
import { InputField } from "@makeplane/propel/components/input-field";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@makeplane/propel/components/menu";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TIssueProperty, TIssuePropertyType, TIssueType } from "@plane/types";
import { IssuePropertyService } from "@/services/issue-property.service";

const service = new IssuePropertyService();

export const PROPERTY_TYPE_OPTIONS: TIssuePropertyType[] = [
  "TEXT",
  "DECIMAL",
  "BOOLEAN",
  "DATETIME",
  "OPTION",
  "RELATION",
  "URL",
  "EMAIL",
];

type ChoiceProps<T extends string> = {
  label: string;
  value: T;
  options: { key: T; label: string }[];
  onChange: (value: T) => void;
};

function ChoiceMenu<T extends string>({ label, value, options, onChange }: ChoiceProps<T>) {
  const current = options.find((option) => option.key === value)?.label ?? value;
  return (
    <Menu>
      <MenuTrigger
        render={<Button variant="secondary" size="lg" stretch="auto" aria-label={label} label={current} />}
      />
      <MenuContent side="bottom" align="start">
        {options.map((option) => (
          <MenuItem key={option.key} label={option.label} onClick={() => onChange(option.key)} />
        ))}
      </MenuContent>
    </Menu>
  );
}

type Props = { workspaceSlug: string; projectId: string; issueTypes: TIssueType[] };

/** A project's custom work item properties: list, add (for all work items or one type), delete. */
export function IssuePropertiesSettings({ workspaceSlug, projectId, issueTypes }: Props) {
  const { t } = useTranslation();
  const { data: properties, mutate } = useSWR(`PROJECT_ISSUE_PROPERTIES_${projectId}`, () =>
    service.list(workspaceSlug, projectId)
  );
  const [name, setName] = useState("");
  const [propertyType, setPropertyType] = useState<TIssuePropertyType>("TEXT");
  const [relationType, setRelationType] = useState<"USER" | "ISSUE">("USER");
  const [appliesTo, setAppliesTo] = useState<string>("all");
  const [isMulti, setIsMulti] = useState(false);
  const [options, setOptions] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [toDelete, setToDelete] = useState<TIssueProperty | null>(null);

  const typeName = (id: string | null) =>
    id ? (issueTypes.find((type) => type.id === id)?.name ?? "—") : t("work_item_properties.all_work_items");
  const canBeMulti = propertyType === "OPTION" || propertyType === "RELATION";

  const handleCreate = async () => {
    setSubmitting(true);
    try {
      await service.create(workspaceSlug, projectId, {
        display_name: name.trim(),
        property_type: propertyType,
        relation_type: propertyType === "RELATION" ? relationType : undefined,
        is_multi: canBeMulti && isMulti,
        issue_type_id: appliesTo === "all" ? null : appliesTo,
        options:
          propertyType === "OPTION"
            ? options
                .split(",")
                .map((option) => option.trim())
                .filter(Boolean)
            : undefined,
      });
      setName("");
      setOptions("");
      await mutate();
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error;
      setToast({ type: "error", title: message ?? t("work_item_properties.save_error") });
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!toDelete) return;
    try {
      await service.remove(workspaceSlug, projectId, toDelete.id);
      await mutate();
    } catch {
      setToast({ type: "error", title: t("work_item_properties.save_error") });
    } finally {
      setToDelete(null);
    }
  };

  const ownProperties = (properties ?? []).filter((property) => property.project === projectId);

  return (
    <section className="flex flex-col gap-3">
      <div>
        <h3 className="text-h5-medium text-primary">{t("work_item_properties.title")}</h3>
        <p className="text-body-xs-regular text-tertiary">{t("work_item_properties.description")}</p>
      </div>
      <div className="divide-y divide-subtle rounded-lg border border-subtle">
        {ownProperties.length === 0 && (
          <p className="px-4 py-3 text-body-sm-regular text-tertiary">{t("work_item_properties.empty")}</p>
        )}
        {ownProperties.map((property) => (
          <div key={property.id} className="flex flex-wrap items-center gap-2 px-4 py-3">
            <span className="truncate text-body-sm-medium text-primary">{property.display_name}</span>
            <Badge variant="neutral" size="sm" label={t(`work_item_properties.types.${property.property_type}`)} />
            {property.is_multi && <Badge variant="neutral" size="sm" label={t("work_item_properties.multi")} />}
            <span className="text-caption-md-regular text-tertiary">· {typeName(property.issue_type)}</span>
            {property.options.length > 0 && (
              <span className="truncate text-caption-md-regular text-secondary">
                {property.options.map((option) => option.name).join(", ")}
              </span>
            )}
            <div className="ml-auto">
              <Button
                variant="danger-outline"
                size="sm"
                stretch="auto"
                label={t("delete")}
                onClick={() => setToDelete(property)}
              />
            </div>
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
        <div className="min-w-48 flex-1">
          <InputField
            size="lg"
            orientation="vertical"
            value={name}
            maxLength={255}
            onChange={(e) => setName(e.target.value)}
            aria-label={t("work_item_properties.name")}
            placeholder={t("work_item_properties.name")}
          />
        </div>
        <ChoiceMenu
          label={t("work_item_properties.kind")}
          value={propertyType}
          options={PROPERTY_TYPE_OPTIONS.map((key) => ({ key, label: t(`work_item_properties.types.${key}`) }))}
          onChange={setPropertyType}
        />
        {propertyType === "RELATION" && (
          <ChoiceMenu
            label={t("work_item_properties.relation_to")}
            value={relationType}
            options={[
              { key: "USER", label: t("work_item_properties.relation_user") },
              { key: "ISSUE", label: t("work_item_properties.relation_issue") },
            ]}
            onChange={setRelationType}
          />
        )}
        <ChoiceMenu
          label={t("work_item_properties.applies_to")}
          value={appliesTo}
          options={[
            { key: "all", label: t("work_item_properties.all_work_items") },
            ...issueTypes.map((type) => ({ key: type.id, label: type.name })),
          ]}
          onChange={setAppliesTo}
        />
        {propertyType === "OPTION" && (
          <div className="min-w-56 flex-1">
            <InputField
              size="lg"
              orientation="vertical"
              value={options}
              onChange={(e) => setOptions(e.target.value)}
              aria-label={t("work_item_properties.options")}
              placeholder={t("work_item_properties.options_placeholder")}
            />
          </div>
        )}
        {canBeMulti && (
          <CheckboxField
            size="lg"
            label={t("work_item_properties.multi")}
            checked={isMulti}
            onCheckedChange={(checked) => setIsMulti(!!checked)}
          />
        )}
        <Button
          type="submit"
          variant="primary"
          size="lg"
          stretch="auto"
          loading={submitting}
          disabled={!name.trim()}
          label={t("work_item_properties.add")}
        />
      </form>

      <ConfirmDialog
        isOpen={!!toDelete}
        handleClose={() => setToDelete(null)}
        handleSubmit={handleDelete}
        isSubmitting={false}
        title={t("work_item_properties.delete_title")}
        content={t("work_item_properties.delete_description", { name: toDelete?.display_name ?? "" })}
      />
    </section>
  );
}
