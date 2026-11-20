/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import useSWR, { mutate as globalMutate } from "swr";
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { InputField } from "@makeplane/propel/components/input-field";
import { Switch } from "@makeplane/propel/components/switch";
import { TextAreaField } from "@makeplane/propel/components/text-area-field";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { Select } from "@plane/blocks/select";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type {
  TProject,
  TTemplate,
  TTemplateProjectBody,
  TTemplateUseResult,
  TTemplateWorkItemBody,
} from "@plane/types";
import { EFileAssetType } from "@plane/types";
import { PageHead } from "@/components/core/page-title";
import { DescriptionInput } from "@/components/editor/rich-text/description-input/root";
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";
import { TemplateService } from "@/services/template.service";
import {
  getTemplateKey,
  getTemplatesKey,
  mergeByName,
  namesOf,
  splitLines,
  splitList,
  suggestIdentifier,
  TemplateKindIcon,
  useWritableProjects,
} from "./common";

const service = new TemplateService();

type TBody = TTemplate["template_data"];
type TOption = { id: string; name: string };

const PRIORITIES = ["none", "urgent", "high", "medium", "low"] as const;
const STATE_GROUPS = ["backlog", "unstarted", "started", "completed", "cancelled"] as const;
const FEATURES = ["cycles", "modules", "views", "pages", "intake", "time_tracking"] as const;
type TStateRow = NonNullable<TTemplateProjectBody["states"]>[number];

const errorMessage = (error: unknown) => (error as { error?: string } | undefined)?.error;

/** A text input that saves on blur when its value changed. */
function BlurInput(props: {
  label?: string;
  ariaLabel?: string;
  value: string;
  placeholder?: string;
  hint?: string;
  disabled?: boolean;
  onSave: (value: string) => void;
}) {
  const { label, ariaLabel, value, placeholder, hint, disabled, onSave } = props;
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <InputField
      size="md"
      orientation="vertical"
      label={label}
      aria-label={ariaLabel ?? label}
      hint={hint}
      value={draft ?? value}
      placeholder={placeholder}
      disabled={disabled}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        if (draft !== null && draft !== value) onSave(draft);
        setDraft(null);
      }}
    />
  );
}

/** A textarea that saves on blur when its value changed. */
function BlurTextArea(props: {
  label: string;
  value: string;
  placeholder?: string;
  hint?: string;
  disabled?: boolean;
  onSave: (value: string) => void;
}) {
  const { label, value, placeholder, hint, disabled, onSave } = props;
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <TextAreaField
      size="lg"
      autoResize
      maxRows={12}
      label={label}
      hint={hint}
      value={draft ?? value}
      placeholder={placeholder}
      disabled={disabled}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        if (draft !== null && draft !== value) onSave(draft);
        setDraft(null);
      }}
    />
  );
}

/** One template: its summary, what it creates, and a way to use it. */
export const TemplateDetail = observer(function TemplateDetail(props: { workspaceSlug: string; templateId: string }) {
  const { workspaceSlug, templateId } = props;
  const { t } = useTranslation();
  const router = useAppRouter();
  const { workspaceInfoBySlug } = useUserPermissions();
  const { getProjectById } = useProject();
  const writableProjects = useWritableProjects();
  const {
    data: template,
    error,
    mutate,
  } = useSWR(getTemplateKey(templateId), () => service.retrieve(workspaceSlug, templateId));
  const [isDeleting, setIsDeleting] = useState(false);

  if (error)
    return <p className="px-6 py-6 text-body-sm-regular text-tertiary">{t("workspace_templates.not_found")}</p>;
  if (!template) return null;

  const workspaceRole = Number(workspaceInfoBySlug(workspaceSlug)?.role ?? 0);
  const project = template.project ? getProjectById(template.project) : undefined;
  const canEdit = template.project
    ? workspaceRole === 20 || Number(project?.member_role ?? 0) >= 15
    : workspaceRole >= 15;
  const body = template.template_data ?? {};

  const save = async (data: Partial<TTemplate>) => {
    try {
      await mutate(service.update(workspaceSlug, templateId, data), { revalidate: false });
      await globalMutate(getTemplatesKey(workspaceSlug));
    } catch (err) {
      setToast({ type: "error", title: errorMessage(err) ?? t("workspace_templates.save_error") });
      await mutate();
    }
  };
  // The web PATCH replaces template_data, so send the whole body with the change applied.
  const saveBody = (change: Partial<TBody>) => {
    const next: Record<string, unknown> = { ...body, ...change };
    for (const key of Object.keys(next)) {
      const value = next[key];
      if (value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) delete next[key];
    }
    return save({ template_data: next as TBody });
  };

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 py-6">
      <PageHead title={`${template.name} - ${t("workspace_templates.title")}`} />
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <TemplateKindIcon kind={template.kind} className="size-4 text-tertiary" />
          <span className="text-caption-md-medium text-secondary">
            {t(`workspace_templates.kinds.${template.kind}`)}
          </span>
          <Badge
            variant="neutral"
            size="sm"
            label={project ? `${project.name} (${project.identifier})` : t("workspace_templates.scope_workspace")}
          />
          {canEdit && (
            <div className="ml-auto">
              <Button
                variant="danger-outline"
                size="sm"
                stretch="auto"
                label={t("workspace_templates.delete")}
                onClick={() => setIsDeleting(true)}
              />
            </div>
          )}
        </div>
        <BlurInput
          label={t("workspace_templates.name")}
          value={template.name}
          disabled={!canEdit}
          onSave={(name) => {
            if (name.trim()) void save({ name: name.trim() });
          }}
        />
        <BlurTextArea
          label={t("workspace_templates.summary")}
          value={template.description}
          placeholder={t("workspace_templates.summary_placeholder")}
          disabled={!canEdit}
          onSave={(text) => void save({ description_html: text.trim() ? `<p>${escapeHtml(text.trim())}</p>` : "" })}
        />
      </section>

      <UseTemplate
        workspaceSlug={workspaceSlug}
        template={template}
        projects={template.project ? (project ? [project] : []) : writableProjects}
        onDone={(result) => {
          if (result.kind === "workitem") router.push(`/${workspaceSlug}/browse/${result.identifier}/`);
          else if (result.kind === "page")
            router.push(`/${workspaceSlug}/projects/${result.project_id}/pages/${result.id}`);
          else router.push(`/${workspaceSlug}/projects/${result.project_id}/issues`);
        }}
      />

      <section className="flex flex-col gap-4">
        <div>
          <h3 className="text-h5-medium text-primary">{t(`workspace_templates.body.${template.kind}`)}</h3>
          <p className="text-body-xs-regular text-tertiary">
            {t(`workspace_templates.body_description.${template.kind}`)}
          </p>
        </div>
        {template.kind === "workitem" && (
          <WorkItemBody
            workspaceSlug={workspaceSlug}
            templateId={template.id}
            body={body}
            disabled={!canEdit}
            onChange={saveBody}
          />
        )}
        {template.kind === "page" && (
          <div className="flex flex-col gap-3">
            <BlurInput
              label={t("workspace_templates.page_title")}
              value={body.name ?? ""}
              placeholder={template.name}
              disabled={!canEdit}
              onSave={(name) => void saveBody({ name: name.trim() })}
            />
            <ContentEditor
              workspaceSlug={workspaceSlug}
              entityId={`${template.id}-content`}
              value={body.description_html}
              label={t("workspace_templates.content")}
              disabled={!canEdit}
              onChange={(description_html) => saveBody({ description_html })}
            />
          </div>
        )}
        {template.kind === "project" && <ProjectBody body={body} disabled={!canEdit} onChange={saveBody} />}
      </section>

      <ConfirmDialog
        isOpen={isDeleting}
        handleClose={() => setIsDeleting(false)}
        handleSubmit={async () => {
          try {
            await service.remove(workspaceSlug, templateId);
            await globalMutate(getTemplatesKey(workspaceSlug));
            router.push(`/${workspaceSlug}/templates`);
          } catch {
            setToast({ type: "error", title: t("workspace_templates.save_error") });
          } finally {
            setIsDeleting(false);
          }
        }}
        isSubmitting={false}
        title={t("workspace_templates.delete")}
        content={t("workspace_templates.delete_description")}
      />
    </div>
  );
});

const escapeHtml = (text: string) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "<br />");

function ContentEditor(props: {
  workspaceSlug: string;
  entityId: string;
  value: string | undefined;
  label: string;
  disabled: boolean;
  onChange: (html: string) => Promise<void>;
}) {
  const { workspaceSlug, entityId, value, label, disabled, onChange } = props;
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-body-xs-medium text-secondary">{label}</span>
      <DescriptionInput
        key={entityId}
        entityId={entityId}
        fileAssetType={EFileAssetType.PROJECT_DESCRIPTION}
        initialValue={value || "<p></p>"}
        workspaceSlug={workspaceSlug}
        disabled={disabled}
        disabledExtensions={["image"]}
        setIsSubmitting={() => {}}
        containerClassName="min-h-24 rounded-lg border border-subtle px-4 py-3"
        onSubmit={async (next) => {
          if ((next.description_html ?? "") !== (value ?? "")) await onChange(next.description_html ?? "");
        }}
      />
    </div>
  );
}

function WorkItemBody(props: {
  workspaceSlug: string;
  templateId: string;
  body: TTemplateWorkItemBody;
  disabled: boolean;
  onChange: (change: Partial<TBody>) => Promise<void>;
}) {
  const { workspaceSlug, templateId, body, disabled, onChange } = props;
  const { t } = useTranslation();
  const priorities: TOption[] = PRIORITIES.map((p) => ({ id: p, name: t(`workspace_templates.priority.${p}`) }));
  const priority = priorities.find((p) => p.id === (body.priority ?? "none")) ?? priorities[0];
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 md:grid-cols-2">
        <BlurInput
          label={t("workspace_templates.work_item_title")}
          value={body.name ?? ""}
          hint={t("workspace_templates.work_item_title_hint")}
          disabled={disabled}
          onSave={(name) => void onChange({ name })}
        />
        <div className="flex flex-col gap-1.5">
          <span className="text-body-xs-medium text-secondary">{t("workspace_templates.priority_label")}</span>
          <Select<TOption>
            getValues={() => priorities}
            value={priority}
            onChange={(next) => void onChange({ priority: (next || "none") as TTemplateWorkItemBody["priority"] })}
            getOptionValue={(option) => option.id}
            getOptionLabel={(option) => option.name}
            pinSelected={false}
            disabled={disabled}
          >
            <Select.Trigger variant="select-md" aria-label={t("workspace_templates.priority_label")}>
              <Select.Value />
            </Select.Trigger>
          </Select>
        </div>
        <BlurInput
          label={t("workspace_templates.state")}
          value={body.state ?? ""}
          placeholder={t("workspace_templates.state_placeholder")}
          hint={t("workspace_templates.state_hint")}
          disabled={disabled}
          onSave={(state) => void onChange({ state: state.trim() })}
        />
        <BlurInput
          label={t("workspace_templates.labels")}
          value={(body.labels ?? []).join(", ")}
          placeholder={t("workspace_templates.labels_placeholder")}
          hint={t("workspace_templates.labels_hint")}
          disabled={disabled}
          onSave={(labels) => void onChange({ labels: splitList(labels) })}
        />
      </div>
      <ContentEditor
        workspaceSlug={workspaceSlug}
        entityId={`${templateId}-description`}
        value={body.description_html}
        label={t("workspace_templates.description")}
        disabled={disabled}
        onChange={(description_html) => onChange({ description_html })}
      />
      <BlurTextArea
        label={t("workspace_templates.sub_work_items")}
        value={namesOf(body.sub_work_items).join("\n")}
        placeholder={t("workspace_templates.one_per_line")}
        hint={t("workspace_templates.sub_work_items_hint")}
        disabled={disabled}
        onSave={(text) => void onChange({ sub_work_items: mergeByName(splitLines(text), body.sub_work_items) })}
      />
    </div>
  );
}

function ProjectBody(props: {
  body: TTemplateProjectBody;
  disabled: boolean;
  onChange: (change: Partial<TBody>) => Promise<void>;
}) {
  const { body, disabled, onChange } = props;
  const { t } = useTranslation();
  const states = body.states ?? [];
  const groups: TOption[] = STATE_GROUPS.map((g) => ({ id: g, name: t(`workspace_templates.state_groups.${g}`) }));
  const setStates = (next: TStateRow[]) => void onChange({ states: next });
  return (
    <div className="flex flex-col gap-5">
      <BlurTextArea
        label={t("workspace_templates.project_description")}
        value={body.description ?? ""}
        disabled={disabled}
        onSave={(description) => void onChange({ description })}
      />
      <div className="flex flex-col gap-2">
        <span className="text-body-xs-medium text-secondary">{t("workspace_templates.features")}</span>
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          <label className="flex items-center gap-2 text-body-xs-regular text-primary">
            <Switch
              size="sm"
              checked={(body.network ?? 2) === 2}
              onCheckedChange={(checked) => void onChange({ network: checked ? 2 : 0 })}
              disabled={disabled}
            />
            {t("workspace_templates.public")}
          </label>
          {FEATURES.map((feature) => (
            <label key={feature} className="flex items-center gap-2 text-body-xs-regular text-primary">
              <Switch
                size="sm"
                checked={body.features?.[feature] ?? feature !== "time_tracking"}
                onCheckedChange={(checked) => void onChange({ features: { ...body.features, [feature]: checked } })}
                disabled={disabled}
              />
              {t(`workspace_templates.feature.${feature}`)}
            </label>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-body-xs-medium text-secondary">{t("workspace_templates.states")}</span>
        <p className="text-caption-md-regular text-tertiary">{t("workspace_templates.states_hint")}</p>
        {states.map((state, index) => (
          <div key={state.name} className="flex items-center gap-2">
            <div className="flex-1">
              <BlurInput
                ariaLabel={t("workspace_templates.state_name")}
                value={state.name}
                disabled={disabled}
                onSave={(name) => {
                  const clash = states.some(
                    (row, i) => i !== index && row.name.toLowerCase() === name.trim().toLowerCase()
                  );
                  if (!name.trim() || clash) return;
                  setStates(states.map((row, i) => (i === index ? { ...row, name: name.trim() } : row)));
                }}
              />
            </div>
            <div className="w-40">
              <Select<TOption>
                getValues={() => groups}
                value={groups.find((g) => g.id === state.group) ?? null}
                onChange={(next) => {
                  if (next)
                    setStates(
                      states.map((row, i) => (i === index ? { ...row, group: next as TStateRow["group"] } : row))
                    );
                }}
                getOptionValue={(option) => option.id}
                getOptionLabel={(option) => option.name}
                pinSelected={false}
                disabled={disabled}
              >
                <Select.Trigger variant="select-md" aria-label={t("workspace_templates.state_group")}>
                  <Select.Value />
                </Select.Trigger>
              </Select>
            </div>
            {!disabled && (
              <Button
                variant="ghost"
                size="sm"
                stretch="auto"
                label={t("workspace_templates.remove")}
                onClick={() => setStates(states.filter((_, i) => i !== index))}
              />
            )}
          </div>
        ))}
        {!disabled && (
          <div>
            <Button
              variant="secondary"
              size="sm"
              stretch="auto"
              label={t("workspace_templates.add_state")}
              onClick={() =>
                setStates([
                  ...states,
                  {
                    name: `${t("workspace_templates.new_state")} ${states.length + 1}`,
                    group: states.length === 0 ? "backlog" : "started",
                  },
                ])
              }
            />
          </div>
        )}
      </div>

      <BlurInput
        label={t("workspace_templates.labels")}
        value={namesOf(body.labels).join(", ")}
        placeholder={t("workspace_templates.labels_placeholder")}
        disabled={disabled}
        onSave={(text) =>
          void onChange({
            labels: mergeByName(splitList(text), body.labels) as TTemplateProjectBody["labels"],
          } as Partial<TBody>)
        }
      />
      <BlurTextArea
        label={t("workspace_templates.starter_work_items")}
        value={namesOf(body.work_items).join("\n")}
        placeholder={t("workspace_templates.one_per_line")}
        disabled={disabled}
        onSave={(text) => void onChange({ work_items: mergeByName(splitLines(text), body.work_items) })}
      />
      <BlurTextArea
        label={t("workspace_templates.starter_pages")}
        value={namesOf(body.pages).join("\n")}
        placeholder={t("workspace_templates.one_per_line")}
        disabled={disabled}
        onSave={(text) => void onChange({ pages: mergeByName(splitLines(text), body.pages) })}
      />
    </div>
  );
}

function UseTemplate(props: {
  workspaceSlug: string;
  template: TTemplate;
  projects: TProject[];
  onDone: (result: TTemplateUseResult) => void;
}) {
  const { workspaceSlug, template, projects, onDone } = props;
  const { t } = useTranslation();
  const { fetchProjects } = useProject();
  const { workspaceInfoBySlug } = useUserPermissions();
  const [projectId, setProjectId] = useState<string | null>(template.project);
  const [name, setName] = useState("");
  const [identifier, setIdentifier] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isProject = template.kind === "project";
  const canCreateProjects = Number(workspaceInfoBySlug(workspaceSlug)?.role ?? 0) >= 15;
  const options: TOption[] = projects.map((p) => ({ id: p.id, name: `${p.name} (${p.identifier})` }));
  const selected = options.find((o) => o.id === (projectId ?? template.project)) ?? null;
  const code = identifier ?? suggestIdentifier(name);
  const ready = isProject ? name.trim() && code.trim() : !!selected;

  if (isProject ? !canCreateProjects : options.length === 0) return null;

  const submit = async () => {
    setBusy(true);
    try {
      const result = await service.use(workspaceSlug, template.id, {
        project_id: isProject ? undefined : selected?.id,
        name: name.trim() || undefined,
        identifier: isProject ? code.trim() : undefined,
      });
      if (isProject) await fetchProjects(workspaceSlug);
      setToast({ type: "success", title: t(`workspace_templates.created.${template.kind}`) });
      onDone(result);
    } catch (error) {
      setToast({ type: "error", title: errorMessage(error) ?? t("workspace_templates.use_error") });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-subtle p-4">
      <h3 className="text-h5-medium text-primary">{t("workspace_templates.use")}</h3>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (ready) void submit();
        }}
      >
        {!isProject && (
          <div className="w-64">
            <Select<TOption>
              getValues={() => options}
              value={selected}
              onChange={(next) => setProjectId(next || null)}
              getOptionValue={(option) => option.id}
              getOptionLabel={(option) => option.name}
              pinSelected={false}
              disabled={!!template.project}
              placeholder={t("workspace_templates.pick_project")}
            >
              <Select.Trigger variant="select-md" aria-label={t("workspace_templates.pick_project")}>
                <Select.Value />
              </Select.Trigger>
            </Select>
          </div>
        )}
        <div className="min-w-56 flex-1">
          <InputField
            size="md"
            orientation="vertical"
            value={name}
            maxLength={255}
            onChange={(e) => setName(e.target.value)}
            aria-label={t(`workspace_templates.use_name.${template.kind}`)}
            placeholder={
              isProject ? t("workspace_templates.use_name.project") : template.template_data?.name || template.name
            }
          />
        </div>
        {isProject && (
          <div className="w-28">
            <InputField
              size="md"
              orientation="vertical"
              value={code}
              maxLength={12}
              onChange={(e) => setIdentifier(e.target.value.toUpperCase())}
              aria-label={t("workspace_templates.identifier")}
              placeholder={t("workspace_templates.identifier")}
            />
          </div>
        )}
        <Button
          type="submit"
          variant="primary"
          size="md"
          stretch="auto"
          loading={busy}
          disabled={!ready}
          label={t(`workspace_templates.create.${template.kind}`)}
        />
      </form>
    </section>
  );
}
