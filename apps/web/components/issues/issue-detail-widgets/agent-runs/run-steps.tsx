/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { LinkOutline } from "@makeplane/propel/icons";
import { useTranslation } from "@plane/i18n";
import type { TAgentRun, TAgentRunStep } from "@plane/types";

const isUrl = (value: unknown): value is string => typeof value === "string" && /^https?:\/\//.test(value);

/** A step's own link, else the run's link it names by ref. */
const stepUrl = (step: TAgentRunStep, links: TAgentRun["links"]): string | null => {
  if (isUrl(step.data?.url)) return step.data.url;
  const ref = typeof step.data?.ref === "string" ? step.data.ref : step.text;
  const link = links.find((l) => l.ref && (l.ref === ref || step.text.includes(l.ref)));
  return link && isUrl(link.url) ? link.url : null;
};

/** The steps an agent reported: messages as text, tools on one line, pull requests and commits as links. */
export function RunSteps({ steps, links }: { steps: TAgentRunStep[]; links: TAgentRun["links"] }) {
  const { t } = useTranslation();
  if (steps.length === 0) return <p className="text-body-xs-regular text-tertiary">{t("agents.runs.no_steps")}</p>;
  return (
    <ol className="flex flex-col gap-1.5">
      {steps.map((step) => {
        const url = stepUrl(step, links);
        if (step.kind === "message")
          return (
            <li key={step.id} className="text-body-xs-regular break-words whitespace-pre-wrap text-secondary">
              {step.text}
            </li>
          );
        if (step.kind === "pr" || step.kind === "commit")
          return (
            <li key={step.id} className="flex items-center gap-1.5 text-body-xs-regular">
              <span className="shrink-0 text-tertiary">
                {t(step.kind === "pr" ? "agents.runs.pull_request" : "agents.runs.commit")}
              </span>
              {url ? (
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex min-w-0 items-center gap-1 text-accent-primary hover:underline"
                >
                  <span className="truncate">{step.text || url}</span>
                  <LinkOutline className="size-3 shrink-0" aria-hidden />
                </a>
              ) : (
                <span className="truncate text-secondary">{step.text}</span>
              )}
            </li>
          );
        return (
          <li
            key={step.id}
            className={
              step.kind === "error"
                ? "truncate text-caption-md-regular text-danger-primary"
                : "font-mono truncate text-caption-md-regular text-tertiary"
            }
            title={step.text}
          >
            {step.text}
          </li>
        );
      })}
    </ol>
  );
}
