/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useSyncExternalStore } from "react";
import type { TAgentRun } from "@plane/types";
import { AgentsService } from "@/services/agents.service";

const service = new AgentsService();

const MAX_IDS = 200;
const BATCH_DELAY_MS = 60;
const POLL_MS = 15000;

type TKey = string;
const keyOf = (workspaceSlug: string, issueId: string): TKey => `${workspaceSlug}/${issueId}`;

/**
 * Live runs for the work items a list or board shows. Rows register their work item id; ids that
 * register in the same tick go out together in one `agent-runs/live/` request (up to 200 per
 * request), and the visible ids are refreshed together on one timer, never one request per row.
 */
const live = new Map<TKey, TAgentRun | null>();
const listeners = new Map<TKey, Set<() => void>>();
const pending = new Set<TKey>();
let batchTimer: ReturnType<typeof setTimeout> | undefined;
let pollTimer: ReturnType<typeof setInterval> | undefined;

const split = (key: TKey) => {
  const at = key.indexOf("/");
  return [key.slice(0, at), key.slice(at + 1)] as const;
};

const notify = (key: TKey) => listeners.get(key)?.forEach((listener) => listener());

const fetchChunk = async (slug: string, chunk: string[]) => {
  try {
    const runs = await service.getLiveRuns(slug, chunk);
    for (const id of chunk) {
      const key = keyOf(slug, id);
      const next = runs?.[id] ?? null;
      const previous = live.get(key);
      if (previous === undefined || previous?.id !== next?.id) {
        live.set(key, next);
        notify(key);
      }
    }
  } catch {
    // A failed badge lookup is not worth a message; the next poll tries again.
  }
};

const fetchKeys = async (keys: TKey[]) => {
  const bySlug = new Map<string, string[]>();
  for (const key of keys) {
    const [slug, issueId] = split(key);
    bySlug.set(slug, [...(bySlug.get(slug) ?? []), issueId]);
  }
  const requests: Promise<void>[] = [];
  for (const [slug, ids] of bySlug) {
    for (let i = 0; i < ids.length; i += MAX_IDS) {
      const chunk = ids.slice(i, i + MAX_IDS);
      requests.push(fetchChunk(slug, chunk));
    }
  }
  await Promise.all(requests);
};

const flush = () => {
  batchTimer = undefined;
  const keys = [...pending].filter((key) => listeners.has(key));
  pending.clear();
  if (keys.length > 0) void fetchKeys(keys);
};

const ensurePolling = () => {
  if (pollTimer || listeners.size === 0) return;
  pollTimer = setInterval(() => {
    if (typeof document !== "undefined" && document.hidden) return;
    if (listeners.size > 0) void fetchKeys([...listeners.keys()]);
  }, POLL_MS);
};

/** Registers a work item id; exported for tests, rows use `useLiveAgentRun`. */
export const subscribe = (key: TKey, listener: () => void) => {
  const set = listeners.get(key) ?? new Set();
  set.add(listener);
  listeners.set(key, set);
  if (!live.has(key)) {
    pending.add(key);
    batchTimer ??= setTimeout(flush, BATCH_DELAY_MS);
  }
  ensurePolling();
  return () => {
    set.delete(listener);
    if (set.size === 0) listeners.delete(key);
    if (listeners.size === 0 && pollTimer) {
      clearInterval(pollTimer);
      pollTimer = undefined;
    }
  };
};

/** The live run on a work item, or null. Cheap to call from every row of a list or board. */
export const useLiveAgentRun = (workspaceSlug: string | undefined, issueId: string): TAgentRun | null => {
  const key = keyOf(workspaceSlug ?? "", issueId);
  const subscribeToKey = useCallback((listener: () => void) => subscribe(key, listener), [key]);
  const getSnapshot = useCallback(() => live.get(key) ?? null, [key]);
  return useSyncExternalStore(
    workspaceSlug ? subscribeToKey : noopSubscribe,
    workspaceSlug ? getSnapshot : getNull,
    getNull
  );
};

const noopSubscribe = () => () => {};
const getNull = () => null;
