/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Editor } from "@tiptap/core";
import { StarterKit } from "@tiptap/starter-kit";
import { afterEach, describe, expect, it } from "vitest";
import { PlaneMarkdown } from "@/extensions/markdown";

const CODE_HTML =
  '<p>intro</p><pre><code class="language-js">const a = 1;\n\nconst b = 2;</code></pre><p>after *not italic*</p>';

let editor: Editor | undefined;
const createEditor = (content: string) => {
  editor = new Editor({
    extensions: [StarterKit, PlaneMarkdown.configure({ html: true, breaks: true, transformPastedText: true })],
    content,
    parseOptions: { preserveWhitespace: true },
  });
  return editor;
};

const codeText = (instance: Editor) => {
  let text: string | undefined;
  instance.state.doc.descendants((node) => {
    if (node.type.name === "codeBlock") text = node.textContent;
  });
  return text;
};

afterEach(() => editor?.destroy());

describe("PlaneMarkdown", () => {
  it("keeps blank lines inside code blocks in the initial HTML", () => {
    const instance = createEditor(CODE_HTML);
    expect(codeText(instance)).toBe("const a = 1;\n\nconst b = 2;");
    expect(instance.getHTML()).toContain("<p>after *not italic*</p>");
  });

  it("keeps blank lines inside code blocks when HTML is set later", () => {
    const instance = createEditor("<p></p>");
    instance.commands.setContent(CODE_HTML, { parseOptions: { preserveWhitespace: true } });
    expect(codeText(instance)).toBe("const a = 1;\n\nconst b = 2;");
  });

  it("still parses Markdown strings", () => {
    const instance = createEditor("<p></p>");
    instance.commands.setContent("# Title\n\nSome **bold** text");
    expect(instance.getHTML()).toBe("<h1>Title</h1><p>Some <strong>bold</strong> text</p>");
  });
});
