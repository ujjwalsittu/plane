/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo } from "react";
import { PagesOutline, ProjectsOutline, WorkItemsOutline } from "@makeplane/propel/icons";
import type { TProject, TTemplateKind } from "@plane/types";
import { useProject } from "@/hooks/store/use-project";

export const TEMPLATE_KINDS: TTemplateKind[] = ["workitem", "page", "project"];

export const getTemplatesKey = (workspaceSlug: string) => `TEMPLATES_${workspaceSlug}`;
export const getTemplateKey = (templateId: string) => `TEMPLATE_${templateId}`;

export function TemplateKindIcon({ kind, className }: { kind: TTemplateKind; className?: string }) {
  if (kind === "page") return <PagesOutline className={className} />;
  if (kind === "project") return <ProjectsOutline className={className} />;
  return <WorkItemsOutline className={className} />;
}

/** Active projects the current user can create work items and pages in. */
export function useWritableProjects(): TProject[] {
  const { workspaceProjectIds, getProjectById } = useProject();
  return useMemo(
    () =>
      (workspaceProjectIds ?? [])
        .map((id) => getProjectById(id))
        .filter((p): p is TProject => !!p && !p.archived_at && Number(p.member_role ?? 0) >= 15),
    [workspaceProjectIds, getProjectById]
  );
}

/** Split "a, b, c" into trimmed, non-empty parts; full-width "，" and "、" count as commas too. */
export const splitList = (value: string) =>
  value
    .split(/[,，、]/)
    .map((part) => part.trim())
    .filter(Boolean);

/** Split text into trimmed, non-empty lines. */
export const splitLines = (value: string) =>
  value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

/** Rebuild a list of named objects from lines of names, keeping whatever else each one already had. */
export function mergeByName<T extends { name?: string }>(lines: string[], existing: (T | string)[] | undefined): T[] {
  const byName = new Map<string, T>();
  for (const item of existing ?? []) {
    const object = (typeof item === "string" ? { name: item } : item) as T;
    if (object.name) byName.set(object.name.toLowerCase(), object);
  }
  return lines.map((name) => ({ ...(byName.get(name.toLowerCase()) ?? ({} as T)), name }));
}

export const namesOf = (items: ({ name?: string } | string)[] | undefined) =>
  (items ?? []).map((item) => (typeof item === "string" ? item : (item.name ?? ""))).filter(Boolean);

/** A short identifier suggestion from a project name: initials, or the first letters. */
export function suggestIdentifier(name: string) {
  const words = name
    .toUpperCase()
    .replace(/[^A-Z0-9 ]/g, "")
    .split(/\s+/)
    .filter(Boolean);
  if (words.length > 1)
    return words
      .map((word) => word[0])
      .join("")
      .slice(0, 5);
  return (words[0] ?? "").slice(0, 3);
}
