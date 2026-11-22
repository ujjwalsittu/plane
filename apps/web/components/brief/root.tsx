/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
import { Button } from "@makeplane/propel/components/button";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import { renderFormattedDate } from "@plane/utils";
import { SupervisionService } from "@/services/supervision.service";
import { BriefAsk } from "./ask";
import { BlockedColumn } from "./blocked";
import { DoneColumn } from "./done";
import { MilestonesDue } from "./milestones-due";
import { NeedsMeColumn } from "./needs-me";
import { ProjectsStrip } from "./projects-strip";
import { BriefSummary } from "./summary";

const service = new SupervisionService();

const briefKey = (workspaceSlug: string) => `BRIEF_${workspaceSlug}`;
const decisionsKey = (workspaceSlug: string) => `BRIEF_DECISIONS_${workspaceSlug}`;

/** What needs me, what is blocked and what got done since I last looked. */
export const BriefRoot = observer(function BriefRoot({ workspaceSlug }: { workspaceSlug: string }) {
  const { t } = useTranslation();
  const {
    data: brief,
    error,
    mutate: refreshBrief,
  } = useSWR(briefKey(workspaceSlug), () => service.getBrief(workspaceSlug));
  const {
    data: decisions,
    error: decisionsError,
    mutate: refreshDecisions,
  } = useSWR(decisionsKey(workspaceSlug), () => service.listOpenDecisions(workspaceSlug));
  const [marking, setMarking] = useState(false);

  const refresh = async () => {
    await Promise.all([refreshBrief(), refreshDecisions()]);
  };

  const markSeen = async () => {
    setMarking(true);
    try {
      await service.markSeen(workspaceSlug);
      await refresh();
    } catch (e) {
      setToast({ type: "error", title: (e as { error?: string })?.error ?? t("supervision.mark_seen_error") });
    } finally {
      setMarking(false);
    }
  };

  if (error) {
    return <p className="px-6 py-6 text-body-sm-regular text-tertiary">{t("supervision.load_error")}</p>;
  }
  if (!brief) return <p className="px-6 py-6 text-body-sm-regular text-tertiary">{t("supervision.loading")}</p>;

  const since = renderFormattedDate(brief.since);
  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-6 py-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {since ? (
          <p className="text-caption-md-regular text-tertiary">{t("supervision.since", { date: since })}</p>
        ) : (
          <span />
        )}
        <Button
          variant="secondary"
          size="sm"
          stretch="auto"
          loading={marking}
          label={t("supervision.mark_seen")}
          onClick={() => void markSeen()}
        />
      </div>
      <BriefSummary workspaceSlug={workspaceSlug} />
      <BriefAsk workspaceSlug={workspaceSlug} />
      <MilestonesDue milestones={brief.milestones_due} />
      <ProjectsStrip workspaceSlug={workspaceSlug} projects={brief.projects} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <NeedsMeColumn
          workspaceSlug={workspaceSlug}
          rows={brief.needs_me}
          decisions={decisions}
          decisionsError={!!decisionsError}
          onAnswered={() => void refresh()}
        />
        <BlockedColumn workspaceSlug={workspaceSlug} rows={brief.blocked} />
        <DoneColumn workspaceSlug={workspaceSlug} groups={brief.done} />
      </div>
    </div>
  );
});
