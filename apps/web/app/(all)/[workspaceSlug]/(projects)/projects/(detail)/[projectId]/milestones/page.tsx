/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { Button } from "@makeplane/propel/components/button";
import { MilestoneOutline } from "@makeplane/propel/icons";
import { EmptyStateCompact } from "@plane/blocks/empty-state";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { AppHeader } from "@/components/core/app-header";
import { ContentWrapper } from "@/components/core/content-wrapper";
import { PageHead } from "@/components/core/page-title";
import { MilestonesList } from "@/components/milestones/milestones-list";
import { ProjectSectionHeader } from "@/components/milestones/page-header";
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
import type { Route } from "./+types/page";

function ProjectMilestonesPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId } = params;
  const { t } = useTranslation();
  const { getProjectById } = useProject();
  const { allowPermissions } = useUserPermissions();
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const project = getProjectById(projectId);
  const canCreate = allowPermissions([EUserPermissions.ADMIN, EUserPermissions.MEMBER], EUserPermissionsLevel.PROJECT);
  const label = t("milestones_feature.label_plural");

  return (
    <>
      <PageHead title={project?.name ? `${project.name} - ${label}` : undefined} />
      <AppHeader
        header={
          <ProjectSectionHeader
            label={label}
            section="milestones"
            icon={<MilestoneOutline className="h-4 w-4 text-tertiary" />}
            rightItem={
              canCreate && project?.milestone_view ? (
                <Button
                  variant="primary"
                  size="md"
                  stretch="auto"
                  label={t("milestones_feature.add")}
                  onClick={() => setIsCreateOpen(true)}
                />
              ) : undefined
            }
          />
        }
      />
      <ContentWrapper>
        {project && !project.milestone_view ? (
          <EmptyStateCompact
            assetKey="milestone"
            title={t("milestones_feature.disabled.title")}
            description={t("milestones_feature.disabled.description")}
            rootClassName="h-auto py-16"
          />
        ) : (
          <MilestonesList
            workspaceSlug={workspaceSlug}
            projectId={projectId}
            isCreateOpen={isCreateOpen}
            onCreateClose={() => setIsCreateOpen(false)}
          />
        )}
      </ContentWrapper>
    </>
  );
}

export default observer(ProjectMilestonesPage);
