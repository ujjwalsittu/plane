/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { observer } from "mobx-react";
import { Controller, useForm } from "react-hook-form";
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
import { DateSelect } from "@plane/blocks/property-select";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TMilestone, TMilestoneFormData } from "@plane/types";
import { getDate, renderFormattedPayloadDate } from "@plane/utils";
import { useMilestone } from "@/hooks/store/use-milestone";
import { useUserProfile } from "@/hooks/store/user";

type Props = {
  isOpen: boolean;
  onClose: () => void;
  workspaceSlug: string;
  projectId: string;
  /** Edit this milestone; omit to create one. */
  milestone?: TMilestone;
  onSaved?: (milestone: TMilestone) => void;
};

const toFormValues = (milestone?: TMilestone): TMilestoneFormData => ({
  title: milestone?.title ?? "",
  description: milestone?.description ?? "",
  target_date: milestone?.target_date ?? null,
});

export const MilestoneModal = observer(function MilestoneModal(props: Props) {
  const { isOpen, onClose, workspaceSlug, projectId, milestone, onSaved } = props;
  const { t } = useTranslation();
  const { createMilestone, updateMilestone } = useMilestone();
  const { data: userProfile } = useUserProfile();
  const {
    control,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<TMilestoneFormData>({ defaultValues: toFormValues(milestone) });

  useEffect(() => {
    if (isOpen) reset(toFormValues(milestone));
  }, [isOpen, milestone, reset]);

  const onSubmit = async (data: TMilestoneFormData) => {
    const payload = { ...data, title: data.title.trim() };
    try {
      const saved = milestone
        ? await updateMilestone(workspaceSlug, projectId, milestone.id, payload)
        : await createMilestone(workspaceSlug, projectId, payload);
      setToast({
        type: "success",
        title: milestone ? t("milestones_feature.toast.updated") : t("milestones_feature.toast.created"),
      });
      onSaved?.(saved);
      onClose();
    } catch {
      setToast({ type: "error", title: t("milestones_feature.toast.error") });
    }
  };

  return (
    <Dialog
      open={isOpen}
      disablePointerDismissal
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent size="md">
        <form className="flex min-h-0 flex-1 flex-col" onSubmit={handleSubmit(onSubmit)}>
          <DialogMain>
            <DialogHeader>
              <DialogHeading>
                <DialogTitle>
                  {milestone ? t("milestones_feature.edit_title") : t("milestones_feature.create_title")}
                </DialogTitle>
              </DialogHeading>
            </DialogHeader>
            <DialogBody tabIndex={0}>
              <div className="space-y-3">
                <Controller
                  name="title"
                  control={control}
                  rules={{
                    validate: (value) => !!value.trim() || t("title_is_required"),
                    maxLength: { value: 255, message: t("title_should_be_less_than_255_characters") },
                  }}
                  render={({ field: { value, onChange } }) => (
                    <InputField
                      size="xl"
                      orientation="vertical"
                      error={errors?.title?.message}
                      name="title"
                      type="text"
                      placeholder={t("milestones_feature.fields.title_placeholder")}
                      aria-label={t("milestones_feature.fields.title")}
                      value={value}
                      onChange={onChange}
                    />
                  )}
                />
                <Controller
                  name="description"
                  control={control}
                  render={({ field: { value, onChange } }) => (
                    <TextAreaField
                      size="xl"
                      autoResize
                      maxRows={8}
                      name="description"
                      placeholder={t("milestones_feature.fields.description_placeholder")}
                      aria-label={t("milestones_feature.fields.description")}
                      value={value}
                      onChange={onChange}
                    />
                  )}
                />
                <Controller
                  name="target_date"
                  control={control}
                  render={({ field: { value, onChange } }) => (
                    <DateSelect
                      variant="pill-sm"
                      className="max-w-none"
                      value={getDate(value) ?? null}
                      onChange={(date) => onChange(date ? renderFormattedPayloadDate(date) : null)}
                      placeholder={t("milestones_feature.fields.target_date")}
                      weekStartsOn={userProfile?.start_of_the_week}
                      clearable
                    />
                  )}
                />
              </div>
            </DialogBody>
          </DialogMain>
          <DialogActions>
            <Button variant="secondary" size="md" stretch="auto" onClick={onClose} label={t("common.cancel")} />
            <Button
              variant="primary"
              size="md"
              stretch="auto"
              type="submit"
              loading={isSubmitting}
              label={milestone ? t("common.update") : t("milestones_feature.add")}
            />
          </DialogActions>
        </form>
      </DialogContent>
    </Dialog>
  );
});
