"""Tests for Context Fetch Engine."""

import pytest

from vn_core.book_model import BookModel
from vn_core.context import ContextFetchEngine
from vn_core.contracts.context_spec import ContextSpec
from vn_core.store import ProjectStore


@pytest.fixture
def store_with_data(tmp_path):
    db_path = tmp_path / "ctx_test.sqlite"
    s = ProjectStore(str(db_path))
    s.initialize()

    s.upsert_book("book01", title="Test Book")
    s.upsert_chapter("book01", "ch001", title="Chapter 1")
    s.upsert_paragraph("book01", "ch001", "ch001_p000", "他走进了房间。", source_order=0)
    s.upsert_paragraph("book01", "ch001", "ch001_p001", "她说道：你好。", source_order=1)
    s.upsert_paragraph("book01", "ch001", "ch001_p002", "天空很蓝。", source_order=2)

    s.upsert_character(
        "book01", "char_lu_ming",
        names=["陆明"], aliases=["少主"], traits=["male", "young", "determined"],
    )
    s.upsert_character(
        "book01", "char_lin_wan",
        names=["林婉"], aliases=["婉儿"], traits=["female", "young", "calm"],
    )

    s.upsert_decision(
        "book01", "ch001_p001_s000", "speaker",
        value={"speaker_id": "char_narrator"}, confidence=1.0,
    )

    return s


class TestContextFetchEngine:
    def test_fetch_basic_spec(self, store_with_data):
        bm = BookModel(store_with_data, "book01")
        engine = ContextFetchEngine(store_with_data, bm)
        spec = ContextSpec(
            task="speaker_attribution",
            chapter_id="ch001",
            segment_ids=["ch001_p000_s000"],
            active_characters={"top_k": 5},
        )
        capsule = engine.fetch(spec)
        assert capsule.task == "speaker_attribution"
        assert len(capsule.active_characters) >= 2

    def test_fetch_without_book_model(self, store_with_data):
        engine = ContextFetchEngine(store_with_data)
        spec = ContextSpec(
            task="text_adaptation",
            chapter_id="ch001",
        )
        capsule = engine.fetch(spec)
        assert capsule.task == "text_adaptation"
        assert len(capsule.active_characters) == 0

    def test_fetch_with_glossary(self, store_with_data):
        store_with_data._get_conn().execute(
            """INSERT INTO glossary (book_id, term, definition, category, confidence, status)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ("book01", "剑法", "martial arts sword technique", "skill", 0.8, "inferred"),
        )
        store_with_data._get_conn().commit()

        bm = BookModel(store_with_data, "book01")
        engine = ContextFetchEngine(store_with_data, bm)
        spec = ContextSpec(
            task="speaker_attribution",
            chapter_id="ch001",
            glossary=True,
        )
        capsule = engine.fetch(spec)
        assert len(capsule.glossary_terms) >= 1

    def test_fetch_with_decisions(self, store_with_data):
        bm = BookModel(store_with_data, "book01")
        engine = ContextFetchEngine(store_with_data, bm)
        spec = ContextSpec(
            task="speaker_attribution",
            chapter_id="ch001",
            segment_ids=["ch001_p001_s000"],
            prior_decisions=True,
        )
        capsule = engine.fetch(spec)
        assert len(capsule.prior_decisions) >= 1
