# Book Model — AI Agent Guide

## Purpose
Runtime projection over the Project Store that provides structured novel understanding: character lookup (by name/alias), scene snapshots, voice assignments, and character trait queries. Services query the Book Model instead of raw SQL.

## Key Concepts
- **Read projection**: BookModel wraps ProjectStore reads with domain logic (name/alias matching, JSON parsing)
- **Character identity**: Characters are stored with names array + aliases array; `lookup_character_by_name_or_alias` matches against both
- **Scene snapshots**: Per-chapter summaries with active characters, location, and key events

## Module: `vn_core/book_model/`

### `BookModel(store: ProjectStore, book_id: str)`

#### Character Operations
- `get_characters() -> list[dict]` — All characters for this book
- `get_character(character_id) -> dict | None` — Single character by ID
- `lookup_character_by_name_or_alias(name) -> dict | None` — Find character by any name or alias (JSON-deserializes names/aliases columns)

#### Scene Operations
- `get_scene_snapshot(chapter_id) -> dict | None` — Chapter scene summary
- `update_scene_snapshot(chapter_id, data, created_by, run_id)` — Write scene data

#### Voice Operations
- `get_voice_assignment(character_id) -> dict | None` — Get voice binding for a character

## Usage Pattern
```python
book_model = BookModel(store, book_id)
char = book_model.lookup_character_by_name_or_alias("陆明")
if char:
    speaker_id = char["character_id"]
```

## Dependencies
- `vn_core.store.ProjectStore` — all data queries
