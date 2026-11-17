/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useMemo } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { MilestoneOutline } from "@makeplane/propel/icons";
import { Select } from "@plane/blocks/select";
import type { SelectPaginationParams, SelectTooltip, SelectTooltipOverride, SelectVariant } from "@plane/blocks/select";
import { useTranslation } from "@plane/i18n";
import type { TMilestone, TPaginatedResponse } from "@plane/types";
import { renderFormattedDate } from "@plane/utils";
import { useMilestone } from "@/hooks/store/use-milestone";

type MilestoneOption = { id: string; title: string; target_date?: string | null };

const CLEAR_OPTION_ID = "";

type Props = {
  projectId: string | undefined;
  value: string | null | undefined;
  onChange: (milestoneId: string | null) => void;
  variant: SelectVariant;
  disabled?: boolean;
  placeholder?: string;
  onClose?: () => void;
  clearable?: boolean;
  className?: string;
  tooltip?: SelectTooltip;
  tabIndex?: number;
};

const toOption = (milestone: TMilestone): MilestoneOption => ({
  id: milestone.id,
  title: milestone.title,
  target_date: milestone.target_date,
});

export const MilestoneSelect = observer(function MilestoneSelect(props: Props) {
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
  const { getProjectMilestones, getMilestoneById, fetchMilestones, ensureMilestones } = useMilestone();

  const resolvedPlaceholder = placeholder ?? t("milestones_feature.none");
  const resolvedTooltip = useMemo<SelectTooltipOverride | undefined>(() => {
    if (!tooltip) return undefined;
    const override = typeof tooltip === "object" ? tooltip : undefined;
    return {
      heading: override?.heading ?? t("milestones_feature.label"),
      emptyContent: override?.emptyContent ?? t("common.none"),
    };
  }, [tooltip, t]);

  const getValues = useCallback(
    async ({ search }: SelectPaginationParams): Promise<TPaginatedResponse<MilestoneOption[]>> => {
      if (!workspaceSlug || !projectId) return { results: [] };
      let milestones = getProjectMilestones(projectId);
      if (!milestones) {
        await fetchMilestones(workspaceSlug.toString(), projectId);
        milestones = getProjectMilestones(projectId);
      }
      const query = search?.trim().toLowerCase();
      const results = (milestones ?? [])
        .filter((milestone) => !query || milestone.title.toLowerCase().includes(query))
        .map(toOption);
      return { results, next_page_results: false };
    },
    [workspaceSlug, projectId, getProjectMilestones, fetchMilestones]
  );

  const milestone = value ? getMilestoneById(value) : null;

  // The label comes from the store; load the project's list if this value isn't in it yet
  // (e.g. a work item opened directly, before any list view loaded them).
  useEffect(() => {
    if (!value || milestone || !workspaceSlug || !projectId) return;
    ensureMilestones(workspaceSlug.toString(), projectId).catch(() => undefined);
  }, [value, milestone, workspaceSlug, projectId, ensureMilestones]);
  const selected = milestone ? toOption(milestone) : null;
  const clearOption = useMemo<MilestoneOption>(
    () => ({ id: CLEAR_OPTION_ID, title: t("milestones_feature.none") }),
    [t]
  );
  const handleChange = useCallback((milestoneId: string) => onChange(milestoneId || null), [onChange]);

  return (
    <Select<MilestoneOption>
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
      getOptionLabel={(option) => option.title}
      getOptionIcon={() => <MilestoneOutline className="size-4 shrink-0 text-secondary" />}
      getOptionTrailing={(option) =>
        option.target_date ? (
          <span className="shrink-0 text-caption-sm-regular text-tertiary">
            {renderFormattedDate(option.target_date)}
          </span>
        ) : undefined
      }
    >
      <Select.Trigger<MilestoneOption>
        disabled={disabled}
        variant={variant}
        tabIndex={tabIndex}
        className={className}
        prependIcon={() => <MilestoneOutline />}
        label={(options) => options[0]?.title ?? resolvedPlaceholder}
        tooltip={resolvedTooltip}
      >
        {(options) => (
          <span className="min-w-0 grow truncate text-left">{options[0]?.title ?? resolvedPlaceholder}</span>
        )}
      </Select.Trigger>
    </Select>
  );
});
