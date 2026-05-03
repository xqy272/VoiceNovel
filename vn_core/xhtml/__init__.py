"""Cleaned XHTML Generator: produce data-seg-id annotated HTML for Reader packages."""

from __future__ import annotations

import html
from collections import defaultdict

from vn_core.contracts.segment import Segment


def generate_cleaned_html(
    chapter_id: str,
    segments: list[Segment],
    adapted_texts: dict[str, str] | None = None,
    source_href: str = "",
    chapter_title: str = "",
) -> str:
    adapted_texts = adapted_texts or {}

    paragraphs: dict[str, list[Segment]] = defaultdict(list)
    for seg in segments:
        paragraphs[seg.paragraph_id].append(seg)

    for pid in paragraphs:
        paragraphs[pid].sort(key=lambda s: s.source_order)

    ordered_pids = []
    seen = set()
    for seg in segments:
        if seg.paragraph_id not in seen:
            ordered_pids.append(seg.paragraph_id)
            seen.add(seg.paragraph_id)

    parts = []
    parts.append(f'<div class="chapter" data-chapter="{html.escape(chapter_id)}">')

    if chapter_title:
        parts.append(f"<h1>{html.escape(chapter_title)}</h1>")

    for pid in ordered_pids:
        segs = paragraphs.get(pid, [])
        if not segs:
            continue

        parts.append(f'  <p data-pid="{html.escape(pid)}">')

        for seg in segs:
            text = adapted_texts.get(seg.segment_id, seg.text)
            escaped_text = html.escape(text)
            parts.append(
                f'    <span data-seg-id="{html.escape(seg.segment_id)}">'
                f"{escaped_text}</span>"
            )

        parts.append("  </p>")

    parts.append("</div>")
    return "\n".join(parts)


def wrap_full_document(
    body_html: str,
    book_id: str = "",
    title: str = "",
    encoding: str = "utf-8",
) -> str:
    escaped_title = html.escape(title) if title else html.escape(book_id)
    return f"""<?xml version="1.0" encoding="{encoding}"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">
<head>
  <meta charset="{encoding}" />
  <meta name="generator" content="VoiceNovel" />
  <title>{escaped_title}</title>
  <style>
    .chapter {{ line-height: 1.8; font-size: 1.1em; }}
    .chapter p {{ margin: 0.8em 0; text-indent: 2em; }}
    .highlight {{ background-color: #ffe082; border-radius: 2px; }}
  </style>
</head>
<body>
{body_html}
</body>
</html>"""
