# Importers — AI Agent Guide

## Purpose
Import TXT and EPUB source files into structured chapters and paragraphs, writing results to the Project Store.

## Key Concepts
- **SourceParagraph**: A single paragraph with book/chapter IDs, order, and DOM hint
- **ImportedChapter**: A chapter with title, source file, and ordered paragraphs
- **Chapter detection**: TXT importer uses regex `^第[...]章` to split chapters; falls back to single-chapter if no headers found
- **Paragraph splitting**: Double-newline (`\n\n`) boundaries; empty paragraphs are dropped

## Module: `vn_core/importers/`

### `import_txt(book_id, file_path) -> list[ImportedChapter]`
1. Read file as UTF-8
2. Scan for chapter headers via regex
3. If no headers: create single `ch001` with all paragraphs
4. If headers found: split text at each header, create one chapter per section
5. Within each chapter, split on `\n\s*\n` for paragraphs

### `import_epub(book_id, file_path) -> list[ImportedChapter]`
1. Uses `ebooklib` to read EPUB
2. Iterates over document items (type 9 = ITEM_DOCUMENT)
3. Parses HTML with simple `HTMLParser` — extracts `<p>` tag content
4. Skips empty documents

### `import_book(file_path, book_id, store) -> list[ImportedChapter]`
Unified entry point:
1. Detects format from file extension (`.txt` or `.epub`)
2. Auto-generates book_id from stem if not provided
3. Calls format-specific importer
4. If store provided: writes book, chapters, and paragraphs to Project Store

## Segment ID Convention
Paragraph IDs follow `{chapter_id}_p{NNN}` format (e.g., `ch001_p000`). Segmenter later adds `_s{NNN}` for segment IDs.

## Dependencies
- `vn_core.store.ProjectStore` — for persisting imported structure
- `ebooklib` — optional, for EPUB import
