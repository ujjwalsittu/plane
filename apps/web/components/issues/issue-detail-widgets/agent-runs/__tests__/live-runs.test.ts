/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getLiveRuns = vi.fn();
vi.mock("@/services/agents.service", () => ({
  AgentsService: class {
    getLiveRuns = getLiveRuns;
  },
}));

const load = async () => {
  vi.resetModules();
  return import("../live-runs");
};

const ids = (n: number) => Array.from({ length: n }, (_, i) => `issue-${i}`);

describe("live run batching", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    getLiveRuns.mockReset();
    getLiveRuns.mockResolvedValue({ runs: {}, poll: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("sends ids registered in the same tick in one request", async () => {
    const { subscribe } = await load();
    ids(5).forEach((id) => subscribe(`ws/${id}`, () => {}));
    await vi.advanceTimersByTimeAsync(100);
    expect(getLiveRuns).toHaveBeenCalledTimes(1);
    expect(getLiveRuns).toHaveBeenCalledWith("ws", ids(5));
  });

  it("chunks more than 200 ids at 200 per request", async () => {
    const { subscribe } = await load();
    ids(450).forEach((id) => subscribe(`ws/${id}`, () => {}));
    await vi.advanceTimersByTimeAsync(100);
    expect(getLiveRuns.mock.calls.map((call) => call[1].length)).toEqual([200, 200, 50]);
  });

  it("drops ids that unsubscribed before the batch fired", async () => {
    const { subscribe } = await load();
    const unsubscribe = subscribe("ws/gone", () => {});
    subscribe("ws/kept", () => {});
    unsubscribe();
    await vi.advanceTimersByTimeAsync(100);
    expect(getLiveRuns).toHaveBeenCalledTimes(1);
    expect(getLiveRuns).toHaveBeenCalledWith("ws", ["kept"]);
  });

  it("polls every 15s and stops once the last subscriber is gone", async () => {
    const { subscribe } = await load();
    const unsubscribe = subscribe("ws/a", () => {});
    await vi.advanceTimersByTimeAsync(100);
    expect(getLiveRuns).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(15000);
    expect(getLiveRuns).toHaveBeenCalledTimes(2);
    unsubscribe();
    await vi.advanceTimersByTimeAsync(60000);
    expect(getLiveRuns).toHaveBeenCalledTimes(2);
  });

  it("stops polling a workspace that has nothing live", async () => {
    getLiveRuns.mockResolvedValue({ runs: {}, poll: false });
    const { subscribe } = await load();
    subscribe("ws/a", () => {});
    await vi.advanceTimersByTimeAsync(100);
    expect(getLiveRuns).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(15000);
    await vi.advanceTimersByTimeAsync(15000);
    await vi.advanceTimersByTimeAsync(30000);
    expect(getLiveRuns).toHaveBeenCalledTimes(1);
  });

  it("rechecks an idle workspace after five minutes", async () => {
    getLiveRuns.mockResolvedValue({ runs: {}, poll: false });
    const { subscribe } = await load();
    subscribe("ws/a", () => {});
    await vi.advanceTimersByTimeAsync(100);
    expect(getLiveRuns).toHaveBeenCalledTimes(1);
    // five minutes, rounded up to the next 15s tick
    await vi.advanceTimersByTimeAsync(315_000);
    expect(getLiveRuns).toHaveBeenCalledTimes(2);
    // Still idle: no more requests until the next five minutes
    await vi.advanceTimersByTimeAsync(60_000);
    expect(getLiveRuns).toHaveBeenCalledTimes(2);

    getLiveRuns.mockResolvedValue({ runs: {}, poll: true });
    await vi.advanceTimersByTimeAsync(240_000);
    expect(getLiveRuns).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(15000);
    expect(getLiveRuns).toHaveBeenCalledTimes(4);
  });
});
