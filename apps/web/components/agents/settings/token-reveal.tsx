/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

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
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import { copyTextToClipboard } from "@plane/utils";

type Props = {
  /** The one-time token; the dialog is open while it is set. */
  token: string | null;
  agentName: string;
  onClose: () => void;
};

/** Shows an agent's token once, right after it is created or rotated, with a copy button. */
export function AgentTokenReveal({ token, agentName, onClose }: Props) {
  const { t } = useTranslation();

  const handleCopy = async () => {
    if (!token) return;
    try {
      await copyTextToClipboard(token);
      setToast({ type: "success", title: t("agents.token.copied") });
    } catch {
      setToast({ type: "error", title: t("agents.token.copy_error") });
    }
  };

  return (
    <Dialog
      open={!!token}
      // Only the button closes it: ignore Escape and outside presses so the token is not lost before it is stored.
      disablePointerDismissal
      onOpenChange={() => {}}
    >
      <DialogContent size="sm">
        <DialogMain>
          <DialogHeader>
            <DialogHeading>
              <DialogTitle>
                {t("agents.token.title")} · {agentName}
              </DialogTitle>
            </DialogHeading>
          </DialogHeader>
          <DialogBody>
            <div className="flex flex-col gap-3">
              <p className="text-body-sm-regular text-secondary">{t("agents.token.store_now")}</p>
              <code className="font-mono rounded-md border border-subtle bg-layer-1 px-3 py-2 text-body-xs-regular break-all text-primary select-all">
                {token}
              </code>
            </div>
          </DialogBody>
        </DialogMain>
        <DialogActions>
          <Button
            variant="secondary"
            size="md"
            stretch="auto"
            label={t("agents.token.copy")}
            onClick={() => void handleCopy()}
          />
          <Button variant="primary" size="md" stretch="auto" label={t("agents.token.done")} onClick={onClose} />
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
}
