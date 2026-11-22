/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { Button } from "@makeplane/propel/components/button";
import { EntityDetailWidgetSection } from "@plane/blocks/entity-detail";
import { useTranslation } from "@plane/i18n";
import type { TTriageSuggestions } from "@plane/types";
import { SupervisionService } from "@/services/supervision.service";
import { TriageSuggestionRow } from "./suggestion-row";

const service = new SupervisionService();

/** Suggestions are offered for work items created within this many days. */
export const TRIAGE_RECENT_DAYS = 7;
const DAY_MS = 24 * 60 * 60 * 1000;

export const isTriageCandidate = (createdAt: string | undefined, assigneeIds: string[], labelIds: string[]) =>
  !!createdAt &&
  Date.now() - new Date(createdAt).getTime() <= TRIAGE_RECENT_DAYS * DAY_MS &&
  (assigneeIds.length === 0 || labelIds.length === 0);

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  createdAt: string | undefined;
  assigneeIds: string[];
  labelIds: string[];
  disabled: boolean;
  /** Each applies through the existing work item update or relation endpoint and throws when it fails. */
  onAssign: (memberId: string) => Promise<void>;
  onAddLabel: (labelId: string) => Promise<void>;
  onMarkDuplicate: (issueId: string) => Promise<void>;
};

/** "Suggestions": on request, Claude suggests an assignee, labels, a better project and likely duplicates. */
export function TriageCollapsible(props: Props) {
  const { workspaceSlug, projectId, issueId, createdAt, assigneeIds, labelIds, disabled } = props;
  const { onAssign, onAddLabel, onMarkDuplicate } = props;
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(true);
  const [suggestions, setSuggestions] = useState<TTriageSuggestions | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Once suggestions are on screen they stay, even after applying one fills the last gap.
  if (disabled || (!suggestions && !isTriageCandidate(createdAt, assigneeIds, labelIds))) return null;

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setSuggestions(await service.triage(workspaceSlug, projectId, issueId, suggestions !== null));
    } catch (e) {
      setError((e as { error?: string } | undefined)?.error ?? t("agents.triage.error"));
    } finally {
      setLoading(false);
    }
  };

  const assignee = suggestions?.assignee;
  const isEmpty =
    !!suggestions &&
    !suggestions.assignee &&
    !suggestions.project &&
    suggestions.labels.length === 0 &&
    suggestions.duplicates.length === 0;

  return (
    <EntityDetailWidgetSection title={t("agents.triage.title")} isOpen={isOpen} onToggle={() => setIsOpen((v) => !v)}>
      <div className="flex flex-col gap-2 px-2 py-1">
        <div className="flex items-center gap-3">
          <Button
            variant="secondary"
            size="sm"
            stretch="auto"
            loading={loading}
            label={suggestions ? t("agents.triage.refresh") : t("agents.triage.suggest")}
            onClick={() => void load()}
          />
          {loading && <span className="text-body-xs-regular text-tertiary">{t("agents.triage.thinking")}</span>}
        </div>
        {!suggestions && !error && <p className="text-caption-md-regular text-tertiary">{t("agents.triage.hint")}</p>}
        {error && <p className="text-body-xs-regular text-danger-primary">{error}</p>}
        {isEmpty && <p className="text-body-xs-regular text-tertiary">{t("agents.triage.none")}</p>}
        {suggestions && !isEmpty && (
          <ul key={suggestions.generated_at} className="flex flex-col gap-1.5">
            {assignee && !assigneeIds.includes(assignee.id) && (
              <TriageSuggestionRow
                kind={t("agents.triage.assignee")}
                title={assignee.display_name}
                reason={assignee.reason}
                onApply={() => onAssign(assignee.id)}
              />
            )}
            {suggestions.labels
              .filter((label) => !labelIds.includes(label.id))
              .map((label) => (
                <TriageSuggestionRow
                  key={label.id}
                  kind={t("agents.triage.label")}
                  title={label.name}
                  reason={label.reason}
                  onApply={() => onAddLabel(label.id)}
                />
              ))}
            {suggestions.duplicates.map((item) => (
              <TriageSuggestionRow
                key={item.id}
                kind={t("agents.triage.duplicate")}
                title={`${item.identifier} ${item.name}`}
                href={`/${workspaceSlug}/browse/${item.identifier}/`}
                reason={item.reason}
                actionLabel={t("agents.triage.mark_duplicate")}
                onApply={() => onMarkDuplicate(item.id)}
              />
            ))}
            {suggestions.project && (
              <TriageSuggestionRow
                kind={t("agents.triage.project")}
                title={suggestions.project.name}
                href={`/${workspaceSlug}/projects/${suggestions.project.id}/issues/`}
                reason={suggestions.project.reason}
              />
            )}
          </ul>
        )}
      </div>
    </EntityDetailWidgetSection>
  );
}
