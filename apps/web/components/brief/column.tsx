/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
import Link from "next/link";
import type { TSupervisionWorkItem } from "@plane/types";

/** A titled column with a count and an empty state. */
export function BriefColumn({
  title,
  count,
  empty,
  children,
}: {
  title: string;
  count: number;
  empty: string;
  children: ReactNode;
}) {
  return (
    <section className="flex min-w-0 flex-col gap-3">
      <h2 className="flex items-center gap-2 text-body-sm-medium text-primary">
        {title}
        <span className="text-caption-md-regular text-tertiary">{count}</span>
      </h2>
      {count === 0 ? (
        <p className="rounded-lg border border-subtle px-4 py-8 text-center text-body-xs-regular text-tertiary">
          {empty}
        </p>
      ) : (
        <div className="divide-y divide-subtle rounded-lg border border-subtle">{children}</div>
      )}
    </section>
  );
}

/** Identifier and name of a work item, linking to it. */
export function WorkItemLink({ workspaceSlug, issue }: { workspaceSlug: string; issue: TSupervisionWorkItem }) {
  return (
    <Link
      href={`/${workspaceSlug}/browse/${issue.identifier}/`}
      className="flex min-w-0 items-baseline gap-2 hover:underline"
    >
      <span className="shrink-0 text-caption-md-regular text-tertiary">{issue.identifier}</span>
      <span className="truncate text-body-sm-medium text-primary">{issue.name}</span>
    </Link>
  );
}
