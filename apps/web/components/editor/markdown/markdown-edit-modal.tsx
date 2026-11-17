/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useMemo, useState } from "react";
import { observer } from "mobx-react";
import { Button } from "@makeplane/propel/components/button";
import {
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogHeading,
  DialogInfo,
  DialogMain,
  DialogTitle,
} from "@makeplane/propel/components/dialog";
import type { EditorRefApi, TEditableMarkdown, TMarkdownLossyFeature } from "@plane/editor";
import {
  editorHTMLToEditableMarkdown,
  getMarkdownLossyFeatures,
  prepareHTMLForSetContent,
  restoreMarkdownTokens,
} from "@plane/editor";
import { useTranslation } from "@plane/i18n";
import { RichTextEditor } from "@/components/editor/rich-text";
import { useMember } from "@/hooks/store/use-member";
import { useWorkspace } from "@/hooks/store/use-workspace";

type Props = {
  isOpen: boolean;
  onClose: () => void;
  editorRef: React.RefObject<EditorRefApi | null>;
  workspaceSlug: string;
  projectId?: string;
  /** Collaborative documents: warn that applying replaces other people's in-flight edits. */
  isCollaborative?: boolean;
};

const EMPTY_DOCUMENT = "<p></p>";

export const MarkdownEditModal = observer(function MarkdownEditModal(props: Props) {
  const { isOpen, onClose, editorRef, workspaceSlug, projectId, isCollaborative = false } = props;
  const { t } = useTranslation();
  const { getUserDetails } = useMember();
  const { getWorkspaceBySlug } = useWorkspace();
  const workspaceId = getWorkspaceBySlug(workspaceSlug)?.id;
  // state
  const [source, setSource] = useState<TEditableMarkdown>({ markdown: "", tokens: {} });
  const [markdown, setMarkdown] = useState("");
  const [lossy, setLossy] = useState<TMarkdownLossyFeature[]>([]);
  const [previewHTML, setPreviewHTML] = useState(EMPTY_DOCUMENT);

  // Snapshot the document as Markdown each time the dialog opens.
  useEffect(() => {
    if (!isOpen || !editorRef.current) return;
    const html = editorRef.current.getDocument().html;
    const editable = editorHTMLToEditableMarkdown(html, {
      getMentionLabel: (userId) => getUserDetails(userId)?.display_name,
    });
    setSource(editable);
    setMarkdown(editable.markdown);
    setLossy(getMarkdownLossyFeatures(html));
  }, [isOpen, editorRef, getUserDetails]);

  const toEditorHTML = useMemo(
    () => (value: string) => {
      const html = editorRef.current?.convertMarkdownToHTML(value) ?? "";
      return restoreMarkdownTokens(html, source.tokens) || EMPTY_DOCUMENT;
    },
    [editorRef, source.tokens]
  );

  // Live preview, debounced while typing.
  useEffect(() => {
    if (!isOpen) return;
    const timer = setTimeout(() => setPreviewHTML(prepareHTMLForSetContent(toEditorHTML(markdown))), 250);
    return () => clearTimeout(timer);
  }, [isOpen, markdown, toEditorHTML]);

  const isDirty = markdown !== source.markdown;

  const handleApply = () => {
    // Untouched Markdown changes nothing, so formatting Markdown can't express is kept.
    if (isDirty) editorRef.current?.setEditorValue(prepareHTMLForSetContent(toEditorHTML(markdown)), true);
    onClose();
  };

  const lossyLabels = lossy.map((feature) => t(`markdown_mode.feature_${feature}`)).join(", ");

  return (
    <Dialog
      open={isOpen}
      disablePointerDismissal
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent size="full" density="compact">
        <DialogMain>
          <DialogHeader>
            <DialogHeading>
              <DialogTitle>{t("markdown_mode.edit_as_markdown")}</DialogTitle>
              <DialogDescription>{t("markdown_mode.description")}</DialogDescription>
            </DialogHeading>
          </DialogHeader>
          <DialogBody tabIndex={-1}>
            <div className="grid h-full min-h-0 grid-cols-1 gap-4 md:grid-cols-2">
              <label className="flex min-h-0 flex-col gap-2">
                <span className="text-caption-md-medium text-secondary">{t("markdown_mode.markdown")}</span>
                <textarea
                  value={markdown}
                  onChange={(event) => setMarkdown(event.target.value)}
                  spellCheck={false}
                  className="font-mono min-h-80 flex-1 resize-none rounded-md border border-subtle bg-layer-1 p-3 text-body-sm-regular text-primary outline-none focus:border-accent-strong"
                />
              </label>
              <div className="flex min-h-0 flex-col gap-2">
                <span className="text-caption-md-medium text-secondary">{t("markdown_mode.preview")}</span>
                <div className="min-h-80 flex-1 overflow-y-auto rounded-md border border-subtle px-4 py-2">
                  {workspaceId && (
                    <RichTextEditor
                      editable={false}
                      id="markdown-mode-preview"
                      initialValue={previewHTML}
                      value={previewHTML}
                      workspaceSlug={workspaceSlug}
                      workspaceId={workspaceId}
                      projectId={projectId}
                      containerClassName="border-none p-0"
                    />
                  )}
                </div>
              </div>
            </div>
          </DialogBody>
        </DialogMain>
        <DialogActions>
          {(lossy.length > 0 || isCollaborative) && (
            <DialogInfo>
              <span className="text-warning-primary">
                {[
                  lossy.length > 0 ? t("markdown_mode.lossy_warning", { features: lossyLabels }) : null,
                  isCollaborative ? t("markdown_mode.collab_warning") : null,
                ]
                  .filter(Boolean)
                  .join(" ")}
              </span>
            </DialogInfo>
          )}
          <Button variant="secondary" size="md" stretch="auto" onClick={onClose} label={t("markdown_mode.cancel")} />
          <Button variant="primary" size="md" stretch="auto" onClick={handleApply} label={t("markdown_mode.apply")} />
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
});
