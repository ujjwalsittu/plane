/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { Button } from "@makeplane/propel/components/button";
import { InputField } from "@makeplane/propel/components/input-field";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TDecisionRequest } from "@plane/types";
import { SupervisionService } from "@/services/supervision.service";

const service = new SupervisionService();

/** Answers a decision in place: one button per option, or a text field when it has none. */
export function DecisionAnswer({
  workspaceSlug,
  projectId,
  issueId,
  decision,
  onAnswered,
}: {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  decision: TDecisionRequest;
  onAnswered: () => void;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (answer: string) => {
    setBusy(true);
    try {
      await service.answerDecision(workspaceSlug, projectId, issueId, decision.id, answer);
      onAnswered();
    } catch (error) {
      setToast({ type: "error", title: (error as { error?: string })?.error ?? t("supervision.answer_error") });
      // Someone else may have answered first; refresh so the row reflects it.
      onAnswered();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <p className="text-body-xs-regular text-secondary">{decision.question}</p>
      {decision.options.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {decision.options.map((option) => (
            <Button
              key={option}
              variant="secondary"
              size="sm"
              stretch="auto"
              disabled={busy}
              label={option}
              onClick={() => void submit(option)}
            />
          ))}
        </div>
      ) : (
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) void submit(text.trim());
          }}
        >
          <div className="flex-1">
            <InputField
              size="md"
              orientation="vertical"
              value={text}
              onChange={(e) => setText(e.target.value)}
              aria-label={t("supervision.answer_placeholder")}
              placeholder={t("supervision.answer_placeholder")}
            />
          </div>
          <Button
            type="submit"
            variant="primary"
            size="sm"
            stretch="auto"
            loading={busy}
            disabled={!text.trim()}
            label={t("supervision.answer_submit")}
          />
        </form>
      )}
    </div>
  );
}
