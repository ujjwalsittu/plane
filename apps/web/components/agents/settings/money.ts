/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/** Integer cents to a dollar amount: 500 -> "$5.00". */
export const formatCents = (cents: number): string =>
  `$${(cents / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** Integer cents to what goes in a dollar input: 500 -> "5.00". */
export const centsToDollarInput = (cents: number): string => (cents / 100).toFixed(2);

/** A dollar input ("5", "5.5", "$5.00") to integer cents, or null when it is not a dollar amount. */
export const dollarInputToCents = (value: string): number | null => {
  const trimmed = value.trim().replace(/^\$/, "");
  if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) return null;
  return Math.round(Number(trimmed) * 100);
};
