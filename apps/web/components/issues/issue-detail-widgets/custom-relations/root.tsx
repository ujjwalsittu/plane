/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import { EntityDetailWidgetSection } from "@plane/blocks/entity-detail";
import { useTranslation } from "@plane/i18n";
import { useProject } from "@/hooks/store/use-project";
import { useCustomRelations } from "./use-custom-relations";

type Props = { workspaceSlug: string; projectId: string; issueId: string; disabled?: boolean };

/** Work items related through the workspace's own relation types, grouped by label. */
export const CustomRelationsCollapsible = observer(function CustomRelationsCollapsible(props: Props) {
  const { workspaceSlug, projectId, issueId, disabled = false } = props;
  const { t } = useTranslation();
  const { getProjectIdentifierById } = useProject();
  const [isOpen, setIsOpen] = useState(true);
  const { groups, remove } = useCustomRelations(workspaceSlug, projectId, issueId);

  const count = groups.reduce((total, [, items]) => total + items.length, 0);
  if (count === 0) return null;

  return (
    <EntityDetailWidgetSection
      title={t("custom_relations.title")}
      count={count}
      isOpen={isOpen}
      onToggle={() => setIsOpen((value) => !value)}
    >
      <div className="flex flex-col gap-3 py-1">
        {groups.map(([label, items]) => (
          <div key={label} className="flex flex-col gap-0.5">
            <span className="px-2 text-caption-md-medium text-tertiary">{label}</span>
            {items.map((item) => {
              const identifier = `${getProjectIdentifierById(item.project_id) ?? ""}-${item.sequence_id}`;
              return (
                <div key={item.id} className="group flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-layer-1">
                  <span className="shrink-0 text-caption-md-medium text-tertiary">{identifier}</span>
                  <Link
                    href={`/${workspaceSlug}/browse/${identifier}/`}
                    className="min-w-0 flex-1 truncate text-body-xs-medium text-primary"
                  >
                    {item.name}
                  </Link>
                  {!disabled && (
                    <button
                      type="button"
                      className="text-caption-sm-regular text-tertiary opacity-0 group-hover:opacity-100 hover:text-danger-primary focus-visible:opacity-100"
                      onClick={() => void remove(item.id)}
                    >
                      {t("custom_relations.remove")}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </EntityDetailWidgetSection>
  );
});
