/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { describe, expect, it } from "vitest";
import {
  editorHTMLToEditableMarkdown,
  getMarkdownLossyFeatures,
  prepareHTMLForSetContent,
  restoreMarkdownTokens,
} from "@/helpers/markdown-mode";

const IMAGE = '<image-component src="5f0c" width="400px" alignment="center"></image-component>';
const MENTION = '<mention-component id="m1" entity_identifier="user-1" entity_name="user_mention"></mention-component>';

describe("editorHTMLToEditableMarkdown", () => {
  it("converts headings, lists and code with language", () => {
    const { markdown } = editorHTMLToEditableMarkdown(
      '<h2>Plan</h2><ul><li><p>one</p></li></ul><pre><code class="language-mermaid">graph TD; A--&gt;B</code></pre>'
    );
    expect(markdown).toContain("## Plan");
    expect(markdown).toMatch(/[-*] one/);
    expect(markdown).toContain("```mermaid\ngraph TD; A-->B\n```");
  });

  it("replaces images and mentions with placeholders", () => {
    const { markdown, tokens } = editorHTMLToEditableMarkdown(`<p>Hi ${MENTION}</p>${IMAGE}`, {
      getMentionLabel: (id) => (id === "user-1" ? "debasis" : undefined),
    });
    expect(markdown).toContain("[@debasis](plane-mention:1)");
    expect(markdown).toContain("![image](plane-asset:0)");
    expect(tokens["plane-asset:0"]).toContain('src="5f0c"');
    expect(tokens["plane-mention:1"]).toContain('entity_identifier="user-1"');
  });
});

describe("restoreMarkdownTokens", () => {
  const tokens = { "plane-asset:0": IMAGE, "plane-mention:1": MENTION };

  it("restores a block image in place of its paragraph", () => {
    const html = restoreMarkdownTokens('<p>before</p><p><img src="plane-asset:0" alt="image"></p>', tokens);
    expect(html).toContain('<p>before</p><image-component src="5f0c" width="400px" alignment="center">');
    expect(html).not.toContain("<img");
  });

  it("restores inline mentions and leaves other links alone", () => {
    const html = restoreMarkdownTokens(
      '<p>Hi <a href="plane-mention:1">@debasis</a> see <a href="https://x.test">x</a></p>',
      tokens
    );
    expect(html).toContain('<mention-component id="m1" entity_identifier="user-1"');
    expect(html).toContain('<a href="https://x.test">x</a>');
  });

  it("drops nothing when a placeholder was deleted", () => {
    expect(restoreMarkdownTokens("<p>only text</p>", tokens)).toBe("<p>only text</p>");
  });
});

describe("getMarkdownLossyFeatures", () => {
  it("lists formatting Markdown can't express", () => {
    expect(
      getMarkdownLossyFeatures(
        '<div data-block-type="callout-component"><p>x</p></div><p><span data-text-color="red">c</span><u>u</u></p>'
      )
    ).toEqual(["callout", "color", "underline"]);
    expect(getMarkdownLossyFeatures("<p>plain</p>")).toEqual([]);
  });
});

describe("prepareHTMLForSetContent", () => {
  it("keeps code block blank lines out of the Markdown parser", () => {
    const html = '<pre><code class="language-js">a\n\nb</code></pre>';
    const prepared = prepareHTMLForSetContent(html);
    expect(prepared).toBe('<div><pre><code class="language-js">a&#10;&#10;b</code></pre></div>');
    const doc = new DOMParser().parseFromString(prepared, "text/html");
    expect(doc.querySelector("code")?.textContent).toBe("a\n\nb");
  });
});
