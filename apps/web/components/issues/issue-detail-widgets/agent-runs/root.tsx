/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { Button } from "@makeplane/propel/components/button";
import { EntityDetailWidgetSection } from "@plane/blocks/entity-detail";
import { useTranslation } from "@plane/i18n";
import { DelegateModal } from "./delegate-modal";
import { RunRow } from "./run-row";
import { useAgentRuns } from "./use-agent-runs";

type Props = { workspaceSlug: string; projectId: string; issueId: string; disabled?: boolean };

/** The run log of a work item: who worked on it, how it went, what it cost, and the way to delegate more. */
export const AgentRunsCollapsible = observer(function AgentRunsCollapsible(props: Props) {
  const { workspaceSlug, projectId, issueId, disabled = false } = props;
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(true);
  const [delegating, setDelegating] = useState(false);
  const { data: runs, error, mutate } = useAgentRuns(workspaceSlug, projectId, issueId);

  const list = runs ?? [];
  // Read-only viewers with nothing to see get no empty section.
  if (disabled && list.length === 0) return null;

  return (
    <>
      <EntityDetailWidgetSection
        title={t("agents.runs.title")}
        count={list.length}
        isOpen={isOpen}
        onToggle={() => setIsOpen((value) => !value)}
      >
        <div className="flex flex-col gap-2 px-2 py-1">
          {!disabled && (
            <div>
              <Button
                variant="secondary"
                size="sm"
                stretch="auto"
                label={t("agents.runs.delegate")}
                onClick={() => setDelegating(true)}
              />
            </div>
          )}
          {error && list.length === 0 ? (
            <p className="text-body-xs-regular text-danger-primary">{t("agents.runs.load_error")}</p>
          ) : list.length === 0 ? (
            <p className="text-body-xs-regular text-tertiary">{t("agents.runs.none")}</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {list.map((run) => (
                <RunRow
                  key={run.id}
                  workspaceSlug={workspaceSlug}
                  projectId={projectId}
                  issueId={issueId}
                  run={run}
                  disabled={disabled}
                  onChanged={() => void mutate()}
                />
              ))}
            </ul>
          )}
        </div>
      </EntityDetailWidgetSection>
      {delegating && (
        <DelegateModal
          workspaceSlug={workspaceSlug}
          projectId={projectId}
          issueId={issueId}
          isOpen
          onClose={() => setDelegating(false)}
          onStarted={() => void mutate()}
        />
      )}
    </>
  );
});
