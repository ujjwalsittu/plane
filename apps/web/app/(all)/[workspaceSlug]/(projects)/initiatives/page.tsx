/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useTranslation } from "@plane/i18n";
import { PageHead } from "@/components/core/page-title";
import { InitiativesRoot } from "@/components/initiatives/list-root";
import type { Route } from "./+types/page";

function WorkspaceInitiativesPage({ params }: Route.ComponentProps) {
  const { t } = useTranslation();
  return (
    <>
      <PageHead title={t("initiatives.title")} />
      <InitiativesRoot workspaceSlug={params.workspaceSlug} />
    </>
  );
}

export default observer(WorkspaceInitiativesPage);
