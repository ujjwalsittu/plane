/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useTranslation } from "@plane/i18n";
import { PageHead } from "@/components/core/page-title";
import { WikiRoot } from "@/components/wiki/root";
import type { Route } from "./+types/page";

function WorkspaceWikiPage({ params }: Route.ComponentProps) {
  const { t } = useTranslation();
  return (
    <>
      <PageHead title={t("wiki.title")} />
      <WikiRoot workspaceSlug={params.workspaceSlug} />
    </>
  );
}

export default observer(WorkspaceWikiPage);
