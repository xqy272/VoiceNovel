"""Server API smoke tests for the reader playback path."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from vn_core.store import ProjectStore
from vn_server.api import create_app

GOLDEN_BOOK = Path(__file__).parent / "golden_books" / "mountain_inn.txt"


def test_import_bake_and_reader_endpoints(tmp_path):
    app = create_app(
        data_dir=str(tmp_path / "data"),
        store_path=str(tmp_path / "project.sqlite"),
    )
    client = TestClient(app)

    created = client.post(
        "/api/projects",
        json={"source_path": str(GOLDEN_BOOK), "book_id": "api_book"},
    )
    assert created.status_code == 200
    assert created.json()["chapters"]

    config = client.get("/api/projects/api_book/generation-config")
    assert config.status_code == 200
    assert config.json()["reading_profile"] == "enhanced"

    updated_config = client.post(
        "/api/projects/api_book/generation-config",
        json={"reading_profile": "faithful", "execution_mode": "economy"},
    )
    assert updated_config.status_code == 200
    assert updated_config.json()["reading_profile"] == "faithful"

    chapters = client.get("/api/projects/api_book/chapters")
    assert chapters.status_code == 200
    assert isinstance(chapters.json(), list)

    baked = client.post("/api/bake", json={"book_id": "api_book", "chapter_id": "ch001"})
    assert baked.status_code == 200
    assert baked.json()["success"] is True
    assert baked.json()["reading_profile"] == "faithful"

    content = client.get("/api/projects/api_book/chapters/ch001/content")
    assert content.status_code == 200
    assert "data-seg-id" in content.text

    timing = client.get("/api/projects/api_book/chapters/ch001/timing")
    assert timing.status_code == 200
    assert timing.json()

    audio = client.get("/api/projects/api_book/chapters/ch001/audio")
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/")


def test_prefetch_accepts_json_body_current_chapter(tmp_path):
    store_path = tmp_path / "project.sqlite"
    app = create_app(data_dir=str(tmp_path / "data"), store_path=str(store_path))

    seed = ProjectStore(str(store_path))
    seed.initialize()
    try:
        seed.upsert_book("prefetch_book", title="Prefetch Book")
        for i in range(1, 4):
            seed.upsert_chapter(
                "prefetch_book",
                f"ch{i:03d}",
                title=f"Chapter {i}",
                chapter_order=i - 1,
            )
    finally:
        seed.close()

    client = TestClient(app)
    response = client.post(
        "/api/projects/prefetch_book/prefetch",
        json={"current_chapter_id": "ch002"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_chapter"] == "ch002"
    assert payload["prefetch_chapters"] == ["ch003"]
    assert [job["chapter_id"] for job in payload["enqueued_jobs"]] == ["ch003"]


def test_segment_endpoint_preserves_source_metadata(tmp_path):
    store_path = tmp_path / "project.sqlite"
    app = create_app(data_dir=str(tmp_path / "data"), store_path=str(store_path))

    seed = ProjectStore(str(store_path))
    seed.initialize()
    try:
        seed.upsert_book("source_book", title="Source Book")
        seed.upsert_chapter("source_book", "ch001", title="Chapter 1")
        seed.upsert_paragraph(
            "source_book",
            "ch001",
            "ch001_p001",
            text="他走进了房间。",
            source_href="chapter1.xhtml",
            source_order=7,
            source_dom_hint="body p:nth-of-type(8)",
        )
    finally:
        seed.close()

    client = TestClient(app)
    response = client.post("/api/projects/source_book/chapters/ch001/segment")

    assert response.status_code == 200
    segment = response.json()["segments"][0]
    assert segment["source_href"] == "chapter1.xhtml"
    assert segment["source_order"] == 7
    assert segment["source_dom_hint"] == "body p:nth-of-type(8)"
