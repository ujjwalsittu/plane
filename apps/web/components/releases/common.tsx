/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@makeplane/propel/components/menu";
import { useTranslation } from "@plane/i18n";
import type { TReleaseLabel, TReleaseStatus } from "@plane/types";

export const RELEASE_STATUSES: TReleaseStatus[] = ["unreleased", "released", "cancelled"];

const STATUS_VARIANT = { unreleased: "info", released: "success", cancelled: "neutral" } as const;

export const getReleasesKey = (workspaceSlug: string) => `RELEASES_${workspaceSlug}`;
export const getReleaseKey = (releaseId: string) => `RELEASE_${releaseId}`;
export const getReleaseTagsKey = (workspaceSlug: string) => `RELEASE_TAGS_${workspaceSlug}`;
export const getReleaseLabelsKey = (workspaceSlug: string) => `RELEASE_LABELS_${workspaceSlug}`;

export function ReleaseStatusBadge({ status }: { status: TReleaseStatus }) {
  const { t } = useTranslation();
  return <Badge variant={STATUS_VARIANT[status]} size="sm" label={t(`releases.status.${status}`)} />;
}

export function ReleaseStatusSelect(props: {
  value: TReleaseStatus;
  onChange: (status: TReleaseStatus) => void;
  disabled?: boolean;
}) {
  const { value, onChange, disabled } = props;
  const { t } = useTranslation();
  if (disabled) return <ReleaseStatusBadge status={value} />;
  return (
    <Menu>
      <MenuTrigger
        render={
          <Button
            variant="ghost"
            size="sm"
            stretch="auto"
            aria-label={t(`releases.status.${value}`)}
            label={t(`releases.status.${value}`)}
          />
        }
      />
      <MenuContent side="bottom" align="start">
        {RELEASE_STATUSES.map((status) => (
          <MenuItem key={status} label={t(`releases.status.${status}`)} onClick={() => onChange(status)} />
        ))}
      </MenuContent>
    </Menu>
  );
}

export function ReleaseLabelChip(props: { label: TReleaseLabel; active?: boolean; onClick?: () => void }) {
  const { label, active = true, onClick } = props;
  const className = `flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-caption-md-medium ${
    active ? "border-subtle text-primary" : "border-dashed border-subtle text-tertiary"
  }`;
  const content = (
    <>
      <span
        className="size-2 shrink-0 rounded-full"
        style={{ backgroundColor: label.color || "var(--color-text-tertiary)" }}
      />
      {label.name}
    </>
  );
  return onClick ? (
    <button type="button" className={`${className} hover:bg-layer-1`} onClick={onClick} aria-pressed={active}>
      {content}
    </button>
  ) : (
    <span className={className}>{content}</span>
  );
}
