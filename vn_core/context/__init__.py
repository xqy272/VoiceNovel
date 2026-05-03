"""Context Fetch Engine: assemble ContextCapsule from ContextSpec + BookModel."""

from __future__ import annotations

import json

from vn_core.book_model import BookModel
from vn_core.contracts.context_capsule import ContextCapsule
from vn_core.contracts.context_spec import ContextSpec
from vn_core.store import ProjectStore


class ContextFetchEngine:
    def __init__(self, store: ProjectStore, book_model: BookModel | None = None):
        self.store = store
        self.book_model = book_model

    def fetch(self, spec: ContextSpec) -> ContextCapsule:
        capsule = ContextCapsule(
            task=spec.task,
            segment_ids=spec.segment_ids,
            chapter_id=spec.chapter_id,
        )

        capsule.target_segments = self._load_target_segments(spec)
        capsule.left_context, capsule.right_context = self._load_text_context(spec)
        capsule.active_characters = self._load_characters(spec)
        capsule.scene_summary, capsule.recent_dialogue_state = self._load_scene_state(spec)
        capsule.glossary_terms = self._load_glossary(spec)
        capsule.pronunciation_overrides = self._load_pronunciation(spec)
        capsule.prior_decisions = self._load_decisions(spec)
        capsule.locked_items = self._load_locked_items(spec)

        return capsule

    def _load_target_segments(self, spec: ContextSpec) -> list[dict]:
        conn = self.store._get_conn()
        segments = []
        for seg_id in spec.segment_ids:
            para_id = (
                "_s".join(seg_id.split("_s")[:-1])
                if "_s" in seg_id else seg_id
            )
            row = conn.execute(
                "SELECT paragraph_id, text, source_href, source_order "
                "FROM paragraphs WHERE paragraph_id=?",
                (para_id,),
            ).fetchone()
            if row:
                segments.append(dict(row))
        return segments

    def _load_text_context(self, spec: ContextSpec) -> tuple[str, str]:
        if not spec.segment_ids or not spec.chapter_id:
            return "", ""
        conn = self.store._get_conn()
        book_id = self.book_model.book_id if self.book_model else ""
        paragraphs = conn.execute(
            "SELECT paragraph_id, text "
            "FROM paragraphs "
            "WHERE book_id=? AND chapter_id=? "
            "ORDER BY source_order",
            (book_id, spec.chapter_id),
        ).fetchall()
        if not paragraphs:
            paragraphs = conn.execute(
                "SELECT paragraph_id, text "
                "FROM paragraphs "
                "WHERE chapter_id=? "
                "ORDER BY source_order",
                (spec.chapter_id,),
            ).fetchall()
        if not paragraphs:
            return "", ""

        para_map = {
            p["paragraph_id"]: idx for idx, p in enumerate(paragraphs)
        }
        target_indices = set()
        for seg_id in spec.segment_ids:
            para_id = (
                "_s".join(seg_id.split("_s")[:-1])
                if "_s" in seg_id else seg_id
            )
            if para_id in para_map:
                target_indices.add(para_map[para_id])
        if not target_indices:
            mid = len(paragraphs) // 2
            target_indices = {mid}

        min_idx = min(target_indices)
        max_idx = min(max(target_indices), len(paragraphs) - 1)

        left_paras = paragraphs[:min_idx]
        right_paras = paragraphs[max_idx + 1:max_idx + 4]

        left_text = " ".join(
            p["text"] for p in left_paras[-3:]
        )[-500:]
        right_text = " ".join(
            p["text"] for p in right_paras[:3]
        )[:500]
        return left_text[:1000], right_text[:1000]

    def _load_characters(self, spec: ContextSpec) -> list[dict]:
        if not self.book_model or not spec.active_characters:
            return []
        characters = self.book_model.get_characters()
        if spec.active_characters.get("top_k"):
            top_k = spec.active_characters.get("top_k")
            return characters[:top_k]
        specific_ids = spec.active_characters.get("ids", [])
        if specific_ids:
            return [
                c for c in characters
                if c["character_id"] in specific_ids
            ]
        return characters

    def _load_scene_state(self, spec: ContextSpec) -> tuple[str, dict]:
        """Load scene summary and rich dialogue state from snapshot."""
        if not spec.scene_state or not spec.chapter_id or not self.book_model:
            return "", {}
        snapshot = self.book_model.get_scene_snapshot(spec.chapter_id)
        if snapshot and snapshot.get("snapshot_data"):
            data = snapshot["snapshot_data"]
            if isinstance(data, str):
                data = json.loads(data)
            summary = data.get("summary", "")
            dialogue_state = {
                "last_speaker": data.get("last_speaker"),
                "last_addressee": data.get("last_addressee"),
                "turn_pattern": data.get("turn_pattern", "none"),
                "character_turn_counts": data.get("character_turn_counts", {}),
            }
            return summary, dialogue_state
        return "", {}

    def _load_glossary(self, spec: ContextSpec) -> list[dict]:
        if not spec.glossary:
            return []
        conn = self.store._get_conn()
        book_id = self.book_model.book_id if self.book_model else ""
        if not book_id:
            return []
        rows = conn.execute(
            "SELECT * FROM glossary WHERE book_id=?", (book_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def _load_pronunciation(self, spec: ContextSpec) -> list[dict]:
        if not spec.pronunciation:
            return []
        conn = self.store._get_conn()
        book_id = self.book_model.book_id if self.book_model else ""
        if not book_id:
            return []
        rows = conn.execute(
            "SELECT * FROM pronunciation_overrides WHERE book_id=?",
            (book_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _load_decisions(self, spec: ContextSpec) -> list[dict]:
        if not spec.prior_decisions:
            return []
        conn = self.store._get_conn()
        book_id = self.book_model.book_id if self.book_model else ""
        if not book_id:
            return []
        if spec.segment_ids:
            placeholders = ",".join("?" * len(spec.segment_ids))
            rows = conn.execute(
                f"SELECT * FROM decisions "
                f"WHERE book_id=? AND segment_id IN ({placeholders})",
                (book_id, *spec.segment_ids),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE book_id=?", (book_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def _load_locked_items(self, spec: ContextSpec) -> list[dict]:
        if not spec.locked_items:
            return []
        conn = self.store._get_conn()
        book_id = self.book_model.book_id if self.book_model else ""
        if not book_id:
            return []
        rows = conn.execute(
            "SELECT * FROM decisions WHERE book_id=? AND user_locked=1",
            (book_id,),
        ).fetchall()
        return [dict(r) for r in rows]
