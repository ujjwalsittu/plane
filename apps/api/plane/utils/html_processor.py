# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import re
from io import StringIO
from html.parser import HTMLParser


class MLStripper(HTMLParser):
    """
    Markup Language Stripper
    """

    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = StringIO()

    def handle_data(self, d):
        self.text.write(d)

    def get_data(self):
        return self.text.getvalue()


def strip_tags(html):
    s = MLStripper()
    s.feed(html)
    return s.get_data()


_BREAKS = re.compile(r"<br\s*/?>|</(?:p|li|h[1-6]|div|blockquote|pre|tr)>", re.IGNORECASE)


def html_to_plain_text(html):
    """Text of an HTML fragment with line breaks kept: <br> and the end of a paragraph, list item,
    heading or similar block become newlines (strip_tags alone runs those lines together)."""
    text = strip_tags(_BREAKS.sub("\n", html or ""))
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())
