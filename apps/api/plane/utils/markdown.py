# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Markdown <-> the HTML Plane's editor stores.

Markdown in: CommonMark + GFM tables, strikethrough and task lists. Images
become the editor's ``<image-component>`` node (``![alt](asset:<uuid>)`` for
uploaded assets, or a plain URL), task lists use the editor's
``data-type="taskList"`` markup, and fenced code keeps its language as
``class="language-x"`` (so ```mermaid stays a Mermaid block). The result is
still sanitised by the caller, like any other HTML.

Markdown out: the reverse, for clients that prefer Markdown on read.
"""

# Python imports
import re

# Third party imports
from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
from markdownify import MarkdownConverter
from mdit_py_plugins.tasklists import tasklists_plugin

ASSET_SCHEME = "asset:"
_TAG = re.compile(r"<[a-zA-Z][\w-]*(\s[^>]*)?/?>|</[a-zA-Z][\w-]*>")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def looks_like_markdown(text):
    """True for non-empty text with no HTML tags -- treated as Markdown when a
    client sends it in an HTML field."""
    return isinstance(text, str) and bool(text.strip()) and not _TAG.search(text)


def _renderer():
    md = MarkdownIt("commonmark", {"html": True, "linkify": False, "breaks": True})
    md.enable(["table", "strikethrough"])
    md.use(tasklists_plugin, enabled=True)
    return md


_MD = _renderer()


def _image_component(soup, src, alt=""):
    node = soup.new_tag("image-component")
    node["src"] = src
    node["status"] = "uploaded"
    node["alignment"] = "left"
    if alt:
        node["alt"] = alt
    return node


def markdown_to_html(markdown):
    """Markdown -> editor HTML (unsanitised; callers sanitise as usual)."""
    if not markdown or not markdown.strip():
        return "<p></p>"
    soup = BeautifulSoup(_MD.render(markdown), "html.parser")

    # Images -> the editor's image node. ``asset:<uuid>`` means an uploaded asset.
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if src.startswith(ASSET_SCHEME):
            src = src[len(ASSET_SCHEME) :]
        if not src:
            img.decompose()
            continue
        img.replace_with(_image_component(soup, src, img.get("alt") or ""))
    # The image node is a block: lift it out of paragraphs that hold only images.
    for paragraph in soup.find_all("p"):
        children = [c for c in paragraph.contents if not (isinstance(c, str) and not c.strip())]
        if children and all(getattr(c, "name", None) == "image-component" for c in children):
            paragraph.replace_with(*children)

    # GFM task lists -> TipTap's taskList / taskItem.
    for ul in soup.find_all("ul", class_="contains-task-list"):
        ul.attrs = {"data-type": "taskList"}
        for li in ul.find_all("li", class_="task-list-item", recursive=False):
            checkbox = li.find("input")
            checked = bool(checkbox and checkbox.has_attr("checked"))
            if checkbox:
                checkbox.decompose()
            li.attrs = {"data-type": "taskItem", "data-checked": "true" if checked else "false"}
            if not li.find("p"):
                inner = BeautifulSoup("".join(str(c) for c in li.contents).strip(), "html.parser")
                li.clear()
                paragraph = soup.new_tag("p")
                paragraph.extend(list(inner.contents))
                li.append(paragraph)

    # Fenced code without a language -> plaintext, the editor's default.
    for code in soup.select("pre > code"):
        if not any(c.startswith("language-") for c in code.get("class", [])):
            code["class"] = ["language-plaintext"]

    return str(soup).strip() or "<p></p>"


class _PlaneMarkdownConverter(MarkdownConverter):
    """markdownify, taught Plane's custom nodes."""

    def convert_image_component(self, el, text, *args, **kwargs):
        src = (el.get("src") or "").strip()
        if not src:
            return ""
        if _UUID.match(src):
            src = f"{ASSET_SCHEME}{src}"
        return f"\n\n![{el.get('alt') or ''}]({src})\n\n"

    def convert_mention_component(self, el, text, *args, **kwargs):
        return f"@{el.get('entity_name') or 'mention'}:{el.get('entity_identifier') or el.get('id') or ''}"

    def convert_li(self, el, text, *args, **kwargs):
        if el.get("data-type") == "taskItem":
            mark = "[x]" if el.get("data-checked") == "true" else "[ ]"
            return f"- {mark} {text.strip()}\n"
        return super().convert_li(el, text, *args, **kwargs)

    def convert_ul(self, el, text, *args, **kwargs):
        if el.get("data-type") == "taskList":
            return f"\n\n{text}\n"
        return super().convert_ul(el, text, *args, **kwargs)


def _code_language(el):
    for cls in el.get("class") or []:
        if cls.startswith("language-") and cls != "language-plaintext":
            return cls[len("language-") :]
    code = el.find("code")
    if code is not None:
        return _code_language(code)
    return None


def html_to_markdown(html):
    """Editor HTML -> Markdown (GFM)."""
    if not html or html.strip() in ("<p></p>", ""):
        return ""
    markdown = _PlaneMarkdownConverter(
        heading_style="ATX",
        bullets="-",
        code_language_callback=_code_language,
        escape_underscores=False,
        escape_asterisks=False,
    ).convert(html)
    return re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"


def to_html(html=None, markdown=None):
    """Resolve an incoming body to HTML: explicit Markdown wins; HTML that has
    no tags at all is taken as Markdown; otherwise the HTML is returned."""
    if markdown is not None:
        return markdown_to_html(markdown)
    if looks_like_markdown(html):
        return markdown_to_html(html)
    return html


_HTML_FIELDS = {
    "description_html": "description_markdown",
    "comment_html": "comment_markdown",
    "overview_html": "overview_markdown",
}


def add_markdown_fields(data, _depth=0):
    """Add ``*_markdown`` beside each ``description_html`` / ``comment_html``
    found in a response payload (dicts, lists and paginated ``results``)."""
    if _depth > 6:
        return
    if isinstance(data, list):
        for item in data:
            add_markdown_fields(item, _depth + 1)
    elif isinstance(data, dict):
        for html_key, markdown_key in _HTML_FIELDS.items():
            value = data.get(html_key)
            if isinstance(value, str) and markdown_key not in data:
                data[markdown_key] = html_to_markdown(value)
        for value in data.values():
            if isinstance(value, (list, dict)):
                add_markdown_fields(value, _depth + 1)
