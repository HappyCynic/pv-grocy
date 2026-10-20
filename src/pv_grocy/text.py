# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Grocy stores descriptions as HTML (from its rich-text editor): turn them into plain text
with the standard library, dropping scripts, styles and images and never fetching anything."""

from __future__ import annotations

from html.parser import HTMLParser

DESCRIPTION_MAX_CHARS = 4000
_BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "ul", "ol"}
_SKIP = {"script", "style", "template", "head"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n- " if tag == "li" else "\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    if "<" not in html:
        return html.strip()
    parser = _Text()
    parser.feed(html)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def clip(text: str, max_chars: int = DESCRIPTION_MAX_CHARS) -> tuple[str, bool]:
    """(text, truncated)."""
    if len(text) <= max_chars:
        return text, False
    return text[: max_chars - 1] + "…", True


def description(html: str | None, max_chars: int = DESCRIPTION_MAX_CHARS) -> dict[str, object]:
    text, truncated = clip(html_to_text(html), max_chars)
    return {"description": text, **({"description_truncated": True} if truncated else {})}
