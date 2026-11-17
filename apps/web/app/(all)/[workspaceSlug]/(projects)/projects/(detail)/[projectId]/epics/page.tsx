/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { EpicOutline } from "@makeplane/propel/icons";
import { EmptyStateCompact } from "@plane/blocks/empty-state";
import { useTranslation } from "@plane/i18n";
import { AppHeader } from "@/components/core/app-header";
import { ContentWrapper } from "@/components/core/content-wrapper";
import { PageHead } from "@/components/core/page-title";
import { EpicsView } from "@/components/milestones/epics-view";
import { ProjectSectionHeader } from "@/components/milestones/page-header";
import { useProject } from "@/hooks/store/use-project";
import type { Route } from "./+types/page";

function ProjectEpicsPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId } = params;
  const { t } = useTranslation();
  const { getProjectById } = useProject();
  const project = getProjectById(projectId);
  const label = t("epics_feature.label_plural");

  return (
    <>
      <PageHead title={project?.name ? `${project.name} - ${label}` : undefined} />
      <AppHeader
        header={
          <ProjectSectionHeader
            label={label}
            section="epics"
            icon={<EpicOutline className="h-4 w-4 text-tertiary" />}
          />
        }
      />
      <ContentWrapper>
        {project && !project.is_issue_type_enabled ? (
          <EmptyStateCompact
            assetKey="epic"
            title={t("epics_feature.no_epic_type.title")}
            description={t("epics_feature.no_epic_type.description")}
            rootClassName="h-auto py-16"
          />
        ) : (
          <EpicsView workspaceSlug={workspaceSlug} projectId={projectId} />
        )}
      </ContentWrapper>
    </>
  );
}

export default observer(ProjectEpicsPage);
