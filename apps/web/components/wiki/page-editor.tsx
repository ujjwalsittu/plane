/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR, { useSWRConfig } from "swr";
import { Button } from "@makeplane/propel/components/button";
import { Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from "@makeplane/propel/components/menu";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TNameDescriptionLoader, TWikiPage } from "@plane/types";
import { EFileAssetType } from "@plane/types";
import { DescriptionInput } from "@/components/editor/rich-text/description-input/root";
import { PageHead } from "@/components/core/page-title";
import { useAppRouter } from "@/hooks/use-app-router";
import { WikiService } from "@/services/wiki.service";
import { getWikiKeys } from "./root";

const service = new WikiService();

/** One workspace page: title, collection, rich text body (Markdown, Mermaid and images work). */
export const WikiPageEditor = observer(function WikiPageEditor(props: { workspaceSlug: string; pageId: string }) {
  const { workspaceSlug, pageId } = props;
  const { t } = useTranslation();
  const router = useAppRouter();
  const { mutate: mutateGlobal } = useSWRConfig();
  const keys = getWikiKeys(workspaceSlug);
  const { data: page, mutate, error } = useSWR(`WIKI_PAGE_${pageId}`, () => service.getPage(workspaceSlug, pageId));
  const { data: collections } = useSWR(keys.collections, () => service.listCollections(workspaceSlug));
  const [title, setTitle] = useState("");
  const [saving, setSaving] = useState<TNameDescriptionLoader>("saved");
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => setTitle(page?.name ?? ""), [page?.name]);

  const refreshLists = () => Promise.all([mutateGlobal(keys.pages), mutateGlobal(keys.archived)]);
  const run = async (action: () => Promise<unknown>) => {
    try {
      await action();
      await mutate();
      await refreshLists();
    } catch (err) {
      const message = (err as { error?: string } | undefined)?.error;
      setToast({ type: "error", title: message ?? t("wiki.save_error") });
    }
  };

  if (error) return <p className="px-page-x py-10 text-body-sm-regular text-tertiary">{t("wiki.not_found")}</p>;
  if (!page) return null;

  const isArchived = !!page.archived_at;
  const collection = (collections ?? []).find((c) => c.id === page.collection_id);
  const saveTitle = () => {
    const next = title.trim();
    if (next && next !== page.name) void run(() => service.updatePage(workspaceSlug, page.id, { name: next }));
    else setTitle(page.name);
  };
  const moveTo = (collectionId: string | null) =>
    void run(() => service.setCollection(workspaceSlug, page as TWikiPage, collectionId));

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-page-x py-6">
      <PageHead title={page.name} />
      <div className="flex flex-wrap items-center gap-2 text-caption-md-regular text-tertiary">
        <Link href={`/${workspaceSlug}/wiki/`} className="hover:text-primary">
          {t("wiki.title")}
        </Link>
        <span>/</span>
        <Menu>
          <MenuTrigger
            disabled={isArchived}
            render={
              <button type="button" className="rounded-sm px-1 hover:bg-layer-transparent-hover hover:text-primary">
                {collection?.name ?? t("wiki.unfiled")}
              </button>
            }
          />
          <MenuContent side="bottom" align="start">
            {(collections ?? []).map((c) => (
              <MenuItem key={c.id} label={c.name} onClick={() => moveTo(c.id)} />
            ))}
            {page.collection_id && (
              <>
                <MenuSeparator />
                <MenuItem label={t("wiki.remove_from_collection")} onClick={() => moveTo(null)} />
              </>
            )}
          </MenuContent>
        </Menu>
        <span className="ml-auto">{saving === "submitting" ? t("common.saving") : ""}</span>
        {isArchived ? (
          <>
            <Button
              variant="secondary"
              size="sm"
              stretch="auto"
              label={t("wiki.restore")}
              onClick={() => void run(() => service.restorePage(workspaceSlug, page.id))}
            />
            <Button
              variant="danger-outline"
              size="sm"
              stretch="auto"
              label={t("delete")}
              onClick={() => setConfirmDelete(true)}
            />
          </>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            stretch="auto"
            label={t("wiki.archive")}
            onClick={() => void run(() => service.archivePage(workspaceSlug, page.id))}
          />
        )}
      </div>

      <input
        className="w-full bg-transparent text-h3-semibold text-primary outline-none placeholder:text-placeholder"
        value={title}
        disabled={isArchived}
        placeholder={t("wiki.untitled")}
        aria-label={t("wiki.page_title")}
        onChange={(e) => setTitle(e.target.value)}
        onBlur={saveTitle}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
        }}
      />

      <DescriptionInput
        key={`wiki-page-${page.id}`}
        entityId={page.id}
        fileAssetType={EFileAssetType.PAGE_DESCRIPTION}
        initialValue={page.description_html}
        workspaceSlug={workspaceSlug}
        disabled={isArchived}
        setIsSubmitting={setSaving}
        placeholder={t("wiki.body_placeholder")}
        containerClassName="min-h-96 px-0"
        onSubmit={async (value) => {
          await service.updatePage(workspaceSlug, page.id, { description_html: value.description_html });
          setSaving("saved");
        }}
      />

      <ConfirmDialog
        isOpen={confirmDelete}
        handleClose={() => setConfirmDelete(false)}
        handleSubmit={async () => {
          try {
            await service.deletePage(workspaceSlug, page.id);
            await refreshLists();
            router.push(`/${workspaceSlug}/wiki/`);
          } catch {
            setToast({ type: "error", title: t("wiki.save_error") });
          } finally {
            setConfirmDelete(false);
          }
        }}
        isSubmitting={false}
        title={t("wiki.delete_title")}
        content={t("wiki.delete_description", { name: page.name })}
      />
    </div>
  );
});
