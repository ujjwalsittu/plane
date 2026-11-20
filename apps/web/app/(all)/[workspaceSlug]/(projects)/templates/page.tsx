/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useTranslation } from "@plane/i18n";
import { PageHead } from "@/components/core/page-title";
import { TemplatesRoot } from "@/components/templates/list-root";
import type { Route } from "./+types/page";

function WorkspaceTemplatesPage({ params }: Route.ComponentProps) {
  const { t } = useTranslation();
  return (
    <>
      <PageHead title={t("workspace_templates.title")} />
      <TemplatesRoot workspaceSlug={params.workspaceSlug} />
    </>
  );
}

export default observer(WorkspaceTemplatesPage);
