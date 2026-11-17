/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { MilestoneOutline } from "@makeplane/propel/icons";
import { useTranslation } from "@plane/i18n";
import { AppHeader } from "@/components/core/app-header";
import { ContentWrapper } from "@/components/core/content-wrapper";
import { PageHead } from "@/components/core/page-title";
import { MilestoneDetail } from "@/components/milestones/milestone-detail";
import { ProjectSectionHeader } from "@/components/milestones/page-header";
import { useMilestone } from "@/hooks/store/use-milestone";
import type { Route } from "./+types/page";

function ProjectMilestoneDetailPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId, milestoneId } = params;
  const { t } = useTranslation();
  const { getMilestoneById } = useMilestone();
  const milestone = getMilestoneById(milestoneId);

  return (
    <>
      <PageHead title={milestone?.title} />
      <AppHeader
        header={
          <ProjectSectionHeader
            label={t("milestones_feature.label_plural")}
            section="milestones"
            current={milestone?.title}
            icon={<MilestoneOutline className="h-4 w-4 text-tertiary" />}
          />
        }
      />
      <ContentWrapper>
        <MilestoneDetail workspaceSlug={workspaceSlug} projectId={projectId} milestoneId={milestoneId} />
      </ContentWrapper>
    </>
  );
}

export default observer(ProjectMilestoneDetailPage);
