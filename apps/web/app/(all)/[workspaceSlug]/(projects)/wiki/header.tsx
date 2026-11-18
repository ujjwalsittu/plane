/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { PagesOutline } from "@makeplane/propel/icons";
import { Breadcrumbs } from "@plane/blocks/breadcrumb";
import { Header } from "@plane/blocks/layout";
import { useTranslation } from "@plane/i18n";
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";

export const WorkspaceWikiHeader = observer(function WorkspaceWikiHeader() {
  const { workspaceSlug } = useParams();
  const { t } = useTranslation();
  return (
    <Header>
      <Header.LeftItem>
        <Breadcrumbs>
          <Breadcrumbs.Item
            component={
              <BreadcrumbLink
                label={t("wiki.title")}
                href={`/${workspaceSlug?.toString()}/wiki/`}
                icon={<PagesOutline className="size-4 text-tertiary" />}
              />
            }
          />
        </Breadcrumbs>
      </Header.LeftItem>
    </Header>
  );
});
