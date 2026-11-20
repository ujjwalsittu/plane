/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Fragment } from "react";
import Link from "next/link";
import useSWR from "swr";
import { SupervisionService } from "@/services/supervision.service";

const service = new SupervisionService();

/** Splits `text` so only the identifiers in `known` (the brief's own items) become links. */
function linkify(text: string, known: Set<string>, workspaceSlug: string) {
  let offset = 0;
  return text.split(/\b([A-Z][A-Z0-9]*-\d+)\b/).map((part) => {
    const key = `${offset}:${part}`;
    offset += part.length;
    return known.has(part) ? (
      <Link
        key={key}
        href={`/${workspaceSlug}/browse/${part}/`}
        className="font-medium text-accent-primary hover:underline"
      >
        {part}
      </Link>
    ) : (
      <Fragment key={key}>{part}</Fragment>
    );
  });
}

/** The AI paragraph above the Brief. Renders nothing while loading, on error, or when there is no text. */
export function BriefSummary({ workspaceSlug }: { workspaceSlug: string }) {
  const { data, error } = useSWR(`BRIEF_SUMMARY_${workspaceSlug}`, () => service.getBriefSummary(workspaceSlug), {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  if (error || !data?.text) return null;
  const known = new Set(data.item_ids);
  return <p className="text-body-sm-regular text-secondary">{linkify(data.text, known, workspaceSlug)}</p>;
}
