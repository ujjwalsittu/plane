/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import useSWR from "swr";
import { Badge } from "@makeplane/propel/components/badge";
import { Button } from "@makeplane/propel/components/button";
import { CheckboxField } from "@makeplane/propel/components/checkbox-field";
import { InputField } from "@makeplane/propel/components/input-field";
import { LockOutline, PagesOutline } from "@makeplane/propel/icons";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import { cn, renderFormattedDate } from "@plane/utils";
import { useAppRouter } from "@/hooks/use-app-router";
import { WikiService } from "@/services/wiki.service";

const service = new WikiService();

export const getWikiKeys = (workspaceSlug: string) => ({
  pages: `WIKI_PAGES_${workspaceSlug}`,
  archived: `WIKI_ARCHIVED_${workspaceSlug}`,
  collections: `WIKI_COLLECTIONS_${workspaceSlug}`,
});

type TFilter = "all" | "unfiled" | "archived" | string;

/** The workspace wiki: collections on the left, the filtered pages on the right. */
export const WikiRoot = observer(function WikiRoot({ workspaceSlug }: { workspaceSlug: string }) {
  const { t } = useTranslation();
  const router = useAppRouter();
  const keys = getWikiKeys(workspaceSlug);
  const { data: pages } = useSWR(keys.pages, () => service.listPages(workspaceSlug));
  const { data: archived } = useSWR(keys.archived, () => service.listPages(workspaceSlug, true));
  const { data: collections, mutate: mutateCollections } = useSWR(keys.collections, () =>
    service.listCollections(workspaceSlug)
  );
  const [filter, setFilter] = useState<TFilter>("all");
  const [newCollection, setNewCollection] = useState("");
  const [isPrivate, setIsPrivate] = useState(false);
  const [creating, setCreating] = useState(false);

  const active = (pages ?? []).filter((page) => !page.parent_id);
  const shown =
    filter === "archived"
      ? (archived ?? [])
      : filter === "all"
        ? active
        : filter === "unfiled"
          ? active.filter((page) => !page.collection_id)
          : active.filter((page) => page.collection_id === filter);
  const selectedCollection = (collections ?? []).find((collection) => collection.id === filter);
  const title =
    filter === "all"
      ? t("wiki.all_pages")
      : filter === "unfiled"
        ? t("wiki.unfiled")
        : filter === "archived"
          ? t("wiki.archived")
          : (selectedCollection?.name ?? "");

  const createPage = async () => {
    setCreating(true);
    try {
      const page = await service.createPage(workspaceSlug, {
        name: t("wiki.untitled"),
        collection_id: selectedCollection?.id ?? null,
      });
      router.push(`/${workspaceSlug}/wiki/${page.id}`);
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error;
      setToast({ type: "error", title: message ?? t("wiki.save_error") });
    } finally {
      setCreating(false);
    }
  };

  const createCollection = async () => {
    const name = newCollection.trim();
    if (!name) return;
    try {
      const collection = await service.createCollection(workspaceSlug, { name, access: isPrivate ? 1 : 0 });
      setNewCollection("");
      setIsPrivate(false);
      await mutateCollections();
      setFilter(collection.id);
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error;
      setToast({ type: "error", title: message ?? t("wiki.save_error") });
    }
  };

  const countFor = (collectionId: string) => active.filter((page) => page.collection_id === collectionId).length;
  const filterButton = (key: TFilter, label: string, count?: number, isLocked = false) => (
    <button
      key={key}
      type="button"
      onClick={() => setFilter(key)}
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-body-xs-medium",
        filter === key
          ? "bg-layer-transparent-selected text-primary"
          : "text-secondary hover:bg-layer-transparent-hover"
      )}
    >
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {isLocked && <LockOutline className="size-3 shrink-0 text-tertiary" />}
      {count !== undefined && <span className="text-caption-md-regular text-tertiary">{count}</span>}
    </button>
  );

  return (
    <div className="mx-auto grid w-full max-w-6xl grid-cols-1 gap-6 px-page-x py-6 md:grid-cols-[15rem_minmax(0,1fr)]">
      <aside className="flex flex-col gap-4">
        <div className="flex flex-col gap-0.5">
          {filterButton("all", t("wiki.all_pages"), active.length)}
          {filterButton("unfiled", t("wiki.unfiled"), active.filter((page) => !page.collection_id).length)}
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="px-2 text-caption-md-semibold text-tertiary">{t("wiki.collections")}</span>
          {(collections ?? []).map((collection) =>
            filterButton(collection.id, collection.name, countFor(collection.id), collection.access === 1)
          )}
          <form
            className="mt-1 flex flex-col gap-2 px-1"
            onSubmit={(e) => {
              e.preventDefault();
              void createCollection();
            }}
          >
            <InputField
              size="md"
              orientation="vertical"
              value={newCollection}
              onChange={(e) => setNewCollection(e.target.value)}
              placeholder={t("wiki.new_collection")}
              aria-label={t("wiki.new_collection")}
            />
            {newCollection.trim() && (
              <CheckboxField
                size="md"
                label={t("wiki.private")}
                checked={isPrivate}
                onCheckedChange={(checked) => setIsPrivate(!!checked)}
              />
            )}
          </form>
        </div>
        <div className="flex flex-col gap-0.5">{filterButton("archived", t("wiki.archived"), archived?.length)}</div>
      </aside>

      <section className="flex min-w-0 flex-col gap-3">
        <div className="flex items-center gap-3">
          <h1 className="min-w-0 flex-1 truncate text-h4-semibold text-primary">{title}</h1>
          {filter !== "archived" && (
            <Button
              variant="primary"
              size="md"
              stretch="auto"
              loading={creating}
              label={t("wiki.new_page")}
              onClick={() => void createPage()}
            />
          )}
        </div>
        <div className="divide-y divide-subtle rounded-lg border border-subtle">
          {shown.length === 0 && <p className="px-4 py-6 text-body-sm-regular text-tertiary">{t("wiki.empty")}</p>}
          {shown.map((page) => {
            const collection = (collections ?? []).find((c) => c.id === page.collection_id);
            return (
              <Link
                key={page.id}
                href={`/${workspaceSlug}/wiki/${page.id}`}
                className="flex items-center gap-3 px-4 py-3 hover:bg-layer-1"
              >
                <PagesOutline className="size-4 shrink-0 text-tertiary" />
                <span className="min-w-0 flex-1 truncate text-body-sm-medium text-primary">
                  {page.name || t("wiki.untitled")}
                </span>
                {page.access === 1 && <LockOutline className="size-3.5 shrink-0 text-tertiary" />}
                {collection && filter === "all" && <Badge variant="neutral" size="sm" label={collection.name} />}
                <span className="shrink-0 text-caption-md-regular text-tertiary">
                  {renderFormattedDate(page.updated_at ?? "")}
                </span>
              </Link>
            );
          })}
        </div>
      </section>
    </div>
  );
});
