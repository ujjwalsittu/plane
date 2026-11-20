/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { EUserPermissions, EUserPermissionsLevel, WORKSPACE_SETTINGS } from "@plane/constants";
import { Breadcrumbs } from "@plane/blocks/breadcrumb";
import { useTranslation } from "@plane/i18n";
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
import { PageHead } from "@/components/core/page-title";
import { SlackIntegrationRoot } from "@/components/integration/slack/root";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
import { SettingsHeading } from "@/components/settings/heading";
import { SettingsPageHeader } from "@/components/settings/page-header";
import { WORKSPACE_SETTINGS_ICONS } from "@/components/settings/workspace/sidebar/item-icon";
import { useWorkspace } from "@/hooks/store/use-workspace";
import { useUserPermissions } from "@/hooks/store/user";
import type { Route } from "./+types/page";

function SlackSettingsHeader() {
  const { t } = useTranslation();
  const Icon = WORKSPACE_SETTINGS_ICONS.slack;
  return (
    <SettingsPageHeader
      leftItem={
        <Breadcrumbs>
          <Breadcrumbs.Item
            component={
              <BreadcrumbLink
                label={t(WORKSPACE_SETTINGS.slack.i18n_label)}
                icon={<Icon className="size-4 text-tertiary" />}
              />
            }
          />
        </Breadcrumbs>
      }
    />
  );
}

function SlackSettingsPage({ params }: Route.ComponentProps) {
  const { workspaceSlug } = params;
  const { t } = useTranslation();
  const { workspaceUserInfo, allowPermissions } = useUserPermissions();
  const { currentWorkspace } = useWorkspace();
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);
  const pageTitle = currentWorkspace?.name
    ? `${currentWorkspace.name} - ${t("supervision.slack.settings_title")}`
    : undefined;

  if (workspaceUserInfo && !isAdmin) return <NotAuthorizedView section="settings" className="h-auto" />;

  return (
    <SettingsContentWrapper header={<SlackSettingsHeader />}>
      <PageHead title={pageTitle} />
      <div className="flex w-full flex-col gap-6">
        <SettingsHeading
          title={t("supervision.slack.settings_title")}
          description={t("supervision.slack.settings_description")}
        />
        {isAdmin && <SlackIntegrationRoot workspaceSlug={workspaceSlug} />}
      </div>
    </SettingsContentWrapper>
  );
}

export default observer(SlackSettingsPage);
