/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
// components
import { LoopsRoot } from "@/components/agents/loops/root";
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { PageHead } from "@/components/core/page-title";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
import { SettingsHeading } from "@/components/settings/heading";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import type { Route } from "./+types/page";
import { LoopsProjectSettingsHeader } from "./header";

function LoopsSettingsPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId } = params;
  const { t } = useTranslation();
  const { workspaceUserInfo, allowPermissions } = useUserPermissions();
  const { currentProjectDetails } = useProject();

  // Members see loops and their runs; project admins and workspace admins manage them
  const canView = allowPermissions([EUserPermissions.ADMIN, EUserPermissions.MEMBER], EUserPermissionsLevel.PROJECT);
  const canManage =
    allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT) ||
    allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);

  const pageTitle = currentProjectDetails?.name
    ? `${currentProjectDetails.name} - ${t("agents.loops.settings_title")}`
    : undefined;

  if (workspaceUserInfo && !canView) {
    return <NotAuthorizedView section="settings" isProjectView className="h-auto" />;
  }

  return (
    <SettingsContentWrapper header={<LoopsProjectSettingsHeader />} hugging>
      <PageHead title={pageTitle} />
      <section className="w-full">
        <SettingsHeading
          title={t("agents.loops.settings_title")}
          description={t("agents.loops.settings_description")}
        />
        <div className="mt-6">
          <LoopsRoot workspaceSlug={workspaceSlug} projectId={projectId} canManage={canManage} />
        </div>
      </section>
    </SettingsContentWrapper>
  );
}

export default observer(LoopsSettingsPage);
