/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import type { KeyedMutator } from "swr";
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { InputField } from "@makeplane/propel/components/input-field";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TAISettings } from "@plane/types";
import { AgentsService, agentsErrorMessage } from "@/services/agents.service";
import { centsToDollarInput, dollarInputToCents, formatCents } from "./money";

const service = new AgentsService();

type Props = {
  workspaceSlug: string;
  settings: TAISettings;
  mutate: KeyedMutator<TAISettings>;
};

/** The workspace's Claude key, model and monthly limit, plus the cloud agents setup. */
export const AISettingsCard = observer(function AISettingsCard({ workspaceSlug, settings, mutate }: Props) {
  const { t } = useTranslation();
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(settings.model);
  const [limit, setLimit] = useState(
    settings.monthly_limit_cents === null ? "" : centsToDollarInput(settings.monthly_limit_cents)
  );
  const [saving, setSaving] = useState(false);
  const [settingUp, setSettingUp] = useState(false);
  const [setupError, setSetupError] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);

  // Follow the server after a save or a refetch.
  useEffect(() => {
    setModel(settings.model);
    setLimit(settings.monthly_limit_cents === null ? "" : centsToDollarInput(settings.monthly_limit_cents));
  }, [settings.model, settings.monthly_limit_cents]);

  const limitCents = limit.trim() === "" ? null : dollarInputToCents(limit);
  const limitInvalid = limit.trim() !== "" && limitCents === null;
  const dirty = apiKey.trim() !== "" || model.trim() !== settings.model || limitCents !== settings.monthly_limit_cents;

  const handleSave = async () => {
    if (limitInvalid) return;
    setSaving(true);
    try {
      const body: { api_key?: string; model?: string; monthly_limit_cents?: number | null } = {
        model: model.trim(),
        monthly_limit_cents: limitCents,
      };
      if (apiKey.trim()) body.api_key = apiKey.trim();
      await mutate(service.updateAISettings(workspaceSlug, body), { revalidate: false });
      setApiKey("");
      setToast({ type: "success", title: t("agents.ai.saved") });
    } catch (e) {
      setToast({ type: "error", title: agentsErrorMessage(e) ?? t("agents.ai.save_error") });
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveKey = async () => {
    try {
      await mutate(service.clearAIKey(workspaceSlug), { revalidate: false });
      setToast({ type: "success", title: t("agents.ai.key_removed") });
    } catch (e) {
      setToast({ type: "error", title: agentsErrorMessage(e) ?? t("agents.ai.remove_key_error") });
    } finally {
      setConfirmRemove(false);
    }
  };

  const handleSetup = async () => {
    setSettingUp(true);
    setSetupError(null);
    try {
      await mutate(service.setupCloudAgents(workspaceSlug), { revalidate: false });
      setToast({ type: "success", title: t("agents.ai.cloud_setup_done") });
    } catch (e) {
      // Setup errors come back on the cloud_agents field; show them next to the button.
      setSetupError(agentsErrorMessage(e) ?? t("agents.ai.cloud_setup_error"));
    } finally {
      setSettingUp(false);
    }
  };

  const statusLabel =
    settings.status === "ok"
      ? t("agents.ai.status_ok")
      : settings.status === "broken"
        ? t("agents.ai.status_broken")
        : t("agents.ai.status_unknown");

  return (
    <section className="flex flex-col gap-4 rounded-lg border border-subtle px-4 py-4">
      <div className="flex flex-col gap-1">
        <h4 className="text-h6-medium text-primary">{t("agents.ai.title")}</h4>
        <p className="text-body-xs-regular text-tertiary">{t("agents.ai.description")}</p>
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-body-sm-medium text-primary">{t("agents.ai.key_status")}</span>
          {settings.has_key && (
            <Badge
              variant={settings.status === "ok" ? "success" : settings.status === "broken" ? "warning" : "neutral"}
              size="sm"
              label={statusLabel}
            />
          )}
          {settings.has_key && (
            <div className="ml-auto">
              <Button
                variant="danger-outline"
                size="sm"
                stretch="auto"
                label={t("agents.ai.remove_key")}
                onClick={() => setConfirmRemove(true)}
              />
            </div>
          )}
        </div>
        <p className="text-body-xs-regular text-tertiary">
          {settings.has_key
            ? t("agents.ai.has_key")
            : settings.uses_instance_key
              ? t("agents.ai.uses_instance_key")
              : t("agents.ai.no_key")}
        </p>
        {settings.last_error && <p className="text-body-xs-regular text-danger-primary">{settings.last_error}</p>}
      </div>

      <div className="grid max-w-2xl gap-3 md:grid-cols-2">
        <div className="md:col-span-2">
          <InputField
            size="md"
            orientation="vertical"
            type="password"
            autoComplete="off"
            label={t("agents.ai.api_key")}
            value={apiKey}
            maxLength={255}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={t("agents.ai.api_key_placeholder")}
          />
        </div>
        <InputField
          size="md"
          orientation="vertical"
          type="text"
          label={t("agents.ai.model")}
          value={model}
          maxLength={100}
          onChange={(e) => setModel(e.target.value)}
        />
        <InputField
          size="md"
          orientation="vertical"
          type="text"
          inputMode="decimal"
          label={t("agents.ai.monthly_limit")}
          value={limit}
          onChange={(e) => setLimit(e.target.value)}
          hint={t("agents.ai.monthly_limit_hint")}
          error={limitInvalid ? t("agents.ai.invalid_limit") : undefined}
        />
      </div>

      <p className="text-body-sm-regular text-secondary">
        {t("agents.ai.spent_this_month")}:{" "}
        <span className="text-primary">{formatCents(settings.spent_this_month_cents)}</span>
        {settings.monthly_limit_cents !== null && (
          <span className="text-tertiary"> / {formatCents(settings.monthly_limit_cents)}</span>
        )}
      </p>

      <div>
        <Button
          variant="primary"
          size="md"
          stretch="auto"
          loading={saving}
          disabled={!dirty || limitInvalid}
          label={t("agents.ai.save")}
          onClick={() => void handleSave()}
        />
      </div>

      <div className="flex flex-col gap-2 border-t border-subtle pt-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-body-sm-medium text-primary">{t("agents.ai.cloud")}</span>
          <Badge
            variant={settings.cloud_agents_ready ? "success" : "neutral"}
            size="sm"
            label={settings.cloud_agents_ready ? t("agents.ai.cloud_ready") : t("agents.ai.cloud_not_ready")}
          />
        </div>
        <p className="text-body-xs-regular text-tertiary">{t("agents.ai.cloud_hint")}</p>
        {setupError && (
          <p role="alert" className="text-body-xs-regular text-danger-primary">
            {setupError}
          </p>
        )}
        <div>
          <Button
            variant="secondary"
            size="md"
            stretch="auto"
            loading={settingUp}
            label={t("agents.ai.cloud_setup")}
            onClick={() => void handleSetup()}
          />
        </div>
      </div>

      <ConfirmDialog
        isOpen={confirmRemove}
        handleClose={() => setConfirmRemove(false)}
        handleSubmit={handleRemoveKey}
        isSubmitting={false}
        title={t("agents.ai.remove_key_title")}
        content={t("agents.ai.remove_key_description")}
      />
    </section>
  );
});
