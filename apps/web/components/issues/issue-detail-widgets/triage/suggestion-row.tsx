/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import Link from "next/link";
import { Button } from "@makeplane/propel/components/button";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";

type Props = {
  kind: string;
  title: string;
  /** In-app link for the suggestion (a project or a possible duplicate). */
  href?: string;
  reason: string;
  /** The button label; without `onApply` the row is text (and its link) only. */
  actionLabel?: string;
  onApply?: () => Promise<void>;
};

/** One suggestion: what it is, why Claude suggests it, and the button that applies it. */
export function TriageSuggestionRow(props: Props) {
  const { kind, title, href, reason, actionLabel, onApply } = props;
  const { t } = useTranslation();
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState(false);

  const apply = async () => {
    if (!onApply || applying || applied) return;
    setApplying(true);
    try {
      await onApply();
      setApplied(true);
    } catch {
      setToast({ type: "error", title: t("agents.triage.apply_error") });
    } finally {
      setApplying(false);
    }
  };

  return (
    <li className="flex items-start justify-between gap-3 rounded-md border border-subtle px-3 py-2">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-caption-md-medium text-tertiary">{kind}</span>
        {href ? (
          <Link href={href} className="truncate text-body-xs-medium text-accent-primary hover:underline">
            {title}
          </Link>
        ) : (
          <span className="truncate text-body-xs-medium text-primary">{title}</span>
        )}
        {reason && <span className="text-caption-md-regular text-secondary">{reason}</span>}
      </div>
      {onApply && (
        <Button
          variant="secondary"
          size="sm"
          stretch="auto"
          loading={applying}
          disabled={applied}
          label={applied ? t("agents.triage.applied") : (actionLabel ?? t("agents.triage.apply"))}
          onClick={() => void apply()}
        />
      )}
    </li>
  );
}
