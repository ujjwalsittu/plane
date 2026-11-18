/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Content } from "@tiptap/core";
import { Markdown } from "tiptap-markdown";
// local imports
import { prepareHTMLForSetContent } from "@/helpers/markdown-mode";

/**
 * tiptap-markdown runs every string given to the editor (initial content and setContent) through
 * markdown-it, which ends a raw HTML block at the first blank line. In a code block that blank line
 * is content, so everything after it was lost on load. HTML strings are passed as a single raw
 * HTML block instead; Markdown strings are parsed as before.
 */
const isHTMLString = (content: unknown): content is string =>
  typeof content === "string" && content.trimStart().startsWith("<");

const protectHTML = <T>(content: T): T => (isHTMLString(content) ? prepareHTMLForSetContent(content) : content) as T;

export const PlaneMarkdown = Markdown.extend({
  onBeforeCreate(event) {
    this.editor.options.content = protectHTML(this.editor.options.content as Content);
    this.parent?.(event);
  },

  addCommands() {
    const commands = this.parent?.() ?? {};
    const { setContent } = commands;
    if (!setContent) return commands;
    return {
      ...commands,
      setContent: (content, options) => setContent(protectHTML(content), options),
    };
  },
});
