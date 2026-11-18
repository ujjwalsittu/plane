/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { Button } from "@makeplane/propel/components/button";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@makeplane/propel/components/menu";
import { PriorityIcon } from "@plane/blocks/icons";
import { DateSelect } from "@plane/blocks/property-select";
import { useTranslation } from "@plane/i18n";
import type { TProjectPriority, TProjectStatus } from "@plane/types";
import { getDate, renderFormattedPayloadDate } from "@plane/utils";
import { useUserProfile } from "@/hooks/store/user";
import { PROJECT_PRIORITY_OPTIONS, PROJECT_STATUS_OPTIONS, getProjectStatusColor } from "./constants";

export function ProjectStatusDot({ status }: { status: TProjectStatus | undefined }) {
  return <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: getProjectStatusColor(status) }} />;
}

type SelectProps<T> = { value: T | undefined; onChange: (value: T) => void; disabled?: boolean };

export function ProjectStatusSelect({ value, onChange, disabled }: SelectProps<TProjectStatus>) {
  const { t } = useTranslation();
  const current = value ?? "backlog";
  const label = t(`project_planning.statuses.${current}`);
  if (disabled)
    return (
      <span className="flex items-center gap-1.5 text-body-xs-medium text-secondary">
        <ProjectStatusDot status={current} />
        {label}
      </span>
    );
  return (
    <Menu>
      <MenuTrigger
        render={
          <Button
            variant="ghost"
            size="sm"
            stretch="auto"
            aria-label={t("project_planning.status")}
            icon={<ProjectStatusDot status={current} />}
            label={label}
          />
        }
      />
      <MenuContent side="bottom" align="start">
        {PROJECT_STATUS_OPTIONS.map((option) => (
          <MenuItem
            key={option.key}
            label={t(`project_planning.statuses.${option.key}`)}
            icon={<ProjectStatusDot status={option.key} />}
            onClick={() => onChange(option.key)}
          />
        ))}
      </MenuContent>
    </Menu>
  );
}

export function ProjectPrioritySelect({ value, onChange, disabled }: SelectProps<TProjectPriority>) {
  const { t } = useTranslation();
  const current = value ?? "none";
  const label = t(`project_planning.priorities.${current}`);
  const icon = <PriorityIcon priority={current} className="size-3.5" />;
  if (disabled)
    return (
      <span className="flex items-center gap-1.5 text-body-xs-medium text-secondary">
        {icon}
        {label}
      </span>
    );
  return (
    <Menu>
      <MenuTrigger
        render={
          <Button
            variant="ghost"
            size="sm"
            stretch="auto"
            aria-label={t("project_planning.priority")}
            icon={icon}
            label={label}
          />
        }
      />
      <MenuContent side="bottom" align="start">
        {PROJECT_PRIORITY_OPTIONS.map((option) => (
          <MenuItem
            key={option}
            label={t(`project_planning.priorities.${option}`)}
            icon={<PriorityIcon priority={option} className="size-3.5" />}
            onClick={() => onChange(option)}
          />
        ))}
      </MenuContent>
    </Menu>
  );
}

type DateProps = {
  value: string | null | undefined;
  onChange: (value: string | null) => void;
  placeholder: string;
  disabled?: boolean;
  minDate?: string | null;
  maxDate?: string | null;
};

export const ProjectDateSelect = observer(function ProjectDateSelect(props: DateProps) {
  const { value, onChange, placeholder, disabled, minDate, maxDate } = props;
  const { data: userProfile } = useUserProfile();
  return (
    <DateSelect
      variant="pill-sm"
      className="max-w-none"
      value={getDate(value) ?? null}
      onChange={(date) => onChange(date ? (renderFormattedPayloadDate(date) ?? null) : null)}
      placeholder={placeholder}
      weekStartsOn={userProfile?.start_of_the_week}
      minDate={getDate(minDate) ?? undefined}
      maxDate={getDate(maxDate) ?? undefined}
      disabled={disabled}
      clearable
    />
  );
});
