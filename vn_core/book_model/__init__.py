"""Book Model: structured novel understanding, runtime projection of Project Store."""

from __future__ import annotations

from vn_core.store import ProjectStore


class BookModel:
    def __init__(self, store: ProjectStore, book_id: str):
        self.store = store
        self.book_id = book_id

    def get_characters(self) -> list[dict]:
        return self.store.get_characters(self.book_id)

    def get_character(self, character_id: str) -> dict | None:
        characters = self.get_characters()
        for c in characters:
            if c["character_id"] == character_id:
                return c
        return None

    def get_scene_snapshot(self, chapter_id: str) -> dict | None:
        return self.store.get_scene_snapshot(self.book_id, chapter_id)

    def update_scene_snapshot(
        self, chapter_id: str, data: dict, created_by: str = "", run_id: str = ""
    ):
        self.store.upsert_scene_snapshot(self.book_id, chapter_id, data, created_by, run_id)

    def get_voice_assignment(self, character_id: str) -> dict | None:
        conn = self.store._get_conn()
        row = conn.execute(
            "SELECT * FROM voice_assignments WHERE book_id=? AND character_id=?",
            (self.book_id, character_id),
        ).fetchone()
        return dict(row) if row else None

    def lookup_character_by_name_or_alias(self, name: str) -> dict | None:
        import json

        for c in self.get_characters():
            names = json.loads(c.get("names", "[]"))
            aliases = json.loads(c.get("aliases", "[]"))
            if name in names or name in aliases:
                return c
        return None
