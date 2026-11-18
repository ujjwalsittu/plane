/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { cloneElement, useState } from "react";
import { observer } from "mobx-react";
import { Button } from "@makeplane/propel/components/button";
import {
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogHeading,
  DialogMain,
  DialogTitle,
} from "@makeplane/propel/components/dialog";
import { InputField } from "@makeplane/propel/components/input-field";
import { TextAreaField } from "@makeplane/propel/components/text-area-field";
import { Tooltip } from "@makeplane/propel/components/tooltip";
import { useTranslation } from "@plane/i18n";
import { formatDuration, parseDuration } from "./duration";
import { useWorkLogs } from "./use-work-logs";

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  customButton: React.ReactElement<React.ComponentPropsWithoutRef<"button">>;
  tooltip?: string;
};

/** "Log time": a small dialog taking "1h 30m"-style durations and a note. */
export const WorkLogActionButton = observer(function WorkLogActionButton(props: Props) {
  const { workspaceSlug, projectId, issueId, customButton, tooltip } = props;
  const { t } = useTranslation();
  const { enabled, log } = useWorkLogs(workspaceSlug, projectId, issueId);
  const [isOpen, setIsOpen] = useState(false);
  const [duration, setDuration] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!enabled) return null;

  const minutes = parseDuration(duration);
  const close = () => {
    setIsOpen(false);
    setDuration("");
    setDescription("");
  };
  const submit = async () => {
    if (!minutes) return;
    setSubmitting(true);
    const ok = await log(minutes, description.trim());
    setSubmitting(false);
    if (ok) close();
  };

  const button = cloneElement(customButton, {
    onClick: (e: React.MouseEvent<HTMLButtonElement>) => {
      e.preventDefault();
      setIsOpen(true);
    },
  });

  return (
    <>
      {tooltip ? <Tooltip label={tooltip}>{button}</Tooltip> : button}
      <Dialog
        open={isOpen}
        onOpenChange={(open) => {
          if (!open) close();
        }}
      >
        <DialogContent size="sm">
          <form
            className="flex min-h-0 flex-1 flex-col"
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <DialogMain>
              <DialogHeader>
                <DialogHeading>
                  <DialogTitle>{t("work_logs.log_time")}</DialogTitle>
                </DialogHeading>
              </DialogHeader>
              <DialogBody tabIndex={0}>
                <div className="space-y-3">
                  <InputField
                    size="xl"
                    orientation="vertical"
                    value={duration}
                    onChange={(e) => setDuration(e.target.value)}
                    placeholder={t("work_logs.duration_placeholder")}
                    aria-label={t("work_logs.duration")}
                    error={duration && !minutes ? t("work_logs.duration_invalid") : undefined}
                  />
                  {minutes && (
                    <p className="text-caption-md-regular text-tertiary">
                      {t("work_logs.duration_preview", { duration: formatDuration(minutes) })}
                    </p>
                  )}
                  <TextAreaField
                    size="xl"
                    autoResize
                    maxRows={6}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder={t("work_logs.description_placeholder")}
                    aria-label={t("work_logs.description")}
                  />
                </div>
              </DialogBody>
            </DialogMain>
            <DialogActions>
              <Button variant="secondary" size="md" stretch="auto" onClick={close} label={t("common.cancel")} />
              <Button
                type="submit"
                variant="primary"
                size="md"
                stretch="auto"
                loading={submitting}
                disabled={!minutes}
                label={t("work_logs.log_time")}
              />
            </DialogActions>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
});
