/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { InputField } from "@makeplane/propel/components/input-field";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import { SlackConnectionService } from "@/services/slack-connection.service";

const service = new SlackConnectionService();

const errorMessage = (error: unknown) => (error as { error?: string } | undefined)?.error;

/** Workspace settings: connect the workspace's Slack app with a bot token, reconnect it, or disconnect. */
export const SlackIntegrationRoot = observer(function SlackIntegrationRoot({
  workspaceSlug,
}: {
  workspaceSlug: string;
}) {
  const { t } = useTranslation();
  const { data, error, mutate, isLoading } = useSWR(`SLACK_CONNECTION_${workspaceSlug}`, () =>
    service.getConnection(workspaceSlug)
  );
  const [token, setToken] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);

  const handleConnect = async () => {
    if (!token.trim()) return;
    setSaving(true);
    try {
      await mutate(service.connect(workspaceSlug, token.trim()), { revalidate: false });
      setToken("");
      setToast({ type: "success", title: t("supervision.slack.connected") });
    } catch (e) {
      setToast({ type: "error", title: errorMessage(e) ?? t("supervision.slack.connect_error") });
    } finally {
      setSaving(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      await service.disconnect(workspaceSlug);
      await mutate();
    } catch (e) {
      setToast({ type: "error", title: errorMessage(e) ?? t("supervision.slack.disconnect_error") });
    } finally {
      setConfirmDisconnect(false);
    }
  };

  if (error) return <div className="text-body-sm-regular text-danger-primary">{t("supervision.slack.load_error")}</div>;
  if (isLoading || !data) return <div className="text-body-sm-regular text-tertiary">{t("loading")}</div>;

  const broken = data.status === "broken";

  return (
    <div className="flex flex-col gap-6">
      {data.connected ? (
        <section className="flex flex-col gap-2 rounded-lg border border-subtle px-4 py-3">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-body-sm-medium text-primary">{t("supervision.slack.status")}</span>
            <Badge
              variant={broken ? "warning" : "success"}
              size="sm"
              label={broken ? t("supervision.slack.status_broken") : t("supervision.slack.status_ok")}
            />
            <div className="ml-auto">
              <Button
                variant="danger-outline"
                size="sm"
                stretch="auto"
                label={t("supervision.slack.disconnect")}
                onClick={() => setConfirmDisconnect(true)}
              />
            </div>
          </div>
          {broken && <p className="text-body-xs-regular text-tertiary">{t("supervision.slack.reconnect_hint")}</p>}
          <p className="text-body-xs-regular text-tertiary">
            {t("supervision.slack.team")}: <span className="text-primary">{data.team_name}</span>
            {" · "}
            {t("supervision.slack.linked_users", { count: data.linked_users })}
          </p>
        </section>
      ) : (
        <p className="rounded-lg border border-subtle px-4 py-3 text-body-xs-regular text-tertiary">
          {t("supervision.slack.not_connected")}
        </p>
      )}

      <section className="flex flex-col gap-3">
        <div className="max-w-md">
          <InputField
            size="md"
            orientation="vertical"
            type="password"
            autoComplete="off"
            value={token}
            maxLength={255}
            onChange={(e) => setToken(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void handleConnect();
            }}
            aria-label={t("supervision.slack.bot_token")}
            placeholder={t("supervision.slack.bot_token_placeholder")}
          />
        </div>
        <div>
          <Button
            variant="primary"
            size="md"
            stretch="auto"
            loading={saving}
            disabled={!token.trim()}
            label={data.connected ? t("supervision.slack.reconnect") : t("supervision.slack.connect")}
            onClick={() => void handleConnect()}
          />
        </div>
      </section>

      <ConfirmDialog
        isOpen={confirmDisconnect}
        handleClose={() => setConfirmDisconnect(false)}
        handleSubmit={handleDisconnect}
        isSubmitting={false}
        title={t("supervision.slack.disconnect_title")}
        content={t("supervision.slack.disconnect_description")}
      />
    </div>
  );
});
