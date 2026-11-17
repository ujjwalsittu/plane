/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useMemo } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { EpicOutline, LayerStackOutline } from "@makeplane/propel/icons";
import { Select } from "@plane/blocks/select";
import type { SelectPaginationParams, SelectTooltip, SelectTooltipOverride, SelectVariant } from "@plane/blocks/select";
import { useTranslation } from "@plane/i18n";
import type { TIssueType, TPaginatedResponse } from "@plane/types";
import { useMilestone } from "@/hooks/store/use-milestone";

type IssueTypeOption = { id: string; name: string; is_epic?: boolean };

const CLEAR_OPTION_ID = "";

type Props = {
  projectId: string | undefined;
  value: string | null | undefined;
  onChange: (issueTypeId: string | null) => void;
  variant: SelectVariant;
  disabled?: boolean;
  placeholder?: string;
  onClose?: () => void;
  clearable?: boolean;
  className?: string;
  tooltip?: SelectTooltip;
  tabIndex?: number;
};

const toOption = (issueType: TIssueType): IssueTypeOption => ({
  id: issueType.id,
  name: issueType.name,
  is_epic: issueType.is_epic,
});

export function IssueTypeIcon({ isEpic, className }: { isEpic?: boolean; className?: string }) {
  return isEpic ? <EpicOutline className={className} /> : <LayerStackOutline className={className} />;
}

export const IssueTypeSelect = observer(function IssueTypeSelect(props: Props) {
  const {
    projectId,
    value,
    onChange,
    variant,
    disabled,
    placeholder,
    onClose,
    clearable = true,
    className,
    tooltip,
    tabIndex,
  } = props;
  const { workspaceSlug } = useParams();
  const { t } = useTranslation();
  const { getProjectIssueTypes, getIssueTypeById, fetchIssueTypes, ensureIssueTypes } = useMilestone();

  const resolvedPlaceholder = placeholder ?? t("issue_types_feature.none");
  const resolvedTooltip = useMemo<SelectTooltipOverride | undefined>(() => {
    if (!tooltip) return undefined;
    const override = typeof tooltip === "object" ? tooltip : undefined;
    return {
      heading: override?.heading ?? t("issue_types_feature.label"),
      emptyContent: override?.emptyContent ?? t("common.none"),
    };
  }, [tooltip, t]);

  const getValues = useCallback(
    async ({ search }: SelectPaginationParams): Promise<TPaginatedResponse<IssueTypeOption[]>> => {
      if (!workspaceSlug || !projectId) return { results: [] };
      let issueTypes = getProjectIssueTypes(projectId);
      if (!issueTypes) {
        await fetchIssueTypes(workspaceSlug.toString(), projectId);
        issueTypes = getProjectIssueTypes(projectId);
      }
      const query = search?.trim().toLowerCase();
      const results = (issueTypes ?? [])
        .filter((issueType) => issueType.is_active !== false)
        .filter((issueType) => !query || issueType.name.toLowerCase().includes(query))
        .map(toOption);
      return { results, next_page_results: false };
    },
    [workspaceSlug, projectId, getProjectIssueTypes, fetchIssueTypes]
  );

  const issueType = value ? getIssueTypeById(value) : null;

  // The label comes from the store; load the project's list if this value isn't in it yet
  // (e.g. a work item opened directly, before any list view loaded them).
  useEffect(() => {
    if (!value || issueType || !workspaceSlug || !projectId) return;
    ensureIssueTypes(workspaceSlug.toString(), projectId).catch(() => undefined);
  }, [value, issueType, workspaceSlug, projectId, ensureIssueTypes]);
  const selected = issueType ? toOption(issueType) : null;
  const clearOption = useMemo<IssueTypeOption>(
    () => ({ id: CLEAR_OPTION_ID, name: t("issue_types_feature.none") }),
    [t]
  );
  const handleChange = useCallback((issueTypeId: string) => onChange(issueTypeId || null), [onChange]);

  return (
    <Select<IssueTypeOption>
      infinite
      getValues={getValues}
      value={selected}
      onChange={handleChange}
      disabled={disabled}
      placeholder={resolvedPlaceholder}
      searchPlaceholder={t("common.search.label")}
      onClose={onClose}
      headerItems={clearable ? [clearOption] : undefined}
      getOptionValue={(option) => option.id}
      getOptionLabel={(option) => option.name}
      getOptionIcon={(option) => <IssueTypeIcon isEpic={option.is_epic} className="size-4 shrink-0 text-secondary" />}
    >
      <Select.Trigger<IssueTypeOption>
        disabled={disabled}
        variant={variant}
        tabIndex={tabIndex}
        className={className}
        prependIcon={(options) => <IssueTypeIcon isEpic={options[0]?.is_epic} />}
        label={(options) => options[0]?.name ?? resolvedPlaceholder}
        tooltip={resolvedTooltip}
      >
        {(options) => (
          <span className="min-w-0 grow truncate text-left">{options[0]?.name ?? resolvedPlaceholder}</span>
        )}
      </Select.Trigger>
    </Select>
  );
});
