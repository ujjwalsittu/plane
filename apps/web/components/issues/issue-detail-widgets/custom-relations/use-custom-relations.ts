/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import { RelationDefinitionService } from "@/services/relation-definition.service";

const service = new RelationDefinitionService();

export const getRelationDefinitionsKey = (workspaceSlug: string) => `RELATION_DEFINITIONS_${workspaceSlug}`;

/** The workspace's own relation types and this work item's relations of those types. */
export const useCustomRelations = (workspaceSlug: string, projectId: string, issueId: string) => {
  const { t } = useTranslation();
  const { data: definitions } = useSWR(getRelationDefinitionsKey(workspaceSlug), () =>
    service.listDefinitions(workspaceSlug)
  );
  const custom = (definitions ?? []).filter((definition) => !definition.is_default && definition.is_active);
  const { data: grouped, mutate } = useSWR(custom.length ? `CUSTOM_RELATIONS_${issueId}` : null, () =>
    service.listRelations(workspaceSlug, projectId, issueId)
  );

  // Each definition offers its outward label and, when different, its inward one.
  const labels = custom.flatMap((definition) =>
    definition.inward === definition.outward
      ? [{ definitionId: definition.id, label: definition.outward }]
      : [
          { definitionId: definition.id, label: definition.outward },
          { definitionId: definition.id, label: definition.inward },
        ]
  );
  const customLabels = new Set(labels.map((entry) => entry.label));
  const groups = Object.entries(grouped ?? {}).filter(([label, items]) => customLabels.has(label) && items.length > 0);

  const add = async (definitionId: string, label: string, workItemIds: string[]) => {
    try {
      await service.addRelations(workspaceSlug, projectId, issueId, definitionId, label, workItemIds);
      await mutate();
    } catch {
      setToast({ type: "error", title: t("custom_relations.save_error") });
    }
  };

  const remove = async (relatedId: string) => {
    try {
      await service.removeRelation(workspaceSlug, projectId, issueId, relatedId);
      await mutate();
    } catch {
      setToast({ type: "error", title: t("custom_relations.save_error") });
    }
  };

  return { labels, groups, add, remove };
};
