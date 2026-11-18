/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
import { Menu, MenuCheckboxItem, MenuContent, MenuItem, MenuTrigger } from "@makeplane/propel/components/menu";
import { Switch } from "@makeplane/propel/components/switch";
import { PropertiesOutline } from "@makeplane/propel/icons";
import { DateSelect } from "@plane/blocks/property-select";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TIssueProperty, TIssuePropertyValueRow } from "@plane/types";
import { getDate, renderFormattedPayloadDate } from "@plane/utils";
import { SidebarPropertyListItem } from "@/components/common/layout/sidebar/property-list-item";
import { useMember } from "@/hooks/store/use-member";
import { IssuePropertyService } from "@/services/issue-property.service";
import { IssueDetailSidebarGroup } from "./sidebar-group";

const service = new IssuePropertyService();

type TValue = string | number | boolean | string[] | null;

const INPUT_CLASS =
  "h-8 w-full rounded-md bg-transparent px-2 text-body-xs-regular text-primary placeholder:text-placeholder hover:bg-layer-transparent-hover focus:bg-layer-1 focus:outline-none disabled:cursor-not-allowed";

/** Text, number, URL and email: saved on blur or Enter. */
function TextEditor(props: {
  property: TIssueProperty;
  value: string | number | null;
  disabled: boolean;
  onSave: (value: TValue) => void;
}) {
  const { property, value, disabled, onSave } = props;
  const { t } = useTranslation();
  const [draft, setDraft] = useState(value == null ? "" : String(value));
  useEffect(() => setDraft(value == null ? "" : String(value)), [value]);
  const isNumber = property.property_type === "DECIMAL";
  const commit = () => {
    const trimmed = draft.trim();
    const next = trimmed === "" ? null : isNumber ? Number(trimmed) : trimmed;
    if (isNumber && next !== null && Number.isNaN(next)) return setDraft(value == null ? "" : String(value));
    if (next !== value) onSave(next);
  };
  return (
    <input
      className={INPUT_CLASS}
      type={isNumber ? "number" : property.property_type === "URL" ? "url" : "text"}
      value={draft}
      disabled={disabled}
      placeholder={t("work_item_properties.empty_value")}
      aria-label={property.display_name}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
      }}
    />
  );
}

/** Option and user properties: one menu, checkboxes when the property holds several values. */
const ChoiceEditor = observer(function ChoiceEditor(props: {
  property: TIssueProperty;
  values: string[];
  workspaceSlug: string;
  disabled: boolean;
  onSave: (value: TValue) => void;
}) {
  const { property, values, workspaceSlug, disabled, onSave } = props;
  const { t } = useTranslation();
  const {
    getUserDetails,
    workspace: { getWorkspaceMemberIds },
  } = useMember();
  const choices =
    property.property_type === "OPTION"
      ? property.options.map((option) => ({ id: option.id, label: option.name }))
      : getWorkspaceMemberIds(workspaceSlug).map((id) => ({ id, label: getUserDetails(id)?.display_name ?? id }));
  const selected = choices.filter((choice) => values.includes(choice.id));
  const label = selected.length
    ? selected.map((choice) => choice.label).join(", ")
    : t("work_item_properties.empty_value");
  const toggle = (id: string) => {
    if (!property.is_multi) return onSave(values[0] === id ? null : id);
    const next = values.includes(id) ? values.filter((value) => value !== id) : [...values, id];
    onSave(next.length ? next : null);
  };
  return (
    <Menu>
      <MenuTrigger
        disabled={disabled}
        render={
          <button
            type="button"
            aria-label={property.display_name}
            className="h-8 w-full truncate rounded-md px-2 text-left text-body-xs-regular text-primary hover:bg-layer-transparent-hover disabled:cursor-not-allowed"
          >
            {label}
          </button>
        }
      />
      <MenuContent side="bottom" align="start">
        {choices.map((choice) =>
          property.is_multi ? (
            <MenuCheckboxItem
              key={choice.id}
              label={choice.label}
              checked={values.includes(choice.id)}
              onCheckedChange={() => toggle(choice.id)}
            />
          ) : (
            <MenuItem key={choice.id} label={choice.label} onClick={() => toggle(choice.id)} />
          )
        )}
      </MenuContent>
    </Menu>
  );
});

function PropertyEditor(props: {
  row: TIssuePropertyValueRow;
  workspaceSlug: string;
  disabled: boolean;
  onSave: (value: TValue) => void;
}) {
  const { row, workspaceSlug, disabled, onSave } = props;
  const { property, values } = row;
  const { t } = useTranslation();
  const first = values[0] ?? null;
  switch (property.property_type) {
    case "BOOLEAN":
      return (
        <div className="flex h-8 items-center px-2">
          <Switch
            size="sm"
            checked={first === true}
            disabled={disabled}
            aria-label={property.display_name}
            onCheckedChange={(checked) => onSave(!!checked)}
          />
        </div>
      );
    case "DATETIME":
      return (
        <DateSelect
          variant="select-ghost-md"
          className="h-8 w-full grow"
          value={getDate(typeof first === "string" ? first.slice(0, 10) : null) ?? null}
          onChange={(date) => onSave(date ? (renderFormattedPayloadDate(date) ?? null) : null)}
          placeholder={t("work_item_properties.empty_value")}
          disabled={disabled}
          clearable
        />
      );
    case "OPTION":
      return (
        <ChoiceEditor
          property={property}
          values={values.filter((v): v is string => typeof v === "string")}
          workspaceSlug={workspaceSlug}
          disabled={disabled}
          onSave={onSave}
        />
      );
    case "RELATION":
      if (property.relation_type === "USER")
        return (
          <ChoiceEditor
            property={property}
            values={values.filter((v): v is string => typeof v === "string")}
            workspaceSlug={workspaceSlug}
            disabled={disabled}
            onSave={onSave}
          />
        );
      // Work item relations are set through the API for now; show how many are linked.
      return (
        <span className="flex h-8 items-center px-2 text-body-xs-regular text-tertiary">
          {values.length ? t("work_item_properties.linked_items", { count: values.length }) : "—"}
        </span>
      );
    default:
      return (
        <TextEditor
          property={property}
          value={typeof first === "boolean" ? null : first}
          disabled={disabled}
          onSave={onSave}
        />
      );
  }
}

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  typeId: string | null | undefined;
  disabled: boolean;
};

/** The work item's custom properties (those of its type and the project's general ones). */
export const IssueCustomProperties = observer(function IssueCustomProperties(props: Props) {
  const { workspaceSlug, projectId, issueId, typeId, disabled } = props;
  const { t } = useTranslation();
  const { data: rows, mutate } = useSWR(`ISSUE_PROPERTY_VALUES_${issueId}_${typeId ?? "none"}`, () =>
    service.listValues(workspaceSlug, projectId, issueId)
  );

  if (!rows || rows.length === 0) return null;

  const save = async (propertyId: string, value: TValue) => {
    try {
      const updated = await service.setValue(workspaceSlug, projectId, issueId, propertyId, value);
      await mutate(updated, { revalidate: false });
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error;
      setToast({ type: "error", title: message ?? t("work_item_properties.save_error") });
      await mutate();
    }
  };

  return (
    <>
      <div className="w-full border-t border-subtle" />
      <IssueDetailSidebarGroup label={t("work_item_properties.title")}>
        {rows.map((row) => (
          <SidebarPropertyListItem key={row.property.id} icon={PropertiesOutline} label={row.property.display_name}>
            <PropertyEditor
              row={row}
              workspaceSlug={workspaceSlug}
              disabled={disabled}
              onSave={(value) => void save(row.property.id, value)}
            />
          </SidebarPropertyListItem>
        ))}
      </IssueDetailSidebarGroup>
    </>
  );
});
