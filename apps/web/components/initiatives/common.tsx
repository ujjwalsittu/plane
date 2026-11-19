/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { LinearProgress } from "@makeplane/propel/components/linear-progress";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@makeplane/propel/components/menu";
import { useTranslation } from "@plane/i18n";
import type { TInitiativeProgress, TInitiativeState } from "@plane/types";

export const INITIATIVE_STATES: TInitiativeState[] = ["DRAFT", "PLANNED", "ACTIVE", "COMPLETED", "CLOSED"];

const STATE_VARIANT = {
  DRAFT: "grey",
  PLANNED: "info",
  ACTIVE: "brand",
  COMPLETED: "success",
  CLOSED: "neutral",
} as const;

export const getInitiativesKey = (workspaceSlug: string) => `INITIATIVES_${workspaceSlug}`;
export const getInitiativeKey = (initiativeId: string) => `INITIATIVE_${initiativeId}`;

export function InitiativeStateBadge({ state }: { state: TInitiativeState }) {
  const { t } = useTranslation();
  return <Badge variant={STATE_VARIANT[state]} size="sm" label={t(`initiatives.states.${state}`)} />;
}

export function InitiativeStateSelect(props: {
  value: TInitiativeState;
  onChange: (state: TInitiativeState) => void;
  disabled?: boolean;
}) {
  const { value, onChange, disabled } = props;
  const { t } = useTranslation();
  if (disabled) return <InitiativeStateBadge state={value} />;
  return (
    <Menu>
      <MenuTrigger
        render={
          <Button
            variant="ghost"
            size="sm"
            stretch="auto"
            aria-label={t(`initiatives.states.${value}`)}
            label={t(`initiatives.states.${value}`)}
          />
        }
      />
      <MenuContent side="bottom" align="start">
        {INITIATIVE_STATES.map((state) => (
          <MenuItem key={state} label={t(`initiatives.states.${state}`)} onClick={() => onChange(state)} />
        ))}
      </MenuContent>
    </Menu>
  );
}

export function InitiativeProgressBar({ progress, label }: { progress: TInitiativeProgress; label: string }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-w-40 items-center gap-2">
      <div className="flex-1">
        <LinearProgress
          value={progress.percent}
          size="sm"
          variant={progress.percent === 100 && progress.total > 0 ? "success" : "brand"}
          aria-label={label}
        />
      </div>
      <span
        className="w-14 shrink-0 text-right text-caption-md-regular text-tertiary"
        title={t("initiatives.progress_detail", { completed: progress.completed, total: progress.total })}
      >
        {progress.completed}/{progress.total - progress.cancelled}
      </span>
    </div>
  );
}
