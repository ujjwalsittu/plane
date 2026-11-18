/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { useTranslation } from "@plane/i18n";
// components
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { PageHead } from "@/components/core/page-title";
import { ProjectSettingsFeatureControlItem } from "@/components/settings/project/content/feature-control-item";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import type { Route } from "./+types/page";
import { FeaturesIssueTypesProjectSettingsHeader } from "./header";
import { SettingsHeading } from "@/components/settings/heading";
import { IssuePropertiesSettings } from "@/components/issue-types/properties-settings";
import { IssueTypesSettingsRoot } from "@/components/issue-types/settings-root";
import { useMilestone } from "@/hooks/store/use-milestone";

function FeaturesIssueTypesSettingsPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId } = params;
  // store hooks
  const { workspaceUserInfo, allowPermissions } = useUserPermissions();
  const { currentProjectDetails } = useProject();
  // translation
  const { t } = useTranslation();
  const { getProjectIssueTypes } = useMilestone();
  // derived values
  const pageTitle = currentProjectDetails?.name
    ? `${currentProjectDetails?.name} settings - ${t("issue_types_feature.settings.short_title")}`
    : undefined;
  const canPerformProjectAdminActions = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT);

  if (workspaceUserInfo && !canPerformProjectAdminActions) {
    return <NotAuthorizedView section="settings" isProjectView className="h-auto" />;
  }

  return (
    <SettingsContentWrapper header={<FeaturesIssueTypesProjectSettingsHeader />}>
      <PageHead title={pageTitle} />
      <section className="w-full">
        <SettingsHeading
          title={t("issue_types_feature.settings.title")}
          description={t("issue_types_feature.settings.description")}
        />
        <div className="mt-7">
          <ProjectSettingsFeatureControlItem
            title={t("issue_types_feature.settings.toggle_title")}
            description={t("issue_types_feature.settings.toggle_description")}
            featureProperty="is_issue_type_enabled"
            projectId={projectId}
            value={!!currentProjectDetails?.is_issue_type_enabled}
            workspaceSlug={workspaceSlug}
          />
        </div>
        {currentProjectDetails?.is_issue_type_enabled && (
          <div className="mt-6">
            <IssueTypesSettingsRoot workspaceSlug={workspaceSlug} projectId={projectId} />
          </div>
        )}
        {/* Properties don't need types: without them they apply to every work item. */}
        <div className="mt-10">
          <IssuePropertiesSettings
            workspaceSlug={workspaceSlug}
            projectId={projectId}
            issueTypes={currentProjectDetails?.is_issue_type_enabled ? (getProjectIssueTypes(projectId) ?? []) : []}
          />
        </div>
      </section>
    </SettingsContentWrapper>
  );
}

export default observer(FeaturesIssueTypesSettingsPage);
