/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { OverviewOutline } from "@makeplane/propel/icons";
import { useTranslation } from "@plane/i18n";
import { AppHeader } from "@/components/core/app-header";
import { ContentWrapper } from "@/components/core/content-wrapper";
import { PageHead } from "@/components/core/page-title";
import { ProjectSectionHeader } from "@/components/milestones/page-header";
import { ProjectOverviewRoot } from "@/components/project-overview/root";
import { useProject } from "@/hooks/store/use-project";
import type { Route } from "./+types/page";

function ProjectOverviewPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId } = params;
  const { t } = useTranslation();
  const { getProjectById } = useProject();
  const project = getProjectById(projectId);
  const label = t("project_overview.label");

  return (
    <>
      <PageHead title={project?.name ? `${project.name} - ${label}` : undefined} />
      <AppHeader
        header={
          <ProjectSectionHeader
            label={label}
            section="overview"
            icon={<OverviewOutline className="h-4 w-4 text-tertiary" />}
          />
        }
      />
      <ContentWrapper>
        <ProjectOverviewRoot workspaceSlug={workspaceSlug} projectId={projectId} />
      </ContentWrapper>
    </>
  );
}

export default observer(ProjectOverviewPage);
