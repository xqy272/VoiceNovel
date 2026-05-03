"""Book Import: EPUB/TXT/HTML to structured chapters and paragraphs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SourceParagraph:
    book_id: str
    chapter_id: str
    paragraph_id: str
    source_text: str
    source_href: str = ""
    source_order: int = 0
    source_dom_hint: str = ""


@dataclass
class ImportedChapter:
    book_id: str
    chapter_id: str
    title: str = ""
    paragraphs: list[SourceParagraph] = field(default_factory=list)
    source_file: str = ""


def import_txt(book_id: str, file_path: str) -> list[ImportedChapter]:
    text = Path(file_path).read_text(encoding="utf-8")

    chapter_pattern = re.compile(r"^第[一二三四五六七八九十百千\d]+[章节幕]", re.MULTILINE)
    splits = list(chapter_pattern.finditer(text))

    if not splits:
        paragraphs: list[SourceParagraph] = []
        order = 0
        raw_paragraphs = re.split(r"\n\s*\n", text)
        for raw in raw_paragraphs:
            stripped = raw.strip()
            if not stripped:
                continue
            pid = f"ch001_p{order:03d}"
            paragraphs.append(
                SourceParagraph(
                    book_id=book_id,
                    chapter_id="ch001",
                    paragraph_id=pid,
                    source_text=stripped,
                    source_href=Path(file_path).name,
                    source_order=order,
                    source_dom_hint=f"txt:p:nth-of-type({order + 1})",
                )
            )
            order += 1

        return [
            ImportedChapter(
                book_id=book_id,
                chapter_id="ch001",
                title="",
                paragraphs=paragraphs,
                source_file=str(file_path),
            )
        ]

    chapters: list[ImportedChapter] = []
    boundaries = [(m.start(), m.group().strip()) for m in splits] + [(len(text), "")]

    for i, ((start, title), (next_start, _)) in enumerate(zip(boundaries[:-1], boundaries[1:])):
        chapter_text = text[start:next_start].strip()
        chapter_id = f"ch{i + 1:03d}"
        paras: list[SourceParagraph] = []
        raw_paras = re.split(r"\n\s*\n", chapter_text)
        order = 0
        for raw in raw_paras:
            stripped = raw.strip()
            if not stripped:
                continue
            pid = f"{chapter_id}_p{order:03d}"
            paras.append(
                SourceParagraph(
                    book_id=book_id,
                    chapter_id=chapter_id,
                    paragraph_id=pid,
                    source_text=stripped,
                    source_href=Path(file_path).name,
                    source_order=order,
                    source_dom_hint=f"txt:p:nth-of-type({order + 1})",
                )
            )
            order += 1

        chapters.append(
            ImportedChapter(
                book_id=book_id,
                chapter_id=chapter_id,
                title=title,
                paragraphs=paras,
                source_file=str(file_path),
            )
        )

    return chapters


def import_epub(book_id: str, file_path: str) -> list[ImportedChapter]:
    try:
        from ebooklib import epub
    except ImportError:
        raise ImportError("ebooklib is required for EPUB import: pip install ebooklib")

    book = epub.read_epub(file_path)
    chapters: list[ImportedChapter] = []
    chapter_idx = 0

    for item in book.get_items_of_type(9):
        content = item.get_content().decode("utf-8", errors="replace")
        from html.parser import HTMLParser

        class _P(HTMLParser):
            def __init__(self):
                super().__init__()
                self.paras: list[str] = []
                self._cur = ""
                self._in_p = False

            def handle_starttag(self, tag, attrs):
                if tag == "p":
                    self._in_p = True

            def handle_endtag(self, tag):
                if tag == "p":
                    self._in_p = False
                    t = self._cur.strip()
                    if t:
                        self.paras.append(t)
                    self._cur = ""

            def handle_data(self, data):
                if self._in_p:
                    self._cur += data

        parser = _P()
        parser.feed(content)

        if not parser.paras:
            continue

        chapter_id = f"ch{chapter_idx + 1:03d}"
        source_href = item.get_name() or ""
        paras: list[SourceParagraph] = []
        for i, p_text in enumerate(parser.paras):
            pid = f"{chapter_id}_p{i:03d}"
            paras.append(
                SourceParagraph(
                    book_id=book_id,
                    chapter_id=chapter_id,
                    paragraph_id=pid,
                    source_text=p_text,
                    source_href=source_href,
                    source_order=i,
                    source_dom_hint=f"body p:nth-of-type({i + 1})",
                )
            )

        chapters.append(
            ImportedChapter(
                book_id=book_id,
                chapter_id=chapter_id,
                title=item.get_name() or f"Chapter {chapter_idx + 1}",
                paragraphs=paras,
                source_file=str(file_path),
            )
        )
        chapter_idx += 1

    return chapters


def import_book(file_path: str, book_id: str = "", store=None) -> list[ImportedChapter]:
    path = Path(file_path)
    suffix = path.suffix.lower()

    if not book_id:
        book_id = f"book_{path.stem}"

    if suffix == ".txt":
        chapters = import_txt(book_id, file_path)
    elif suffix == ".epub":
        chapters = import_epub(book_id, file_path)
    else:
        raise ValueError(f"Unsupported file format: {suffix}")

    if store is not None:
        store.upsert_book(
            book_id,
            title=chapters[0].title if chapters else "",
            source_file=str(file_path),
        )
        for ci, chapter in enumerate(chapters):
            store.upsert_chapter(chapter.book_id, chapter.chapter_id, title=chapter.title,
                                source_file=chapter.source_file, chapter_order=ci)
            for para in chapter.paragraphs:
                store.upsert_paragraph(para.book_id, para.chapter_id, para.paragraph_id,
                                        text=para.source_text, source_href=para.source_href,
                                       source_order=para.source_order,
                                       source_dom_hint=para.source_dom_hint)

    return chapters
