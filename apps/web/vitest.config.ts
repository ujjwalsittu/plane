/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["**/__tests__/**/*.test.ts"],
    exclude: ["**/node_modules/**", "build/**", ".react-router/**"],
    environment: "happy-dom",
  },
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, ".") },
  },
});
