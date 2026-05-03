"""VoiceNovel Server: FastAPI REST + WebSocket API."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import (
    BackgroundTasks,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from vn_core.book_model import BookModel
from vn_core.contracts.generation_config import GenerationConfig
from vn_core.contracts.job_state import JobStage, JobState, JobStatus
from vn_core.contracts.reader_adapter import ReaderAdapterResponse
from vn_core.contracts.reader_manifest import ReaderPackageManifest
from vn_core.contracts.timing_entry import TimingEntry
from vn_core.cost_planner import CostPlanner
from vn_core.harness import GateDecision, HarnessGate
from vn_core.importers import import_book
from vn_core.llm_gateway import LLMGateway
from vn_core.orchestration import Orchestrator
from vn_core.packaging import PackagingService
from vn_core.pipeline.pipeline import Pipeline
from vn_core.planner import ReadingPlanner
from vn_core.preflight import PreflightCheck
from vn_core.prompts import PromptRegistry
from vn_core.render import CosyVoiceAdapter, SpeechGateway
from vn_core.render.tts_input_composer import TTSInputComposer
from vn_core.segmenter import ChineseSegmenter
from vn_core.store import ProjectStore
from vn_core.voice import VoiceRegistry


class CreateProjectRequest(BaseModel):
    source_path: str = Field(..., description="path to TXT or EPUB file")
    title: str = Field(default="", description="book title override")
    book_id: str | None = Field(default=None, description="custom book id")


class JobSubmitRequest(BaseModel):
    book_id: str = Field(...)
    chapter_id: str = Field(...)
    stage: str = Field(default="tts_render")
    priority: str = Field(default="P2")
    generation_config_id: str = Field(default="default")
    reading_profile: Literal["faithful", "enhanced"] | None = Field(default=None)


class BakeChapterRequest(BaseModel):
    book_id: str = Field(...)
    chapter_id: str = Field(...)
    generation_config_id: str = Field(default="default")
    reading_profile: Literal["faithful", "enhanced"] | None = Field(default=None)


class GenerationConfigRequest(BaseModel):
    generation_config_id: str = Field(default="default")
    reading_profile: Literal["faithful", "enhanced"] = Field(default="enhanced")
    execution_mode: Literal["economy", "balanced"] = Field(default="balanced")
    tts_engine: str = Field(default="mock")
    cache_buster: str | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActivateArtifactRequest(BaseModel):
    artifact_version_id: str = Field(...)


class PrefetchRequest(BaseModel):
    current_chapter_id: str = Field(default="ch001")
    generation_config_id: str = Field(default="default")


class PreflightRequest(BaseModel):
    operation: Literal["bake", "cold_start", "rebuild", "export"] = "bake"
    generation_config_id: str = "default"
    format: str = "daw"


class VoiceAssignmentUpdate(BaseModel):
    character_id: str = Field(...)
    voice_id: str = Field(...)


class UnlockVoiceRequest(BaseModel):
    character_id: str = Field(...)


class ReplayRequest(BaseModel):
    source_text: str = Field(...)
    ops: list = Field(default_factory=list)
    scope: str | None = Field(default=None)


class DiffRequest(BaseModel):
    before: str = Field(...)
    after: str = Field(...)


class RollbackRequest(BaseModel):
    op_ids: list = Field(...)
    reason: str = Field(default="manual rollback")


class ReaderAdapterRequestModel(BaseModel):
    book_id: str = Field(...)
    chapter_id: str | None = Field(default=None)
    position_segment_id: str | None = Field(default=None)
    position_time_ms: int | None = Field(default=None)
    action: str = Field(default="get_status")
    capabilities: list[str] = Field(default_factory=list)


def create_app(data_dir: str = "data", store_path: str | None = None) -> FastAPI:
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)

    db_path = store_path or str(data_path / "projects.sqlite")
    store = ProjectStore(db_path)
    store.initialize()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await orchestrator.start()
        try:
            yield
        finally:
            await orchestrator.stop()
            store.close()

    app = FastAPI(
        title="VoiceNovel",
        version="0.1.0",
        description="AI multi-role audiobook system",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    segmenter = ChineseSegmenter()
    voice_registry = VoiceRegistry()
    prompt_registry = PromptRegistry()
    prompt_registry.load_builtins()
    llm_gateway = LLMGateway(prompt_registry=prompt_registry)
    llm_gateway.configure_from_env()
    tts_composer = TTSInputComposer()
    tts_gateway = SpeechGateway(output_dir=str(data_path / "tts_output"))
    tts_gateway.register_adapter(
        "cosyvoice",
        CosyVoiceAdapter(
            output_dir=str(data_path / "tts_output"),
            endpoint=os.environ.get("VN_COSYVOICE_ENDPOINT", "http://localhost:50000"),
        ),
    )
    pkg_service = PackagingService()
    cost_planner = CostPlanner()
    harness = HarnessGate()
    orchestrator = Orchestrator(store=store)

    _active_sessions: dict[str, Any] = {}

    # --- Orchestrator executor wiring ---

    async def _pipeline_executor(job: JobState) -> dict:
        """Create a Pipeline, run bake_chapter, and wire progress to WebSocket sessions."""
        book_id = job.book_id
        if not book_id:
            return {"success": False, "artifact": "", "errors": ["Job missing book_id"]}

        config = store.get_generation_config(book_id, job.generation_config_id)

        pipeline = Pipeline(
            store=store,
            llm=llm_gateway,
            gateway=tts_gateway,
            output_dir=str(data_path),
            tts_engine=config.tts_engine,
            generation_config_id=config.generation_config_id,
            reading_profile=config.reading_profile,
            concurrent_tts=(
                2 if config.execution_mode == "economy" else 4
            ),
        )

        # Forward pipeline progress events to all WebSocket sessions
        async def _broadcast(event_type: str, data: dict):
            await _broadcast_to_all(event_type, data)

        pipeline.on_progress(_broadcast)

        # Rebuild jobs (cache_buster starts with "rebuild:") bypass stale cache
        force_bake = bool(
            job.cache_buster and str(job.cache_buster).startswith("rebuild:")
        )
        result = await pipeline.bake_chapter(
            book_id=book_id, chapter_id=job.unit_id, force=force_bake,
        )

        return {
            "success": result.success,
            "artifact": result.package_dir,
            "errors": result.errors,
        }

    orchestrator.set_executor(_pipeline_executor)

    # --- WebSocket broadcast helper ---

    async def _broadcast_to_all(event_type: str, data: dict):
        payload = {"type": event_type, **data}
        dead = []
        for sid, session in _active_sessions.items():
            try:
                ws = session.get("websocket")
                if ws is not None:
                    await ws.send_json(payload)
            except Exception:
                dead.append(sid)
        for sid in dead:
            _active_sessions.pop(sid, None)

    def _preflight_chapter_op(
        book_id: str, chapter_id: str,
        generation_config_id: str = "default",
        require_package: bool = False,
    ) -> tuple[bool, str]:
        """Lightweight preflight for chapter operations.

        Returns (ok, error_message). Writes exceptions on failure so they
        surface in the Station exception queue with the given stage.
        """
        book = store.get_book(book_id)
        if not book:
            msg = f"Book not found: {book_id}"
            try:
                store.write_exception(
                    book_id=book_id, exception_type="preflight",
                    message=msg, unit_id=chapter_id, stage="preflight",
                )
            except Exception:
                pass
            return False, msg

        chapters = store.get_chapters(book_id)
        if not any(c["chapter_id"] == chapter_id for c in chapters):
            msg = f"Chapter not found: {chapter_id}"
            try:
                store.write_exception(
                    book_id=book_id, exception_type="preflight",
                    message=msg, unit_id=chapter_id, stage="preflight",
                )
            except Exception:
                pass
            return False, msg

        if not store.generation_config_exists(book_id, generation_config_id):
            msg = f"Generation config not found: {generation_config_id}"
            try:
                store.write_exception(
                    book_id=book_id, exception_type="preflight",
                    message=msg, unit_id=chapter_id, stage="preflight",
                )
            except Exception:
                pass
            return False, msg

        if require_package:
            pkg = store.get_current_artifact(book_id, "reader_package", chapter_id)
            if not pkg or not _package_is_valid(book_id, pkg, "full"):
                msg = "No valid reader_package. Bake or rebuild first."
                try:
                    store.write_exception(
                        book_id=book_id, exception_type="preflight",
                        message=msg, unit_id=chapter_id, stage="preflight",
                    )
                except Exception:
                    pass
                return False, msg

        return True, "ok"

    def _validate_path_component(value: str) -> str:
        """Reject path traversal, null bytes, and glob metacharacters in identifiers."""
        if not value:
            raise HTTPException(status_code=400, detail="Empty identifier")
        forbidden = {"..", "/", "\\", "\x00", ":", "*", "?", "[", "]"}
        has_forbidden = any(c in value for c in forbidden)
        if has_forbidden or "%" in value:
            raise HTTPException(status_code=400, detail=f"Invalid identifier: {value[:40]}")
        return value

    def _require_book(book_id: str):
        _validate_path_component(book_id)
        if not store.get_book(book_id):
            raise HTTPException(status_code=404, detail=f"Book not found: {book_id}")

    def _resolve_generation_config(
        book_id: str,
        generation_config_id: str = "default",
        reading_profile: str | None = None,
    ) -> GenerationConfig:
        config = store.get_generation_config(book_id, generation_config_id)
        if reading_profile:
            config = config.model_copy(update={"reading_profile": reading_profile})
        return config

    def _segment_paragraph_row(row: dict) -> list:
        return segmenter.segment_paragraph(
            row["paragraph_id"],
            row["text"],
            source_href=row.get("source_href", ""),
            source_order=row.get("source_order", 0),
            source_dom_hint=row.get("source_dom_hint", ""),
        )

    def _reader_package_is_usable(book_id: str, package_artifact: dict | None) -> bool:
        if not package_artifact:
            return False

        version_id = package_artifact["artifact_version_id"]
        deps = store.get_artifact_dependencies(book_id, version_id)
        if not deps:
            return False

        dep_check = store.check_dependencies_active(book_id, version_id)
        if not dep_check["all_active"]:
            return False

        package_validation = harness.validate(
            "reader_package",
            {
                "package_dir": package_artifact.get("file_path", ""),
                "require_audio": True,
            },
        )
        return package_validation.decision == GateDecision.pass_decision

    @app.get("/")
    async def root():
        return {"name": "VoiceNovel", "version": "0.1.0", "status": "ok"}

    @app.get("/api/projects")
    async def list_projects():
        rows = store._get_conn().execute(
            "SELECT book_id, title FROM books ORDER BY book_id"
        ).fetchall()
        result = []
        for r in rows:
            chapters = store.get_chapters(r[0])
            result.append({
                "book_id": r[0],
                "title": r[1] or r[0],
                "chapters": [
                    {"chapter_id": c["chapter_id"], "title": c["title"], "paragraph_count": 0}
                    for c in chapters
                ],
            })
        return result

    @app.get("/health")
    async def health():
        preflight = PreflightCheck()
        result = preflight.run_preflight()
        return {
            "status": "ok" if result.can_proceed else "degraded",
            "checks": result.checks,
            "warnings": result.warnings,
            "errors": result.errors,
        }

    @app.post("/api/projects")
    async def create_project(req: CreateProjectRequest):
        source = Path(req.source_path).resolve()
        # Restrict imports to known-safe directories
        allowed_roots = [
            data_path.resolve(),
            Path.cwd().resolve(),
        ]
        if not any(
            str(source).startswith(str(root))
            for root in allowed_roots
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Source file must be within the project data directory "
                    "or current working directory"
                ),
            )
        if not source.exists():
            raise HTTPException(status_code=404, detail="Source file not found")
        if not source.is_file():
            raise HTTPException(status_code=400, detail="Source path must be a file")

        book_id = req.book_id or f"book_{source.stem}_{uuid.uuid4().hex[:8]}"
        try:
            chapters = import_book(str(source), book_id=book_id, store=store)
            store.upsert_generation_config(GenerationConfig(book_id=book_id))
        except Exception as e:
            raise HTTPException(status_code=500, detail="Failed to import book") from e

        title = req.title or (chapters[0].title if chapters else book_id)

        return {
            "book_id": book_id,
            "title": title,
            "chapters": [
                {
                    "chapter_id": ch.chapter_id,
                    "title": ch.title,
                    "paragraph_count": len(ch.paragraphs),
                }
                for ch in chapters
            ],
        }

    @app.get("/api/projects/{book_id}")
    async def get_project(book_id: str):
        characters = store.get_characters(book_id)
        artifacts = store._get_conn().execute(
            "SELECT artifact_type, unit_id, status "
            "FROM artifacts WHERE book_id=? AND status='active'",
            (book_id,),
        ).fetchall()
        return {
            "book_id": book_id,
            "characters": characters,
            "artifacts": [{"type": a[0], "unit_id": a[1], "status": a[2]} for a in artifacts],
            "generation_config": store.get_generation_config(book_id).model_dump(),
        }

    @app.get("/api/projects/{book_id}/generation-config")
    async def get_generation_config(
        book_id: str,
        generation_config_id: str = "default",
    ):
        _require_book(book_id)
        return store.get_generation_config(book_id, generation_config_id).model_dump()

    @app.get("/api/projects/{book_id}/artifacts")
    async def list_artifacts(
        book_id: str,
        artifact_type: str | None = None,
        unit_id: str | None = None,
    ):
        """List artifact versions for a book, with optional type/unit filters."""
        _require_book(book_id)
        artifacts = store.list_artifact_versions(book_id, artifact_type, unit_id)
        return {"book_id": book_id, "artifacts": artifacts}

    @app.post("/api/projects/{book_id}/artifacts/activate")
    async def activate_artifact(book_id: str, req: ActivateArtifactRequest):
        """Activate artifact through Harness Gate transaction (atomic)."""
        _require_book(book_id)
        result = harness.activate_artifact(store, book_id, req.artifact_version_id)
        if result.decision == "fail":
            if "not found" in result.reason:
                raise HTTPException(status_code=404, detail=result.reason)
            raise HTTPException(status_code=409, detail=result.reason)
        return {
            "book_id": book_id,
            "artifact_version_id": req.artifact_version_id,
            "status": "active",
        }

    @app.get("/api/projects/{book_id}/artifacts/{artifact_version_id}/dependencies")
    async def get_artifact_dependencies(book_id: str, artifact_version_id: str):
        """Get the dependency graph for an artifact version."""
        _require_book(book_id)
        deps = store.get_artifact_dependencies(book_id, artifact_version_id)
        dep_check = store.check_dependencies_active(book_id, artifact_version_id)
        return {
            "artifact_version_id": artifact_version_id,
            "dependencies": deps,
            "all_active": dep_check["all_active"],
            "inactive": dep_check["inactive"],
        }

    @app.post("/api/projects/{book_id}/generation-config")
    async def update_generation_config(book_id: str, req: GenerationConfigRequest):
        _require_book(book_id)
        config = GenerationConfig(book_id=book_id, **req.model_dump())
        store.upsert_generation_config(config)
        return config.model_dump()

    @app.get("/api/projects/{book_id}/chapters")
    async def list_chapters(book_id: str):
        chapters = store.get_chapters(book_id)
        result = []
        for c in chapters:
            para_count = len(store.get_paragraphs(book_id, c["chapter_id"]))
            result.append({
                "chapter_id": c["chapter_id"],
                "title": c["title"],
                "paragraph_count": para_count,
            })
        return result

    @app.post("/api/projects/{book_id}/chapters/{chapter_id}/segment")
    async def segment_chapter(book_id: str, chapter_id: str):
        _require_book(book_id)
        _validate_path_component(chapter_id)
        paragraphs_data = store.get_paragraphs(book_id, chapter_id)

        if not paragraphs_data:
            raise HTTPException(status_code=404, detail="Chapter not found or no paragraphs")

        all_segments = []
        for p in paragraphs_data:
            all_segments.extend(_segment_paragraph_row(p))

        seg_data = [s.model_dump() for s in all_segments]
        return {
            "book_id": book_id,
            "chapter_id": chapter_id,
            "segment_count": len(all_segments),
            "segments": seg_data,
        }

    @app.post("/api/projects/{book_id}/chapters/{chapter_id}/plan")
    async def plan_chapter(book_id: str, chapter_id: str):
        paragraphs_data = store.get_paragraphs(book_id, chapter_id)

        if not paragraphs_data:
            raise HTTPException(status_code=404, detail="Chapter not found")

        all_segments = []
        for p in paragraphs_data:
            all_segments.extend(_segment_paragraph_row(p))

        book_model = BookModel(store, book_id)
        planner_with_model = ReadingPlanner(llm=llm_gateway, book_model=book_model)
        plan = await planner_with_model.plan_chapter(all_segments, chapter_id)

        return {
            "book_id": book_id,
            "chapter_id": chapter_id,
            "plan_entries": len(plan),
            "plan": [p.model_dump() for p in plan],
        }

    @app.post("/api/projects/{book_id}/chapters/{chapter_id}/tts")
    async def tts_chapter(book_id: str, chapter_id: str):
        paragraphs_data = store.get_paragraphs(book_id, chapter_id)

        if not paragraphs_data:
            raise HTTPException(status_code=404, detail="Chapter not found")

        all_segments = []
        for p in paragraphs_data:
            all_segments.extend(_segment_paragraph_row(p))

        book_model = BookModel(store, book_id)
        planner_with_model = ReadingPlanner(llm=llm_gateway, book_model=book_model)
        plan = await planner_with_model.plan_chapter(all_segments, chapter_id)

        results = []
        for entry in plan:
            voice_id = voice_registry.get_fallback_voice("narrator")
            if entry.speaker_id != "char_narrator":
                vc = entry.voice_constraints
                if vc.gender_style:
                    role = f"{vc.gender_style}_dialogue"
                    voice_id = voice_registry.get_fallback_voice(role)

            tts_request = tts_composer.compose(
                segment_id=entry.segment_id,
                tts_base_text=entry.text,
                voice_id=voice_id,
                engine="edge_tts",
                reading_style=entry.reading_style.model_dump(),
                prosody_hint=entry.reading_style.prosody_hint,
            )

            result = await tts_gateway.synthesize(tts_request)
            results.append(result.model_dump() if hasattr(result, "model_dump") else vars(result))

        return {
            "book_id": book_id,
            "chapter_id": chapter_id,
            "results": results,
        }

    @app.post("/api/projects/{book_id}/chapters/{chapter_id}/package")
    async def package_chapter(book_id: str, chapter_id: str):
        manifest = ReaderPackageManifest(
            book_id=book_id,
            title=f"Chapter {chapter_id}",
            segmenter_version="zh_clause_v1",
        )
        pkg_dir = pkg_service.build_reader_package(
            output_dir=str(data_path / "packages" / book_id / chapter_id),
            manifest=manifest,
        )
        return {"book_id": book_id, "chapter_id": chapter_id, "package_dir": str(pkg_dir)}

    @app.get("/api/voices")
    async def list_voices(backend: str | None = None):
        return {"voices": voice_registry.list_voices(backend=backend)}

    @app.get("/api/projects/{book_id}/voice-assignments")
    async def list_voice_assignments(book_id: str, status: str | None = None):
        """Get voice assignments for a book, optionally filtered by status."""
        _require_book(book_id)
        assignments = store.list_voice_assignments(book_id, status=status)
        return {"book_id": book_id, "assignments": assignments}

    @app.post("/api/projects/{book_id}/voice-assignments/lock")
    async def lock_voice_assignment(book_id: str, req: VoiceAssignmentUpdate):
        """Lock a character's voice assignment via Harness Gate."""
        _require_book(book_id)
        result = harness.commit_voice_assignments(
            store=store,
            book_id=book_id,
            unit_id=req.character_id,
            assignments=[{
                "character_id": req.character_id,
                "voice_id": req.voice_id,
                "user_locked": True,
                "source": "user",
                "status": "user_locked",
            }],
        )
        if result.decision != "pass":
            raise HTTPException(
                status_code=409,
                detail=f"Voice assignment lock rejected: {result.reason}",
            )
        # Invalidate dependents of all chapter-level voice_assignment artifacts
        for ch in store.get_chapters(book_id):
            cid = ch["chapter_id"]
            old_va = store.get_active_artifact(book_id, "voice_assignment", cid)
            if old_va:
                store.invalidate_dependents(
                    book_id, old_va["artifact_version_id"], reason="voice_lock",
                )
        return {
            "book_id": book_id, "character_id": req.character_id,
            "locked": True, "status": "user_locked",
        }

    @app.post("/api/projects/{book_id}/voice-assignments/unlock")
    async def unlock_voice_assignment(book_id: str, req: UnlockVoiceRequest):
        """Unlock a character's voice assignment (sets status=confirmed)."""
        _require_book(book_id)
        character_id = req.character_id
        existing = store.get_voice_assignment(book_id, character_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Assignment not found")
        store.upsert_voice_assignment(
            book_id=book_id,
            character_id=character_id,
            voice_id=existing["voice_id"],
            user_locked=False,
            source="user",
            status="confirmed",
        )
        # Invalidate dependents of all chapter-level voice_assignment artifacts
        for ch in store.get_chapters(book_id):
            cid = ch["chapter_id"]
            old_va = store.get_active_artifact(book_id, "voice_assignment", cid)
            if old_va:
                store.invalidate_dependents(
                    book_id, old_va["artifact_version_id"], reason="voice_unlock",
                )
        return {
            "book_id": book_id, "character_id": character_id,
            "locked": False, "status": "confirmed",
        }

    @app.post("/api/projects/{book_id}/voice-assignments/recast-unlocked")
    async def recast_unlocked(book_id: str):
        """Re-cast all unlocked voice assignments. Locked assignments are untouched."""
        _require_book(book_id)
        updated = store.recast_unlocked_voice_assignments(
            book_id=book_id,
            cast_fn=lambda char_id, traits: _cast_single(char_id, traits),
        )
        # Invalidate dependents of voice_assignment for each affected chapter
        chapters = store.get_chapters(book_id)
        for ch in chapters:
            cid = ch["chapter_id"]
            old_va = store.get_active_artifact(book_id, "voice_assignment", cid)
            if old_va:
                store.invalidate_dependents(
                    book_id, old_va["artifact_version_id"],
                    reason="voice_recast",
                )
        return {"book_id": book_id, "updated_count": len(updated), "updated": updated}

    @app.post("/api/projects/{book_id}/chapters/{chapter_id}/cold-start")
    async def cold_start_chapter(book_id: str, chapter_id: str):
        """Cold start for an already-imported book: segment → scan → buffer."""
        _validate_path_component(book_id)
        ok, msg = _preflight_chapter_op(book_id, chapter_id)
        if not ok:
            raise HTTPException(status_code=409, detail=msg)
        from vn_core.pipeline.pipeline import Pipeline
        pipeline = Pipeline(
            store=store, output_dir=str(data_path), tts_engine="mock",
        )
        csr = await pipeline.cold_start_existing(book_id=book_id, chapter_id=chapter_id)
        return {
            "book_id": csr.book_id, "phase": csr.phase,
            "segments_count": csr.segments_count,
            "buffer_segments_count": csr.buffer_segments_count,
            "playable": csr.playable,
            "buffer_package_dir": csr.buffer_package_dir,
            "render_window_id": csr.render_window_id,
            "full_bake_job_id": csr.full_bake_job_id,
            "errors": csr.errors,
        }

    @app.get("/api/projects/{book_id}/chapters/{chapter_id}/render-windows")
    async def list_render_windows(book_id: str, chapter_id: str):
        """List RenderWindow-shaped window_package artifacts."""
        _require_book(book_id)
        rows = store.list_artifact_versions(book_id, "window_package", chapter_id)
        windows = []
        for art in rows:
            meta = {}
            try:
                meta = json.loads(art.get("metadata", "{}"))
            except (TypeError, json.JSONDecodeError):
                pass
            windows.append({
                "window_id": meta.get("window_id", ""),
                "book_id": book_id,
                "chapter_id": chapter_id,
                "status": meta.get("status", art.get("status", "")),
                "package_dir": meta.get("package_dir", art.get("file_path", "")),
                "segment_ids": meta.get("segment_ids", []),
                "target_count": meta.get("target_count", 0),
                "audio_manifest_path": meta.get("audio_manifest_path", ""),
                "timing_path": meta.get("timing_path", ""),
                "artifact_version_id": art["artifact_version_id"],
            })
        return {"book_id": book_id, "chapter_id": chapter_id, "windows": windows}

    def _package_files_exist(pkg_dir: str, pkg_type: str = "full") -> bool:
        """Check that the expected package files exist on disk."""
        if not pkg_dir:
            return False
        d = Path(pkg_dir)
        required = ["cleaned.html", "timing.json", "manifest.json"]
        if not all((d / f).exists() for f in required):
            return False
        adir = d / "audio"
        if not adir.exists() or not any(adir.glob("*.wav")) and not any(adir.glob("*.mp3")):
            return False
        return True

    def _package_is_valid(book_id: str, pkg: dict, pkg_type: str = "full") -> bool:
        """Check artifact is active, deps active, AND package files exist on disk."""
        if not pkg or pkg.get("status") != "active":
            return False
        vid = pkg["artifact_version_id"]
        dep_ok = store.check_dependencies_active(book_id, vid)
        if not dep_ok["all_active"]:
            return False
        return _package_files_exist(pkg.get("file_path", ""), pkg_type)

    def _get_package_dir(book_id: str, chapter_id: str) -> tuple[str, str, str]:
        """Return (package_dir, kind, artifact_version_id) for best valid package.

        Only returns usable packages (deps active + files exist on disk).
        Prefers full reader_package over buffer. Returns 404 if nothing valid.
        """
        pkg = store.get_active_artifact(book_id, "reader_package", chapter_id)
        if pkg and _package_is_valid(book_id, pkg, "full"):
            return pkg.get("file_path", ""), "full", pkg["artifact_version_id"]
        win = store.get_active_artifact(book_id, "window_package", chapter_id)
        if win and _package_is_valid(book_id, win, "buffer"):
            return win.get("file_path", ""), "buffer", win["artifact_version_id"]
        raise HTTPException(
            status_code=404,
            detail="No usable buffer or package found",
        )

    @app.get("/api/projects/{book_id}/chapters/{chapter_id}/buffer")
    async def get_buffer(book_id: str, chapter_id: str):
        """Return the current playable buffer (or full) package info with URLs."""
        _require_book(book_id)
        pkg_dir, kind, vid = _get_package_dir(book_id, chapter_id)
        base = f"/api/projects/{book_id}/chapters/{chapter_id}/buffer"
        return {
            "book_id": book_id, "chapter_id": chapter_id,
            "status": f"{kind}_ready",
            "package_kind": kind,
            "package_dir": pkg_dir,
            "artifact_version_id": vid,
            "content_url": f"{base}/content",
            "audio_url": f"{base}/audio",
            "timing_url": f"{base}/timing",
            "manifest_url": f"{base}/manifest",
        }

    @app.get("/api/projects/{book_id}/chapters/{chapter_id}/buffer/content")
    async def get_buffer_content(book_id: str, chapter_id: str):
        _require_book(book_id)
        pkg_dir, _, _ = _get_package_dir(book_id, chapter_id)
        html = Path(pkg_dir) / "cleaned.html"
        if not html.exists():
            raise HTTPException(status_code=404, detail="cleaned.html not found")
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html.read_text(encoding="utf-8"))

    @app.get("/api/projects/{book_id}/chapters/{chapter_id}/buffer/timing")
    async def get_buffer_timing(book_id: str, chapter_id: str):
        _require_book(book_id)
        pkg_dir, _, _ = _get_package_dir(book_id, chapter_id)
        tf = Path(pkg_dir) / "timing.json"
        if not tf.exists():
            raise HTTPException(status_code=404, detail="timing.json not found")
        return json.loads(tf.read_text(encoding="utf-8"))

    @app.get("/api/projects/{book_id}/chapters/{chapter_id}/buffer/manifest")
    async def get_buffer_manifest(book_id: str, chapter_id: str):
        _require_book(book_id)
        pkg_dir, _, _ = _get_package_dir(book_id, chapter_id)
        mf = Path(pkg_dir) / "manifest.json"
        if not mf.exists():
            raise HTTPException(status_code=404, detail="manifest.json not found")
        return json.loads(mf.read_text(encoding="utf-8"))

    @app.get("/api/projects/{book_id}/chapters/{chapter_id}/buffer/audio")
    async def get_buffer_audio(book_id: str, chapter_id: str):
        from fastapi.responses import FileResponse

        _require_book(book_id)
        pkg_dir, _, _ = _get_package_dir(book_id, chapter_id)
        adir = Path(pkg_dir) / "audio"
        if adir.exists():
            for pattern in ("*.wav", "*.mp3"):
                files = list(adir.glob(pattern))
                if files:
                    mt = "audio/wav" if files[0].suffix == ".wav" else "audio/mpeg"
                    return FileResponse(files[0], media_type=mt)
        raise HTTPException(status_code=404, detail="Audio not found")

    def _cast_single(char_id: str, traits: list[str]) -> tuple[str, float]:
        """Simple scorer for recast."""
        from vn_core.voice.casting import cast_voice as _cast_one
        va = _cast_one(char_id, traits, voice_registry)
        return va.voice_id, va.confidence

    @app.get("/api/projects/{book_id}/chapters/{chapter_id}/adaptation-ops")
    async def list_adaptation_ops(
        book_id: str, chapter_id: str, segment_id: str = "",
    ):
        """List text adaptation operations for a chapter."""
        _require_book(book_id)
        ops = store.get_text_adaptation_ops(
            book_id, unit_id=chapter_id, segment_id=segment_id or "",
        )
        return {"book_id": book_id, "chapter_id": chapter_id, "ops": ops}

    @app.post("/api/projects/{book_id}/chapters/{chapter_id}/adaptation-ops/replay")
    async def replay_adaptation_ops_ep(
        book_id: str, chapter_id: str, req: ReplayRequest,
    ):
        """Replay adaptation ops on source text."""
        _require_book(book_id)
        from vn_core.adaptation import replay_adaptation_ops as _replay
        text, warnings = _replay(req.source_text, req.ops, scope=req.scope)
        return {"text": text, "warnings": warnings}

    @app.post("/api/projects/{book_id}/chapters/{chapter_id}/adaptation-ops/diff")
    async def diff_adaptation_ops_ep(
        book_id: str, chapter_id: str, req: DiffRequest,
    ):
        """Compute diff between two text strings."""
        _require_book(book_id)
        from vn_core.adaptation import diff_text
        return diff_text(req.before, req.after)

    @app.post("/api/projects/{book_id}/chapters/{chapter_id}/adaptation-ops/rollback")
    async def rollback_adaptation_ops_ep(
        book_id: str, chapter_id: str, req: RollbackRequest,
    ):
        """Rollback specified adaptation ops by creating new artifact version."""
        _require_book(book_id)
        from vn_core.adaptation import rollback_adaptation_ops as _rollback
        from vn_core.contracts.stage_result import StageResult

        decision_rows = store.get_text_adaptation_ops(book_id, unit_id=chapter_id)
        if not decision_rows:
            raise HTTPException(status_code=404, detail="No adaptation ops found")

        # Unwrap decision rows into raw ops.
        # Each decision row has: value = raw op dict, decision_type = "text_adaptation:{op_id}"
        raw_ops: list[dict] = []
        warnings: list[str] = []
        for row in decision_rows:
            raw = row.get("value", {})
            if not isinstance(raw, dict):
                warnings.append(f"malformed op in decision {row.get('segment_id', '?')}")
                continue
            # Ensure op_id is present — extract from decision_type if missing
            if "op_id" not in raw:
                dt = row.get("decision_type", "")
                if dt.startswith("text_adaptation:"):
                    raw["op_id"] = dt[len("text_adaptation:"):]
            if not raw.get("op_id"):
                warnings.append(
                    f"op missing op_id in decision for segment {row.get('segment_id', '?')}",
                )
                continue
            if "original" not in raw or "normalized" not in raw:
                warnings.append(f"op {raw.get('op_id')} missing original/normalized")
                continue
            raw_ops.append(raw)

        if not raw_ops:
            raise HTTPException(
                status_code=422,
                detail=f"No valid ops to rollback. Warnings: {warnings}",
            )

        # Reconstruct approximate source text by finding the earliest original
        source_text = raw_ops[0].get("original", "")
        new_ops, result_text = _rollback(
            source_text, raw_ops, set(req.op_ids), req.reason,
        )

        # Compute next version and commit via Harness
        conn = store._get_conn()
        row = conn.execute(
            """SELECT COUNT(*) FROM artifacts
            WHERE book_id=? AND artifact_type=? AND unit_id=?""",
            (book_id, "adaptation_ops", chapter_id),
        ).fetchone()
        counter = (row[0] + 1) if row else 1
        ops_ver = f"{book_id}_adaptation_ops_{chapter_id}_v{counter:03d}"
        ops_input_hash = hashlib.sha256(
            json.dumps(new_ops, ensure_ascii=False).encode(),
        ).hexdigest()[:40]

        stage_result = StageResult(
            stage="adaptation_rollback",
            book_id=book_id,
            unit_id=chapter_id,
            proposed_artifacts=[{
                "artifact_type": "adaptation_ops",
                "artifact_version_id": ops_ver,
                "unit_id": chapter_id,
                "data": new_ops,  # raw ops, written to file by commit_stage_result
                "input_hash": ops_input_hash,
                "metadata": {
                    "rolled_back_op_ids": list(req.op_ids),
                    "rollback_reason": req.reason,
                    "source_op_count": len(raw_ops),
                    "op_count": len(new_ops),
                },
            }],
            decisions=[
                {
                    "segment_id": op.get("segment_id", chapter_id),
                    "decision_type": f"text_adaptation:{op.get('op_id', '')}",
                    "value": op,
                    "confidence": op.get("confidence", 0.99),
                    "source": "rollback",
                    "evidence": [f"rollback: {req.reason}"],
                }
                for op in new_ops
                if op.get("segment_id") and op.get("op_id")
            ],
            provenance={
                "stage": "adaptation_rollback",
                "unit_id": chapter_id,
                "artifact_version_id": ops_ver,
            },
        )
        # Capture old adaptation_ops BEFORE commit — commit_stage_result will
        # supersede it and activate the new one.
        old_adapt = store.get_active_artifact(
            book_id, "adaptation_ops", chapter_id,
        )
        csr = harness.commit_stage_result(store, stage_result)
        if csr.decision != "pass":
            raise HTTPException(
                status_code=409,
                detail=f"Rollback rejected: {csr.reason}",
            )
        # Invalidate dependents of the OLD adaptation_ops that downstream
        # artifacts actually reference (not the new ops_ver).
        if old_adapt and old_adapt["artifact_version_id"] != ops_ver:
            store.invalidate_dependents(
                book_id, old_adapt["artifact_version_id"],
                reason="adaptation_rollback",
            )
        return {
            "book_id": book_id,
            "chapter_id": chapter_id,
            "artifact_version_id": ops_ver,
            "rolled_back_op_ids": list(req.op_ids),
            "new_op_count": len(new_ops),
            "warnings": warnings,
        }

    @app.post("/api/jobs")
    async def submit_job(req: JobSubmitRequest):
        config = _resolve_generation_config(
            req.book_id,
            req.generation_config_id,
            req.reading_profile,
        )
        from vn_core.orchestration.cache_keys import reader_package_cache_key
        cache_key = reader_package_cache_key(
            book_id=req.book_id,
            chapter_id=req.chapter_id,
            generation_config_id=config.generation_config_id,
            reading_profile=config.reading_profile,
            execution_mode=config.execution_mode,
            tts_engine=config.tts_engine,
            cache_buster=config.cache_buster,
        )
        job = JobState(
            job_id=f"job_{uuid.uuid4().hex[:12]}",
            book_id=req.book_id,
            stage=JobStage(req.stage),
            unit_id=req.chapter_id,
            status=JobStatus.pending,
            priority=req.priority,
            generation_config_id=config.generation_config_id,
            execution_mode=config.execution_mode,
            cache_key=cache_key,
            output_artifact_type="reader_package",
        )
        job_id = orchestrator.enqueue(job)
        await _broadcast_to_all("job_enqueued", {
            "job_id": job_id,
            "stage": req.stage,
            "book_id": req.book_id,
            "chapter_id": req.chapter_id,
        })
        return {
            "job_id": job_id,
            "status": "pending",
            "queue_depth": orchestrator.pending_count(),
            "running": orchestrator.running_count(),
        }

    @app.post("/api/bake")
    async def bake_chapter(req: BakeChapterRequest):
        ok, msg = _preflight_chapter_op(
            req.book_id, req.chapter_id, req.generation_config_id,
        )
        if not ok:
            raise HTTPException(status_code=409, detail=msg)
        config = _resolve_generation_config(
            req.book_id,
            req.generation_config_id,
            req.reading_profile,
        )
        pipeline = Pipeline(
            store=store,
            llm=llm_gateway,
            gateway=tts_gateway,
            output_dir=str(data_path),
            tts_engine=config.tts_engine,
            generation_config_id=config.generation_config_id,
            reading_profile=config.reading_profile,
        )
        result = await pipeline.bake_chapter(req.book_id, req.chapter_id)
        return {
            "book_id": result.book_id,
            "chapter_id": result.chapter_id,
            "success": result.success,
            "generation_config_id": result.generation_config_id,
            "reading_profile": result.reading_profile,
            "package_dir": result.package_dir,
            "segment_count": len(result.segments),
            "timing_count": len(result.timing),
            "errors": result.errors,
        }

    @app.get("/api/jobs")
    async def list_jobs(book_id: str = "", status: str = "", limit: int = 50):
        return {
            "jobs": store.list_jobs(book_id=book_id, status=status, limit=limit),
        }

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str):
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return dict(job)

    @app.post("/api/jobs/{job_id}/retry")
    async def retry_job(job_id: str):
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["status"] in ("pending", "running"):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot retry job in status '{job['status']}'",
            )
        store.requeue_job(job_id)
        return {"job_id": job_id, "status": "pending", "ok": True}

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        status = job["status"]
        if status in ("done",):
            return {"job_id": job_id, "status": status, "ok": True}
        if status == "pending":
            store.fail_job(job_id, "cancelled by user")
        elif status == "running":
            orchestrator.cancel_job(job_id)
        else:
            store.fail_job(job_id, "cancelled by user")
        return {
            "job_id": job_id, "status": "failed",
            "cancelled": True, "ok": True,
        }

    @app.post("/api/projects/{book_id}/chapters/{chapter_id}/rebuild")
    async def rebuild_chapter(book_id: str, chapter_id: str):
        """Submit a full rebuild job for a chapter. Deduplicates pending jobs."""
        _validate_path_component(book_id)
        ok, msg = _preflight_chapter_op(book_id, chapter_id)
        if not ok:
            raise HTTPException(status_code=409, detail=msg)
        from vn_core.contracts.job_state import JobStage, JobState, JobStatus
        from vn_core.orchestration.cache_keys import reader_package_cache_key

        # Dedup: only dedup against other rebuild jobs (same chapter)
        existing = store.find_duplicate_job(
            book_id, "tts_render", chapter_id,
            cache_buster_prefix="rebuild:",
        )
        if existing:
            return {
                "job_id": existing["job_id"], "status": existing["status"],
                "duplicate": True,
            }

        config = store.get_generation_config(book_id)
        ck = reader_package_cache_key(
            book_id=book_id, chapter_id=chapter_id,
            generation_config_id=config.generation_config_id,
            reading_profile=config.reading_profile,
            execution_mode=config.execution_mode,
            tts_engine=config.tts_engine,
        )
        job = JobState(
            job_id=f"job_rebuild_{book_id}_{chapter_id}_{uuid.uuid4().hex[:6]}",
            book_id=book_id, stage=JobStage.tts_render,
            unit_id=chapter_id, status=JobStatus.pending,
            priority="P0",  # user-triggered = highest
            generation_config_id=config.generation_config_id,
            execution_mode=config.execution_mode,
            cache_key=ck,
            cache_buster=f"rebuild:{uuid.uuid4().hex[:8]}",
            output_artifact_type="reader_package",
        )
        jid = orchestrator.enqueue(job)
        await _broadcast_to_all("job_enqueued", {
            "job_id": jid, "book_id": book_id, "chapter_id": chapter_id,
        })
        return {"job_id": jid, "status": "pending", "duplicate": False}

    @app.get("/api/orchestrator/stats")
    async def orchestrator_stats():
        return orchestrator.get_stats()

    def _load_timing_entries(pkg_dir: Path) -> list:
        """Load and validate timing.json, returning list of TimingEntry.

        Raises HTTPException(409) when timing.json is missing,
        HTTPException(422) on bad JSON or schema mismatch.
        """
        _export_err = HTTPException
        timing_path = pkg_dir / "timing.json"
        if not timing_path.exists():
            raise _export_err(
                status_code=409,
                detail="timing.json not found in reader_package",
            )
        try:
            timing_data = json.loads(timing_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise _export_err(
                status_code=422,
                detail=f"timing.json is not valid JSON: {e}",
            )
        if not isinstance(timing_data, list):
            raise _export_err(
                status_code=422,
                detail="timing.json must be a JSON array",
            )
        try:
            return [TimingEntry(**t) for t in timing_data]
        except Exception as e:
            raise _export_err(
                status_code=422,
                detail=f"timing.json entry validation failed: {e}",
            )

    def _export_write_exception(
        book_id: str, chapter_id: str, fmt: str, message: str,
    ) -> None:
        """Write export exception to store. Best-effort, errors logged not raised."""
        try:
            store.write_exception(
                book_id=book_id,
                exception_type="export_failure",
                message=message,
                unit_id=chapter_id,
                stage=f"export_{fmt}",
                severity="high",
            )
        except Exception:
            pass

    def _export_package_preflight(
        book_id: str, pkg: dict,
    ) -> tuple[bool, str]:
        """Validate reader_package for export (artifact, deps, files except timing).

        timing.json is validated separately by _load_timing_entries so missing /
        corrupt timing gets its own diagnostic.
        """
        if not pkg or pkg.get("status") != "active":
            return False, "Reader package not active"
        vid = pkg["artifact_version_id"]
        dep_ok = store.check_dependencies_active(book_id, vid)
        if not dep_ok["all_active"]:
            return False, "Reader package dependencies not active"
        pkg_dir = pkg.get("file_path", "")
        if not pkg_dir:
            return False, "Reader package has no file_path"
        d = Path(pkg_dir)
        if not (d / "cleaned.html").exists():
            return False, "cleaned.html not found in reader_package"
        if not (d / "manifest.json").exists():
            return False, "manifest.json not found in reader_package"
        adir = d / "audio"
        if not adir.exists() or (
            not any(adir.glob("*.wav")) and not any(adir.glob("*.mp3"))
        ):
            return False, "audio files not found in reader_package"
        return True, "ok"

    _EXPORT_ARTIFACT_TYPES = frozenset({
        "export_daw", "export_audiobookshelf", "export_m4b",
    })

    def _validate_export_format(fmt: str) -> str:
        if fmt not in ("daw", "audiobookshelf", "m4b"):
            raise HTTPException(status_code=400, detail=f"Unknown format: {fmt}")
        return fmt

    @app.post("/api/projects/{book_id}/chapters/{chapter_id}/exports")
    async def export_chapter(
        book_id: str, chapter_id: str, format: str = "daw",
    ):
        """Export a chapter's reader_package in the requested format."""
        import shutil as _shutil

        _require_book(book_id)
        _validate_path_component(chapter_id)
        fmt = _validate_export_format(format)

        # Preflight: validate reader_package (except timing.json)
        pkg = store.get_active_artifact(book_id, "reader_package", chapter_id)
        ok, pkg_msg = _export_package_preflight(book_id, pkg)
        if not ok:
            _export_write_exception(book_id, chapter_id, fmt, pkg_msg)
            raise HTTPException(status_code=409, detail=pkg_msg)

        pkg_dir = Path(pkg.get("file_path", ""))

        # Load and validate timing
        try:
            timing_entries = _load_timing_entries(pkg_dir)
        except HTTPException as he:
            _export_write_exception(book_id, chapter_id, fmt, he.detail)
            raise
        except Exception as e:
            msg = f"Failed to load timing.json: {e}"
            _export_write_exception(book_id, chapter_id, fmt, msg)
            raise HTTPException(status_code=422, detail=msg)

        # Generate export into a temp directory, then atomically rename on success
        export_root = data_path / "exports" / book_id / chapter_id
        export_root.mkdir(parents=True, exist_ok=True)
        tmp_id = uuid.uuid4().hex[:8]
        tmp_dir = export_root / f".tmp_{fmt}_{tmp_id}"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        try:
            if fmt == "daw":
                from vn_core.export.daw import export_daw_package
                audio_files = list((pkg_dir / "audio").glob("*"))
                gen_path = export_daw_package(
                    output_dir=tmp_dir, book_id=book_id,
                    title=chapter_id, timing=timing_entries,
                    audio_files=audio_files,
                )
            elif fmt == "audiobookshelf":
                from vn_core.export.audiobookshelf import export_audiobookshelf
                audio_files = list((pkg_dir / "audio").glob("*"))
                gen_path = export_audiobookshelf(
                    output_dir=tmp_dir, book_id=book_id,
                    title=chapter_id, timing=timing_entries,
                    audio_files=audio_files,
                )
            else:  # m4b
                from vn_core.export.m4b import export_m4b
                gen_path = export_m4b(
                    output_dir=tmp_dir, book_id=book_id,
                    title=chapter_id, timing=timing_entries,
                )
        except Exception as e:
            _shutil.rmtree(str(tmp_dir), ignore_errors=True)
            msg = f"Export generation failed: {e}"
            _export_write_exception(book_id, chapter_id, fmt, msg)
            raise HTTPException(status_code=422, detail=msg)

        # Build version info for final path + artifact
        atype = f"export_{fmt}"
        conn = store._get_conn()
        counter = conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE book_id=? AND artifact_type=? AND unit_id=?",
            (book_id, atype, chapter_id),
        ).fetchone()[0]
        export_ver = f"{book_id}_{atype}_{chapter_id}_v{counter + 1:03d}"
        final_path = export_root / export_ver

        # Move generated output from tmp to final stable path
        try:
            resolved_gen = gen_path.resolve()
            if resolved_gen == tmp_dir.resolve():
                # m4b writes directly into tmp_dir → rename tmp_dir itself
                _shutil.move(str(tmp_dir), str(final_path))
            else:
                # daw / audiobookshelf write a subdir → move that subdir
                _shutil.move(str(gen_path), str(final_path))
                _shutil.rmtree(str(tmp_dir), ignore_errors=True)
        except Exception as e:
            _shutil.rmtree(str(tmp_dir), ignore_errors=True)
            msg = f"Export atomic rename failed: {e}"
            _export_write_exception(book_id, chapter_id, fmt, msg)
            raise HTTPException(status_code=422, detail=msg)

        # Atomic commit via StageResult + Harness
        from vn_core.contracts.stage_result import StageResult
        stage_result = StageResult(
            stage=f"export_{fmt}",
            book_id=book_id,
            unit_id=chapter_id,
            proposed_artifacts=[{
                "artifact_type": atype,
                "artifact_version_id": export_ver,
                "unit_id": chapter_id,
                "file_path": str(final_path),
            }],
            dependencies=[
                (export_ver, pkg["artifact_version_id"], "reader_package"),
            ],
            provenance={
                "stage": f"export_{fmt}",
                "unit_id": chapter_id,
                "artifact_version_id": export_ver,
            },
        )
        csr = harness.commit_stage_result(store, stage_result)
        if csr.decision != "pass":
            _shutil.rmtree(str(final_path), ignore_errors=True)
            msg = f"Export commit rejected: {csr.reason}"
            _export_write_exception(book_id, chapter_id, fmt, msg)
            raise HTTPException(status_code=409, detail=msg)
        return {
            "book_id": book_id, "chapter_id": chapter_id,
            "format": fmt, "artifact_version_id": export_ver,
            "output_dir": str(final_path),
        }

    # --- Export browse / download / list ---

    @app.get("/api/projects/{book_id}/exports")
    async def list_exports(
        book_id: str,
        chapter_id: str = "",
        format: str = "",
        status: str = "active,invalidated",
    ):
        """List export artifacts with optional filters.

        Query params:
        - chapter_id: filter by unit_id
        - format: daw | audiobookshelf | m4b
        - status: comma-separated, default 'active,invalidated'
        """
        _require_book(book_id)
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if format and format not in ("daw", "audiobookshelf", "m4b"):
            return {"book_id": book_id, "exports": []}

        atypes = (
            [f"export_{format}"] if format
            else ["export_daw", "export_audiobookshelf", "export_m4b"]
        )
        _KEYS = (
            "artifact_version_id", "artifact_type", "unit_id",
            "status", "file_path", "created_at", "invalidated_reason",
        )

        def _build_export_entry(art: dict) -> dict:
            """Extract invalidated_reason and return stable-field entry."""
            deps = store.get_artifact_dependencies(
                book_id, art["artifact_version_id"],
            )
            pkg_vids = [
                d["depends_on_artifact_version_id"] for d in deps
                if d.get("dependency_role") == "reader_package"
            ]
            invalidated_reason = ""
            try:
                meta = json.loads(art.get("metadata", "{}"))
            except (TypeError, json.JSONDecodeError):
                meta = {}
            if art.get("status") == "invalidated":
                invalidated_reason = meta.get("invalidated_reason", "")
            elif pkg_vids:
                conn = store._get_conn()
                pkg_row = conn.execute(
                    "SELECT status, metadata FROM artifacts"
                    " WHERE book_id=? AND artifact_version_id=?",
                    (book_id, pkg_vids[0]),
                ).fetchone()
                if pkg_row and pkg_row[0] == "invalidated":
                    try:
                        pkg_meta = json.loads(pkg_row[1] or "{}")
                    except (TypeError, json.JSONDecodeError):
                        pkg_meta = {}
                    invalidated_reason = (
                        meta.get("invalidated_reason", "")
                        or pkg_meta.get("invalidated_reason", "")
                        or "source invalidated"
                    )
            entry = {k: art.get(k, "") for k in _KEYS if k != "invalidated_reason"}
            entry["invalidated_reason"] = invalidated_reason
            return entry

        results: list[dict] = []
        for atype in atypes:
            arts = store.list_artifact_versions(book_id, atype,
                                                unit_id=chapter_id or None)
            for art in arts:
                if statuses and art.get("status", "") not in statuses:
                    continue
                results.append(_build_export_entry(art))

        # Stable sort: created_at DESC, then artifact_version_id DESC
        results.sort(key=lambda e: (
            e.get("created_at") or "",
            e.get("artifact_version_id") or "",
        ), reverse=True)
        return {"book_id": book_id, "exports": results}

    def _export_path_allowed(book_id: str, raw_path: str) -> bool:
        """Return True if *raw_path* resolves under data/exports/{book_id}."""
        if not raw_path:
            return False
        try:
            resolved = Path(raw_path).resolve()
            allowed = (data_path / "exports" / book_id).resolve()
            resolved.relative_to(allowed)
            return True
        except (ValueError, OSError):
            return False

    @app.get("/api/projects/{book_id}/exports/{artifact_version_id}")
    async def get_export_artifact(book_id: str, artifact_version_id: str):
        """Get metadata for a single export artifact."""
        _require_book(book_id)
        conn = store._get_conn()
        row = conn.execute(
            "SELECT * FROM artifacts WHERE book_id=? AND artifact_version_id=?",
            (book_id, artifact_version_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Export artifact not found")
        art = dict(row)
        if art.get("artifact_type", "") not in _EXPORT_ARTIFACT_TYPES:
            raise HTTPException(status_code=404, detail="Export artifact not found")
        deps = store.get_artifact_dependencies(book_id, artifact_version_id)
        dep_check = store.check_dependencies_active(book_id, artifact_version_id)
        raw_path = art.get("file_path", "")
        return {
            "artifact": art,
            "dependencies": deps,
            "all_deps_active": dep_check["all_active"],
            "inactive_deps": dep_check["inactive"],
            "downloadable": (
                art.get("status") == "active"
                and dep_check["all_active"]
                and bool(raw_path)
                and Path(raw_path).exists()
                and _export_path_allowed(book_id, raw_path)
            ),
        }

    @app.get("/api/projects/{book_id}/exports/{artifact_version_id}/download")
    async def download_export_artifact(
        book_id: str, artifact_version_id: str,
        include_inactive: bool = False,
        background_tasks: BackgroundTasks = BackgroundTasks(),
    ):
        """Download an export artifact. ZIP for directories, raw for files.

        Only active artifacts with active deps are downloadable by default.
        Pass include_inactive=true to allow download of invalidated exports.
        """
        import zipfile as _zipfile

        _require_book(book_id)
        conn = store._get_conn()
        row = conn.execute(
            "SELECT * FROM artifacts WHERE book_id=? AND artifact_version_id=?",
            (book_id, artifact_version_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Export artifact not found")
        art = dict(row)

        # Reject non-export artifact types
        if art.get("artifact_type", "") not in _EXPORT_ARTIFACT_TYPES:
            raise HTTPException(status_code=404, detail="Export artifact not found")

        if not include_inactive:
            if art.get("status") != "active":
                raise HTTPException(
                    status_code=409,
                    detail=f"Artifact is {art.get('status')}, not downloadable",
                )
            dep_check = store.check_dependencies_active(
                book_id, artifact_version_id,
            )
            if not dep_check["all_active"]:
                raise HTTPException(
                    status_code=409,
                    detail="Artifact dependencies are not all active",
                )

        raw_path = art.get("file_path", "")
        if not raw_path:
            raise HTTPException(status_code=404, detail="Export file not found on disk")

        if not _export_path_allowed(book_id, raw_path):
            raise HTTPException(
                status_code=409, detail="Export path is outside allowed directory",
            )

        file_path = Path(raw_path).resolve()

        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Export file not found on disk")

        if file_path.is_dir():
            tmp_zip = Path(data_path) / ".tmp_downloads" / f"{uuid.uuid4().hex}.zip"
            tmp_zip.parent.mkdir(parents=True, exist_ok=True)
            try:
                with _zipfile.ZipFile(str(tmp_zip), "w", _zipfile.ZIP_DEFLATED) as zf:
                    for f in file_path.rglob("*"):
                        if f.is_file():
                            zf.write(str(f), str(f.relative_to(file_path)))
            except Exception:
                try:
                    tmp_zip.unlink(missing_ok=True)
                except Exception:
                    pass
                raise HTTPException(
                    status_code=500, detail="Failed to create ZIP archive",
                )
            from fastapi.responses import FileResponse

            safe_name = artifact_version_id.replace("/", "_").replace("\\", "_")
            background_tasks.add_task(lambda: tmp_zip.unlink(missing_ok=True))
            return FileResponse(
                str(tmp_zip),
                media_type="application/zip",
                filename=f"{safe_name}.zip",
            )
        else:
            from fastapi.responses import FileResponse
            mt = "application/octet-stream"
            if file_path.suffix == ".json":
                mt = "application/json"
            elif file_path.suffix == ".txt":
                mt = "text/plain"
            return FileResponse(str(file_path), media_type=mt,
                               filename=file_path.name)

    @app.get("/api/projects/{book_id}/station")
    async def get_station(book_id: str):
        """Aggregated station view: chapters, buffers, packages, jobs, exceptions."""
        _require_book(book_id)
        chapters_data = []

        def _job_kind(job: dict) -> str:
            cache_buster = str(job.get("cache_buster") or "")
            job_id = str(job.get("job_id") or "")
            if cache_buster.startswith("rebuild:") or job_id.startswith("job_rebuild_"):
                return "rebuild"
            if cache_buster.startswith("prefetch:") or job_id.startswith("job_prefetch_"):
                return "prefetch"
            return "bake"

        for ch in store.get_chapters(book_id):
            cid = ch["chapter_id"]
            buf_win = store.get_current_artifact(book_id, "window_package", cid)
            full_pkg = store.get_current_artifact(book_id, "reader_package", cid)

            buf_info = {"status": "missing"}
            if buf_win:
                buf_valid = _package_is_valid(book_id, buf_win, "buffer")
                meta = {}
                try:
                    meta = json.loads(buf_win.get("metadata", "{}"))
                except (TypeError, json.JSONDecodeError):
                    pass
                buf_info = {
                    "status": "ready" if buf_valid else "invalid",
                    "artifact_version_id": buf_win["artifact_version_id"],
                    "package_dir": buf_win.get("file_path", ""),
                    "dependency_ok": store.check_dependencies_active(
                        book_id, buf_win["artifact_version_id"],
                    )["all_active"],
                    "window_id": meta.get("window_id", ""),
                }

            full_info = {"status": "missing"}
            if full_pkg:
                full_valid = _package_is_valid(book_id, full_pkg, "full")
                full_info = {
                    "status": "ready" if full_valid else "invalid",
                    "artifact_version_id": full_pkg["artifact_version_id"],
                    "package_dir": full_pkg.get("file_path", ""),
                    "dependency_ok": store.check_dependencies_active(
                        book_id, full_pkg["artifact_version_id"],
                    )["all_active"],
                }

            chap_exceptions = store.list_exceptions(
                book_id=book_id, status="open", unit_id=cid,
            )
            needs_rebuild = store.chapter_needs_rebuild(book_id, cid)

            # Distinguish stale (artifact invalidated by user action) from invalid.
            # get_current_artifact returns most recent active or invalidated.
            if buf_win and buf_win.get("status") == "invalidated":
                buf_info["status"] = "stale"
                buf_info["dependency_ok"] = False
            if full_pkg and full_pkg.get("status") == "invalidated":
                full_info["status"] = "stale"
                full_info["dependency_ok"] = False

            jobs = store.list_jobs(book_id=book_id, unit_id=cid)[:10]
            for job in jobs:
                job["job_kind"] = _job_kind(job)

            chapters_data.append({
                "chapter_id": cid,
                "title": ch.get("title", ""),
                "buffer": buf_info,
                "full_package": full_info,
                "jobs": jobs,
                "exceptions": chap_exceptions,
                "progress": {
                    "playable": buf_info["status"] == "ready" or full_info["status"] == "ready",
                    "full_ready": full_info["status"] == "ready",
                    "has_open_exceptions": len(chap_exceptions) > 0,
                    "needs_rebuild": needs_rebuild,
                },
                "invalidated_artifacts": store.list_invalidated_artifacts(
                    book_id, unit_id=cid,
                ),
            })

        stats = store.get_job_stats(book_id)
        return {
            "book_id": book_id,
            "chapters": chapters_data,
            "queue": {
                "pending": stats.get("pending", 0),
                "running": stats.get("running", 0),
                "failed": stats.get("failed", 0),
                "done": stats.get("done", 0),
            },
        }

    @app.get("/api/exceptions")
    async def list_exceptions(
        book_id: str = "",
        status: str = "",
        exception_type: str = "",
        unit_id: str = "",
        limit: int = 100,
    ):
        """Query the exception queue with optional filters."""
        return {
            "exceptions": store.list_exceptions(
                book_id=book_id, status=status,
                exception_type=exception_type, unit_id=unit_id, limit=limit,
            ),
        }

    @app.post("/api/exceptions/{exception_id}/resolve")
    async def resolve_exception(exception_id: str):
        """Mark an exception as user-resolved. Returns 404 if not found."""
        exc = store.get_exception(exception_id)
        if not exc:
            raise HTTPException(
                status_code=404,
                detail=f"Exception not found: {exception_id}",
            )
        store.update_exception_status(exception_id, "user_resolved")
        return {"exception_id": exception_id, "status": "user_resolved"}

    @app.post("/api/projects/{book_id}/prefetch")
    async def schedule_prefetch(
        book_id: str,
        req: PrefetchRequest | None = None,
        current_chapter_id: str | None = None,
        generation_config_id: str | None = None,
    ):
        """Schedule prefetch jobs for chapters after the current one.

        Called by the reader when playback reaches a new chapter to ensure
        upcoming chapters are pre-rendered.
        """
        _require_book(book_id)
        req = req or PrefetchRequest()
        current_chapter_id = current_chapter_id or req.current_chapter_id
        generation_config_id = generation_config_id or req.generation_config_id
        _validate_path_component(current_chapter_id)
        _validate_path_component(generation_config_id)

        chapters = store.get_chapters(book_id)
        all_chapter_ids = [c["chapter_id"] for c in chapters]

        config = store.get_generation_config(book_id, generation_config_id)
        prefetch_ids = orchestrator.compute_prefetch_plan(current_chapter_id, all_chapter_ids)
        hot_before, hot_after = orchestrator.get_hot_window(current_chapter_id, all_chapter_ids)

        enqueued = []
        for ch_id in prefetch_ids:
            # Skip if valid full package already exists
            pkg = store.get_active_artifact(book_id, "reader_package", ch_id)
            if pkg and _package_is_valid(book_id, pkg, "full"):
                continue

            # Dedup: skip if pending/running prefetch job exists
            dup = store.find_duplicate_job(
                book_id, "tts_render", ch_id,
                cache_buster_prefix="prefetch:",
            )
            if dup:
                enqueued.append({"chapter_id": ch_id, "job_id": dup["job_id"]})
                continue

            from vn_core.orchestration.cache_keys import reader_package_cache_key
            ck = reader_package_cache_key(
                book_id=book_id, chapter_id=ch_id,
                generation_config_id=config.generation_config_id,
                reading_profile=config.reading_profile,
                execution_mode=config.execution_mode,
                tts_engine=config.tts_engine,
            )
            job = JobState(
                job_id=f"job_prefetch_{book_id}_{ch_id}_{uuid.uuid4().hex[:6]}",
                book_id=book_id,
                stage=JobStage.tts_render,
                unit_id=ch_id,
                status=JobStatus.pending,
                priority="P3",  # prefetch = lower priority
                generation_config_id=config.generation_config_id,
                execution_mode=config.execution_mode,
                cache_key=ck,
                cache_buster=f"prefetch:{uuid.uuid4().hex[:8]}",
                output_artifact_type="reader_package",
            )
            job_id = orchestrator.enqueue(job)
            enqueued.append({"chapter_id": ch_id, "job_id": job_id})

        await _broadcast_to_all("prefetch_scheduled", {
            "book_id": book_id,
            "current_chapter": current_chapter_id,
            "enqueued": [e["chapter_id"] for e in enqueued],
            "hot_window_before": hot_before,
            "hot_window_after": hot_after,
        })

        return {
            "book_id": book_id,
            "current_chapter": current_chapter_id,
            "prefetch_chapters": prefetch_ids,
            "hot_window_before": hot_before,
            "hot_window_after": hot_after,
            "enqueued_jobs": enqueued,
            "queue_depth": orchestrator.pending_count(),
        }

    @app.post("/api/projects/{book_id}/chapters/{chapter_id}/preflight")
    async def preflight_chapter(
        book_id: str, chapter_id: str, req: PreflightRequest = PreflightRequest(),
    ):
        """Preflight check for a chapter operation with cost estimate."""
        import shutil as _shutil

        _require_book(book_id)
        _validate_path_component(chapter_id)

        checks: list[dict] = []
        blocking: list[str] = []
        warnings: list[str] = []

        def _add(name: str, ok: bool, msg: str, level: str = "fail"):
            checks.append({"name": name, "status": "pass" if ok else level, "message": msg})
            if not ok and level == "fail":
                blocking.append(msg)
            elif not ok and level == "warn":
                warnings.append(msg)

        # 1. Chapter exists
        chapters = store.get_chapters(book_id)
        ch_exists = any(c["chapter_id"] == chapter_id for c in chapters)
        _add("chapter_exists", ch_exists,
             "Chapter found" if ch_exists else f"Chapter not found: {chapter_id}")

        # 2. Generation config exists
        cfg_ok = store.generation_config_exists(book_id, req.generation_config_id)
        _add("generation_config", cfg_ok,
             f"Config '{req.generation_config_id}' found" if cfg_ok
             else f"Generation config not found: {req.generation_config_id}")

        # 3. Export-specific: reader_package valid
        if req.operation == "export":
            pkg = store.get_active_artifact(book_id, "reader_package", chapter_id)
            pkg_ok = bool(pkg) and _package_is_valid(book_id, pkg, "full")
            _add("reader_package", pkg_ok,
                 "Reader package is valid" if pkg_ok
                 else "No valid reader_package. Bake or rebuild first.")
            fmt_ok = req.format in ("daw", "audiobookshelf", "m4b")
            _add("export_format", fmt_ok,
                 f"Format '{req.format}' is supported" if fmt_ok
                 else f"Unknown format: {req.format}",
                 level="fail" if not fmt_ok else "pass")

        # 4. Data dir writable
        try:
            test_file = data_path / ".preflight_write_test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink()
            _add("data_dir_writable", True, "Data directory is writable")
        except OSError:
            _add("data_dir_writable", False, "Data directory is not writable")

        # 5. External tools
        ffmpeg_ok = _shutil.which("ffmpeg") is not None
        _add("ffmpeg_available", ffmpeg_ok,
             "ffmpeg found" if ffmpeg_ok else "ffmpeg not found (required for m4b)",
             level="warn" if not ffmpeg_ok else "pass")

        # 6. LLM gateway
        llm_backend = getattr(llm_gateway, "_default_backend", "unknown")
        if llm_backend == "mock":
            _add("llm_gateway", True, "LLM gateway: mock (no cost, pass)")
        elif llm_backend in getattr(llm_gateway, "_backends", {}):
            _add("llm_gateway", True, f"LLM gateway: {llm_backend} configured")
        else:
            _add("llm_gateway", False,
                 f"LLM gateway: {llm_backend} has no backend registered",
                 level="warn")

        # 7. TTS engine (from generation config if available)
        if cfg_ok:
            config = store.get_generation_config(book_id, req.generation_config_id)
            tts_engine = config.tts_engine
            adapters = getattr(tts_gateway, "_adapters", {})
            if tts_engine in adapters:
                _add("tts_engine", True,
                     f"TTS engine '{tts_engine}' adapter registered")
            else:
                _add("tts_engine", False,
                     f"TTS engine '{tts_engine}' has no adapter",
                     level="fail")
        else:
            _add("tts_engine", False, "TTS engine unknown (config missing)",
                 level="warn")

        # --- Cost estimate ---
        cost = None
        _seg_count_est = 0
        if ch_exists and cfg_ok:
            try:
                paragraphs = store.get_paragraphs(book_id, chapter_id)
                _seg_count_est = max(len(paragraphs) * 4, 1)
                config = store.get_generation_config(book_id, req.generation_config_id)
                cost = cost_planner.estimate_chapter(
                    book_id=book_id,
                    chapter_id=chapter_id,
                    segment_count=_seg_count_est,
                    llm_model="mock",
                    tts_engine=config.tts_engine,
                    reading_profile=config.reading_profile,
                )
            except Exception:
                warnings.append("Cost estimation unavailable")

        return {
            "ok": len(blocking) == 0,
            "operation": req.operation,
            "book_id": book_id,
            "chapter_id": chapter_id,
            "checks": checks,
            "blocking_errors": blocking,
            "warnings": warnings,
            "estimated_cost": {
                "segment_count_est": _seg_count_est,
                "tts_total_chars": cost.tts_total_chars if cost else 0,
                "total_duration_minutes": cost.total_duration_minutes if cost else 0,
                "llm_cost_usd": cost.llm_cost_usd if cost else 0,
                "tts_cost_usd": cost.tts_cost_usd if cost else 0,
                "total_cost_usd": cost.total_cost_usd if cost else 0,
            } if cost else {
                "segment_count_est": 0,
                "tts_total_chars": 0,
                "total_duration_minutes": 0,
                "llm_cost_usd": 0,
                "tts_cost_usd": 0,
                "total_cost_usd": 0,
            },
        }

    @app.post("/api/cost/estimate")
    async def estimate_cost(req: BakeChapterRequest):
        """Estimate cost for baking a chapter without executing."""
        _require_book(req.book_id)
        paragraphs = store.get_paragraphs(req.book_id, req.chapter_id)
        segment_count = len(paragraphs) * 4  # rough: ~4 segments per paragraph

        config = _resolve_generation_config(
            req.book_id, req.generation_config_id, req.reading_profile,
        )
        llm_model = "mock"
        if llm_gateway._default_backend != "mock":
            llm_model = llm_gateway._default_backend

        estimate = cost_planner.estimate_chapter(
            book_id=req.book_id,
            chapter_id=req.chapter_id,
            segment_count=segment_count,
            llm_model=llm_model,
            tts_engine=config.tts_engine,
            reading_profile=config.reading_profile,
        )
        return {
            "book_id": estimate.book_id,
            "chapter_id": estimate.chapter_id,
            "estimate_type": estimate.estimate_type,
            "segment_count_est": segment_count,
            "llm_model": estimate.llm_model,
            "tts_engine": estimate.tts_engine,
            "llm_cost_usd": estimate.llm_cost_usd,
            "tts_cost_usd": estimate.tts_cost_usd,
            "total_cost_usd": estimate.total_cost_usd,
            "total_duration_minutes": estimate.total_duration_minutes,
            "llm_input_tokens_est": estimate.llm_input_tokens_est,
            "llm_output_tokens_est": estimate.llm_output_tokens_est,
            "tts_total_chars": estimate.tts_total_chars,
            "tts_total_duration_ms": estimate.tts_total_duration_ms,
        }

    @app.get("/api/cost/estimate-book/{book_id}")
    async def estimate_book_cost(book_id: str, generation_config_id: str = "default"):
        """Estimate cost for baking an entire book."""
        _require_book(book_id)
        chapters = store.get_chapters(book_id)
        total_paragraphs = sum(
            len(store.get_paragraphs(book_id, c["chapter_id"])) for c in chapters
        )
        total_segments = total_paragraphs * 4

        config = store.get_generation_config(book_id, generation_config_id)
        llm_model = "mock"
        if llm_gateway._default_backend != "mock":
            llm_model = llm_gateway._default_backend

        estimate = cost_planner.estimate_book(
            book_id=book_id,
            chapter_ids=[c["chapter_id"] for c in chapters],
            total_segments=total_segments,
            llm_model=llm_model,
            tts_engine=config.tts_engine,
            reading_profile=config.reading_profile,
        )
        return {
            "book_id": estimate.book_id,
            "chapter_count": len(chapters),
            "segment_count_est": total_segments,
            "llm_model": estimate.llm_model,
            "tts_engine": estimate.tts_engine,
            "llm_cost_usd": estimate.llm_cost_usd,
            "tts_cost_usd": estimate.tts_cost_usd,
            "total_cost_usd": estimate.total_cost_usd,
            "total_duration_minutes": estimate.total_duration_minutes,
        }

    @app.post("/api/reader-adapter")
    async def reader_adapter(req: ReaderAdapterRequestModel, request: Request):
        base_url = str(request.base_url).rstrip("/")
        chapters_path = f"{base_url}/api/projects/{req.book_id}/chapters"
        if req.action == "get_status":
            chapters = store.get_chapters(req.book_id)
            chapter_ids = [c["chapter_id"] for c in chapters]
            return ReaderAdapterResponse(
                book_id=req.book_id,
                status="ready",
                available_chapters=chapter_ids,
            ).model_dump()

        if req.action == "get_chapter" and req.chapter_id:
            return ReaderAdapterResponse(
                book_id=req.book_id,
                status="ready",
                current_chapter=req.chapter_id,
                chapter_content_url=f"{chapters_path}/{req.chapter_id}/content",
                chapter_audio_url=f"{chapters_path}/{req.chapter_id}/audio",
                chapter_timing_url=f"{chapters_path}/{req.chapter_id}/timing",
            ).model_dump()

        return ReaderAdapterResponse(
            book_id=req.book_id,
            status="idle",
        ).model_dump()

    @app.get("/api/projects/{book_id}/chapters/{chapter_id}/content")
    async def get_chapter_content(book_id: str, chapter_id: str):
        _require_book(book_id)
        _validate_path_component(chapter_id)
        pkg_dir = data_path / "packages" / book_id / chapter_id
        html_file = pkg_dir / "cleaned.html"
        if html_file.exists():
            from fastapi.responses import HTMLResponse
            return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
        paragraphs_data = store.get_paragraphs(book_id, chapter_id)
        if not paragraphs_data:
            raise HTTPException(status_code=404, detail="Chapter content not found")
        from vn_core.xhtml import generate_cleaned_html, wrap_full_document
        segments = []
        for p in paragraphs_data:
            segments.extend(_segment_paragraph_row(p))
        body = generate_cleaned_html(chapter_id, segments)
        html_content = wrap_full_document(body, book_id=book_id)
        return HTMLResponse(content=html_content)

    @app.get("/api/projects/{book_id}/chapters/{chapter_id}/timing")
    async def get_chapter_timing(book_id: str, chapter_id: str):
        _require_book(book_id)
        _validate_path_component(chapter_id)
        pkg_dir = data_path / "packages" / book_id / chapter_id
        timing_file = pkg_dir / "timing.json"
        if timing_file.exists():
            return json.loads(timing_file.read_text(encoding="utf-8"))
        raise HTTPException(status_code=404, detail="Timing not found. Run bake_chapter first.")

    @app.get("/api/projects/{book_id}/chapters/{chapter_id}/audio")
    async def get_chapter_audio(book_id: str, chapter_id: str):
        _require_book(book_id)
        _validate_path_component(chapter_id)
        from fastapi.responses import FileResponse

        pkg_dir = data_path / "packages" / book_id / chapter_id
        manifest_path = pkg_dir / "audio_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for chapter in manifest.get("chapters", []):
                audio_file = chapter.get("audio_file", "")
                if not audio_file:
                    continue
                audio_path = pkg_dir / audio_file
                if audio_path.exists():
                    return FileResponse(
                        audio_path,
                        media_type=_audio_media_type(audio_path),
                    )

        audio_dir = pkg_dir / "audio"
        if audio_dir.exists():
            for pattern in ("*.wav", "*.mp3", "*.m4a", "*.opus"):
                files = list(audio_dir.glob(pattern))
                if files:
                    return FileResponse(files[0], media_type=_audio_media_type(files[0]))
        tts_dir = data_path / "tts_output"
        mp3_files = list(tts_dir.glob(f"*{chapter_id}*.mp3"))
        if mp3_files:
            return FileResponse(mp3_files[0], media_type="audio/mpeg")
        raise HTTPException(status_code=404, detail="Audio not found. Run TTS synthesis first.")

    def _audio_media_type(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".wav":
            return "audio/wav"
        if suffix == ".m4a":
            return "audio/mp4"
        if suffix == ".opus":
            return "audio/ogg"
        return "audio/mpeg"

    @app.websocket("/ws/pipeline")
    async def pipeline_websocket(websocket: WebSocket):
        await websocket.accept()
        session_id = uuid.uuid4().hex[:12]
        _active_sessions[session_id] = {"websocket": websocket}
        await websocket.send_json({"type": "connected", "session_id": session_id})
        try:
            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)
                cmd = msg.get("command", "")
                if cmd == "status":
                    await websocket.send_json({
                        "type": "status",
                        "session_id": session_id,
                        "state": "idle",
                        "stats": orchestrator.get_stats(),
                    })
                elif cmd == "preflight":
                    preflight = PreflightCheck()
                    result = preflight.run_preflight()
                    await websocket.send_json({
                        "type": "preflight_result",
                        "can_proceed": result.can_proceed,
                        "checks": result.checks,
                        "warnings": result.warnings,
                        "errors": result.errors,
                    })
                elif cmd == "subscribe":
                    # Subscribe to pipeline progress for a specific book/chapter
                    book_id = msg.get("book_id", "")
                    chapter_id = msg.get("chapter_id", "")
                    _active_sessions[session_id]["subscription"] = {
                        "book_id": book_id,
                        "chapter_id": chapter_id,
                    }
                    await websocket.send_json({
                        "type": "subscribed",
                        "session_id": session_id,
                        "book_id": book_id,
                        "chapter_id": chapter_id,
                    })
                elif cmd == "stats":
                    await websocket.send_json({
                        "type": "orchestrator_stats",
                        **orchestrator.get_stats(),
                    })
                else:
                    await websocket.send_json(
                        {"type": "error", "message": f"unknown command: {cmd}"}
                    )
        except WebSocketDisconnect:
            pass
        finally:
            _active_sessions.pop(session_id, None)

    return app


app = create_app()
