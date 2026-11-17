/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { convertHTMLToMarkdown } from "@plane/utils";

/**
 * Markdown mode: edit a document as Markdown and convert it back.
 *
 * Uploaded images and mentions have no Markdown form that converts back to the same node, so
 * they are swapped for placeholder links (`plane-asset:N`, `plane-mention:N`) on the way out
 * and restored from the original HTML on the way back.
 */

const ASSET_SCHEME = "plane-asset:";
const MENTION_SCHEME = "plane-mention:";

export type TEditableMarkdown = {
  markdown: string;
  /** Placeholder URL → original element HTML. */
  tokens: Record<string, string>;
};

export type TMarkdownLossyFeature = "callout" | "color" | "alignment" | "underline";

const parseFragment = (html: string) => new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");

export function editorHTMLToEditableMarkdown(
  html: string,
  options?: { getMentionLabel?: (userId: string) => string | undefined }
): TEditableMarkdown {
  const doc = parseFragment(html);
  const tokens: Record<string, string> = {};
  let index = 0;

  doc.body.querySelectorAll("image-component").forEach((element) => {
    const key = `${ASSET_SCHEME}${index++}`;
    tokens[key] = element.outerHTML;
    const img = doc.createElement("img");
    img.setAttribute("src", key);
    img.setAttribute("alt", "image");
    element.replaceWith(img);
  });

  doc.body.querySelectorAll("mention-component").forEach((element) => {
    const key = `${MENTION_SCHEME}${index++}`;
    tokens[key] = element.outerHTML;
    const userId = element.getAttribute("entity_identifier") ?? "";
    const link = doc.createElement("a");
    link.setAttribute("href", key);
    link.textContent = `@${options?.getMentionLabel?.(userId) ?? "mention"}`;
    element.replaceWith(link);
  });

  const markdown = convertHTMLToMarkdown({
    description_html: doc.body.innerHTML,
    metaData: { file_assets: [], user_mentions: [] },
  }).trim();
  return { markdown, tokens };
}

/** Puts the original images and mentions back in place of their placeholders. */
export function restoreMarkdownTokens(html: string, tokens: Record<string, string>): string {
  if (Object.keys(tokens).length === 0) return html;
  const doc = parseFragment(html);
  const toNode = (original: string) => {
    const template = doc.createElement("template");
    template.innerHTML = original;
    return template.content.firstChild;
  };

  doc.body.querySelectorAll("img").forEach((img) => {
    const original = tokens[img.getAttribute("src") ?? ""];
    const node = original ? toNode(original) : null;
    if (!node) return;
    // Images are blocks in the editor; drop the paragraph Markdown wraps them in.
    const parent = img.parentElement;
    if (parent?.tagName === "P" && parent.childNodes.length === 1) parent.replaceWith(node);
    else img.replaceWith(node);
  });

  doc.body.querySelectorAll("a").forEach((link) => {
    const original = tokens[link.getAttribute("href") ?? ""];
    const node = original ? toNode(original) : null;
    if (node) link.replaceWith(node);
  });

  return doc.body.innerHTML;
}

/** Formatting in the document that Markdown can't express and will be dropped on apply. */
export function getMarkdownLossyFeatures(html: string): TMarkdownLossyFeature[] {
  const doc = parseFragment(html);
  const features: TMarkdownLossyFeature[] = [];
  if (doc.body.querySelector('[data-block-type="callout-component"]')) features.push("callout");
  if (doc.body.querySelector("[data-text-color], [data-background-color]")) features.push("color");
  if (doc.body.querySelector('[style*="text-align"]')) features.push("alignment");
  if (doc.body.querySelector("u")) features.push("underline");
  return features;
}

/**
 * The editor's setContent runs strings through markdown-it, which ends a raw HTML block at the
 * first blank line (e.g. inside a code block) and parses the rest as Markdown. Encoding newlines
 * as `&#10;` (the same characters) and wrapping in a `<div>` (which ProseMirror skips) keeps the
 * whole document one raw HTML block.
 */
export function prepareHTMLForSetContent(html: string): string {
  return `<div>${html.replace(/\r?\n/g, "&#10;")}</div>`;
}
