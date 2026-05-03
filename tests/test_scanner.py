"""Tests for Book Scanner module."""

import pytest

from vn_core.llm_gateway import LLMGateway
from vn_core.scanner import BookScanner
from vn_core.store import ProjectStore


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "scan_test.sqlite"
    s = ProjectStore(str(db_path))
    s.initialize()
    s.upsert_book("book01", title="Test Book")
    s.upsert_chapter("book01", "ch001", title="Chapter 1")
    yield s
    s.close()


class TestBookScanner:
    @pytest.mark.asyncio
    async def test_scan_chapter_with_mock(self, store):
        llm = LLMGateway()
        scanner = BookScanner(llm=llm, store=store)
        result = await scanner.scan_chapter(
            "book01", "ch001",
            "陆明走进了房间。林婉说：你好。",
        )
        assert "characters" in result
        assert "scene" in result

    @pytest.mark.asyncio
    async def test_scan_book_with_mock(self, store):
        llm = LLMGateway()
        scanner = BookScanner(llm=llm, store=store)
        result = await scanner.scan_book(
            "book01",
            [
                {"chapter_id": "ch001", "text": "第一章。陆明来了。"},
                {"chapter_id": "ch002", "text": "第二章。林婉笑了。"},
            ],
        )
        assert "characters" in result
        assert "glossary" in result
