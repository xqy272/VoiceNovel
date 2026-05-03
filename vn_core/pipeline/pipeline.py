"""End-to-end pipeline: import → segment → adapt → plan → render → package.

Cold Start 4-Phase Path:
  Phase 1 (local):  Import + segment + adapt + fallback voice (no LLM)
  Phase 2 (scan):   LLM quick scan of current chapter (character/term extraction)
  Phase 3 (buffer):  Render minimum playable buffer (first 20-40 segments)
  Phase 4 (full):    Background full-chapter processing
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Coroutine

from vn_core.adaptation import TextAdapter
from vn_core.adaptation.llm_adapter import AdaptationPolicy, LLMTextAdapter
from vn_core.book_model import BookModel
from vn_core.context import ContextFetchEngine
from vn_core.contracts.context_spec import ContextSpec
from vn_core.contracts.reader_manifest import ReaderPackageManifest
from vn_core.contracts.reading_plan import Enhancements, ReadingStyle, VoiceConstraints
from vn_core.contracts.segment import Segment
from vn_core.contracts.text_adaptation import AdaptationScope, TextAdaptationOperation
from vn_core.contracts.timing_entry import TimingEntry
from vn_core.harness import GateDecision, HarnessGate
from vn_core.importers import import_book
from vn_core.llm_gateway import LLMGateway
from vn_core.orchestration import Orchestrator
from vn_core.packaging import PackagingService
from vn_core.planner import ReadingPlanner
from vn_core.pronunciation import PronunciationEngine
from vn_core.render import SpeechGateway
from vn_core.render.tts_input_composer import TTSInputComposer
from vn_core.scanner import BookScanner
from vn_core.segmenter import SEGMENTER_VERSION, ChineseSegmenter
from vn_core.store import ProjectStore
from vn_core.timing import (
    assemble_chapter_mp3,
    assemble_chapter_wav,
    build_timing,
    compute_chapter_duration_ms,
    ffmpeg_available,
    get_audio_duration_ms,
)
from vn_core.voice import VoiceRegistry
from vn_core.voice.casting import cast_all_characters
from vn_core.xhtml import generate_cleaned_html, wrap_full_document

ProgressCallback = Callable[[str, dict], Coroutine[None, None, None]]

MIN_BUFFER_SEGMENTS = 30


@dataclass
class ColdStartResult:
    book_id: str
    chapters: list = field(default_factory=list)
    phase: str = ""
    segments_count: int = 0
    buffer_segments_count: int = 0
    playable: bool = False
    buffer_package_dir: str = ""
    render_window_id: str = ""
    full_bake_job_id: str = ""
    errors: list = field(default_factory=list)


@dataclass
class BakeResult:
    book_id: str
    chapter_id: str
    success: bool = False
    generation_config_id: str = "default"
    reading_profile: str = "enhanced"
    segments: list = field(default_factory=list)
    plan: list = field(default_factory=list)
    voice_assignments: dict = field(default_factory=dict)
    timing: list = field(default_factory=list)
    package_dir: str = ""
    cleaned_html: str = ""
    errors: list = field(default_factory=list)


class Pipeline:
    def __init__(
        self,
        store: ProjectStore,
        llm: LLMGateway | None = None,
        gateway: SpeechGateway | None = None,
        output_dir: str = "data/output",
        min_buffer_segments: int = MIN_BUFFER_SEGMENTS,
        concurrent_tts: int = 4,
        tts_engine: str = "mock",
        generation_config_id: str = "default",
        reading_profile: str = "enhanced",
        audio_codec: str = "mp3",
        adaptation_policy: str = "conservative",
    ):
        if reading_profile not in {"faithful", "enhanced"}:
            raise ValueError("reading_profile must be 'faithful' or 'enhanced'")
        if audio_codec not in {"mp3", "wav"}:
            raise ValueError("audio_codec must be 'mp3' or 'wav'")
        if adaptation_policy not in {"conservative", "balanced", "aggressive", "off"}:
            raise ValueError(
                "adaptation_policy must be 'conservative', 'balanced', "
                "'aggressive', or 'off'"
            )

        if audio_codec == "mp3" and not ffmpeg_available():
            import warnings
            warnings.warn("ffmpeg not available, falling back to WAV output")
            audio_codec = "wav"

        self.store = store
        self.llm = llm or LLMGateway()
        self.segmenter = ChineseSegmenter()
        self.adapter = TextAdapter()
        self.llm_adapter = (
            LLMTextAdapter(self.llm, policy=AdaptationPolicy(adaptation_policy))
            if adaptation_policy != "off" else None
        )
        self.planner = ReadingPlanner(llm=self.llm)
        self.voice_registry = VoiceRegistry()
        self.pronunciation = PronunciationEngine()
        self.tts_composer = TTSInputComposer(pronunciation_engine=self.pronunciation)
        self.tts_gateway = gateway or SpeechGateway(output_dir=str(Path(output_dir) / "tts"))
        self.pkg_service = PackagingService()
        self.harness = HarnessGate()
        self.orchestrator = Orchestrator(store=store)
        self.output_dir = Path(output_dir)
        self.min_buffer_segments = min_buffer_segments
        self.concurrent_tts = concurrent_tts
        self.tts_engine = tts_engine
        self.generation_config_id = generation_config_id
        self.reading_profile = reading_profile
        self.audio_codec = audio_codec
        self._progress_callbacks: list[ProgressCallback] = []

    def on_progress(self, callback: ProgressCallback):
        """Register an async callback for pipeline stage progress events.

        Callback signature: ``async def callback(event_type: str, data: dict) -> None``.

        Event types: ``segment_start``, ``segment_done``, ``plan_start``, ``plan_done``,
        ``tts_start``, ``tts_progress``, ``tts_done``, ``timing_start``, ``timing_done``,
        ``xhtml_start``, ``xhtml_done``, ``package_start``, ``package_done``,
        ``harness_validating``, ``harness_done``, ``chapter_done``, ``chapter_error``.
        """
        self._progress_callbacks.append(callback)

    async def _emit(self, event_type: str, data: dict):
        for cb in self._progress_callbacks:
            try:
                await cb(event_type, data)
            except Exception:
                pass

    async def cold_start_existing(
        self, book_id: str, chapter_id: str,
    ) -> ColdStartResult:
        """Cold start Phase 2-4 for an already-imported book."""
        result = ColdStartResult(book_id=book_id)
        result.phase = "phase1_local"

        paragraphs = self.store.get_paragraphs(book_id, chapter_id)
        if not paragraphs:
            result.errors.append(f"No paragraphs for {chapter_id}")
            return result

        segs = []
        for p in paragraphs:
            a = self.adapter.adapt_pre_segment(
                f"{p['paragraph_id']}_pre", p["text"],
            )
            segments = self.segmenter.segment_paragraph(
                p["paragraph_id"], a.adapted_text,
                source_href=p.get("source_href", ""),
                source_order=p.get("source_order", 0),
                source_dom_hint=p.get("source_dom_hint", ""),
            )
            segs.extend(segments)
        result.segments_count = len(segs)

        # Phase 2: Quick scan
        result.phase = "phase2_scan"
        chapter_text = "\n".join(p["text"] for p in paragraphs)
        scanner = BookScanner(self.llm, self.store)
        self._sync_scan(scanner, book_id, chapter_id, chapter_text)

        # Phase 3: Buffer window
        result.phase = "phase3_buffer"
        buffer_count = min(self.min_buffer_segments, len(segs))
        result.buffer_segments_count = buffer_count

        if buffer_count > 0:
            try:
                window_result = await self.bake_window(
                    book_id=book_id, chapter_id=chapter_id,
                    start=0, count=buffer_count,
                )
                if window_result.success:
                    result.playable = True
                    result.buffer_package_dir = window_result.package_dir
                    end_count = min(buffer_count, len(segs))
                    result.render_window_id = (
                        f"{chapter_id}_buffer_000_{end_count:03d}"
                    )
                    result.phase = "buffer_ready"
                else:
                    result.errors.append(
                        f"Phase 3 buffer failed: {window_result.errors}",
                    )
            except Exception as e:
                result.errors.append(f"Phase 3 exception: {e}")

        # Phase 4: Submit background full-bake job (only if no full package exists)
        existing_full = self.store.get_active_artifact(
            book_id, "reader_package", chapter_id,
        )
        if existing_full and self.store.check_dependencies_active(
            book_id, existing_full["artifact_version_id"],
        )["all_active"]:
            result.full_bake_job_id = ""  # already done
        elif result.playable:
            from vn_core.contracts.job_state import JobStage, JobState, JobStatus
            from vn_core.orchestration.cache_keys import reader_package_cache_key
            ck = reader_package_cache_key(
                book_id=book_id, chapter_id=chapter_id,
                generation_config_id=self.generation_config_id,
                reading_profile=self.reading_profile,
                execution_mode="balanced", tts_engine=self.tts_engine,
            )
            job = JobState(
                job_id=f"job_cs_{book_id}_{chapter_id}",
                book_id=book_id, stage=JobStage.tts_render,
                unit_id=chapter_id, status=JobStatus.pending,
                priority="P1", generation_config_id=self.generation_config_id,
                execution_mode="balanced", cache_key=ck,
                output_artifact_type="reader_package",
            )
            jid = self.orchestrator.enqueue(job)
            result.full_bake_job_id = jid
            result.phase = result.phase or "phase4_background"

        result.chapters = [{"chapter_id": chapter_id, "segments": len(segs)}]
        return result

    async def cold_start(
        self,
        source_path: str,
        book_id: str = "",
        scan_chapters: int = 1,
    ) -> ColdStartResult:
        """4-phase cold start: local → scan → buffer → (full bake async)."""
        result = ColdStartResult(book_id=book_id)

        # Phase 1: Local — import + segment + adapt (no LLM, no network)
        chapters = import_book(source_path, book_id=book_id, store=self.store)
        if not book_id:
            book_id = chapters[0].book_id if chapters else ""
        result.book_id = book_id
        result.phase = "phase1_local"

        if not chapters:
            result.errors.append("No chapters imported")
            return result

        all_segments_map: dict[str, list] = {}
        for ch in chapters:
            paragraphs = self.store.get_paragraphs(book_id, ch.chapter_id)
            segs = []
            for p in paragraphs:
                a = self.adapter.adapt_pre_segment(
                    f"{p['paragraph_id']}_pre", p["text"],
                )
                segments = self.segmenter.segment_paragraph(
                    p["paragraph_id"], a.adapted_text,
                    source_href=p.get("source_href", ""),
                    source_order=p.get("source_order", 0),
                    source_dom_hint=p.get("source_dom_hint", ""),
                )
                segs.extend(segments)
            all_segments_map[ch.chapter_id] = segs
            result.segments_count += len(segs)

        # Phase 2: LLM Quick Scan — scan first N chapters for characters/terms
        result.phase = "phase2_scan"
        scanner = BookScanner(self.llm, self.store)
        for ch in chapters[:scan_chapters]:
            chapter_text = "\n".join(
                p.source_text for p in ch.paragraphs
            )
            self._sync_scan(scanner, book_id, ch.chapter_id, chapter_text)

        # Phase 3: Minimum Buffer — render first N segments of first chapter
        result.phase = "phase3_buffer"
        first_chapter = chapters[0]
        first_chapter_id = first_chapter.chapter_id
        first_ch_segs = all_segments_map.get(first_chapter_id, [])
        buffer_count = min(self.min_buffer_segments, len(first_ch_segs))
        result.buffer_segments_count = buffer_count

        if buffer_count > 0:
            try:
                # bake_window is async inside cold_start (which is now async)
                window_result = await self.bake_window(
                    book_id=book_id, chapter_id=first_chapter_id,
                    start=0, count=buffer_count,
                )
                if window_result.success:
                    result.playable = True
                    result.buffer_package_dir = window_result.package_dir
                    first_ch_segs[0].segment_id if first_ch_segs else ""
                    end_idx = min(buffer_count - 1, len(first_ch_segs) - 1)
                    first_ch_segs[end_idx].segment_id if end_idx >= 0 else ""
                    result.render_window_id = (
                        f"{first_chapter_id}_buffer_000_{buffer_count:03d}"
                    )
                    result.phase = "buffer_ready"
                else:
                    result.errors.append(
                        f"Phase 3 buffer failed: {window_result.errors}",
                    )
                    self.harness.write_exception(
                        store=self.store, book_id=book_id,
                        unit_id=first_chapter_id,
                        stage="cold_start_phase3",
                        exception_type="tts_timeout",
                        message="; ".join(window_result.errors),
                    )
            except Exception as e:
                result.errors.append(f"Phase 3 exception: {e}")

        # Phase 4: Submit full-chapter bake as Store-backed background job
        result.phase = result.phase or "phase4_background"
        if result.playable:
            from vn_core.contracts.job_state import JobStage, JobState, JobStatus
            from vn_core.orchestration.cache_keys import reader_package_cache_key
            ck = reader_package_cache_key(
                book_id=book_id, chapter_id=first_chapter_id,
                generation_config_id=self.generation_config_id,
                reading_profile=self.reading_profile,
                execution_mode="balanced",
                tts_engine=self.tts_engine,
            )
            job = JobState(
                job_id=f"job_cold_start_{book_id}_{first_chapter_id}",
                book_id=book_id,
                stage=JobStage.tts_render,
                unit_id=first_chapter_id,
                status=JobStatus.pending,
                priority="P1",
                generation_config_id=self.generation_config_id,
                execution_mode="balanced",
                cache_key=ck,
                output_artifact_type="reader_package",
            )
            jid = self.orchestrator.enqueue(job)
            result.full_bake_job_id = jid

        self._commit_artifact(book_id, "import", first_chapter_id)

        result.chapters = [
            {
                "chapter_id": ch.chapter_id,
                "title": ch.title,
                "paragraph_count": len(ch.paragraphs),
                "segments": len(all_segments_map.get(ch.chapter_id, [])),
            }
            for ch in chapters
        ]
        return result

    def import_and_scan(self, source_path: str, book_id: str = "") -> dict:
        """Legacy import+scan entry point (Phase 1+2 combined)."""
        chapters = import_book(source_path, book_id=book_id, store=self.store)
        if not book_id:
            book_id = chapters[0].book_id if chapters else ""

        _ = BookModel(self.store, book_id)
        scanner = BookScanner(self.llm, self.store)

        for ch in chapters:
            chapter_text = "\n".join(p.source_text for p in ch.paragraphs)
            self._sync_scan(scanner, book_id, ch.chapter_id, chapter_text)

        self._commit_artifact(
            book_id, "import",
            f"{chapters[0].chapter_id if chapters else 'all'}",
        )

        return {
            "book_id": book_id,
            "chapters": [
                {
                    "chapter_id": ch.chapter_id,
                    "title": ch.title,
                    "paragraph_count": len(ch.paragraphs),
                }
                for ch in chapters
            ],
        }

    async def bake_window(
        self,
        book_id: str,
        chapter_id: str,
        start: int = 0,
        count: int = MIN_BUFFER_SEGMENTS,
        force: bool = False,
    ) -> BakeResult:
        """Render a segment window for cold-start playback.

        Reuses the same segment→plan→voice→TTS→package pipeline as
        bake_chapter, but only processes *count* segments starting from
        *start*.  Writes a ``window_package`` artifact (distinct from
        the full ``reader_package``).

        Returns BakeResult with the window package directory path.
        """

        result = BakeResult(
            book_id=book_id,
            chapter_id=chapter_id,
            generation_config_id=self.generation_config_id,
            reading_profile=self.reading_profile,
        )

        # --- segment + adapt (same as bake_chapter) ---
        await self._emit("segment_start", {"book_id": book_id, "chapter_id": chapter_id})
        paragraphs = self.store.get_paragraphs(book_id, chapter_id)
        if not paragraphs:
            result.errors.append(f"No paragraphs found for {chapter_id}")
            result.success = False
            return result

        self.pronunciation.set_book(book_id, self.store)
        book_model = BookModel(self.store, book_id)
        all_segments = []
        adapted_texts: dict[str, str] = {}
        all_adaptation_ops: list[TextAdaptationOperation] = []

        # Phase A: pre-segment rule-based adaptation + collect adapted paragraphs
        adapted_paragraphs = []
        for p in paragraphs:
            pre_result = self.adapter.adapt_pre_segment(
                f"{p['paragraph_id']}_pre", p["text"],
            )
            if pre_result.operations:
                all_adaptation_ops.extend(pre_result.operations)
            adapted_paragraphs.append({
                "paragraph_id": p["paragraph_id"],
                "text": pre_result.adapted_text,
                "source_href": p.get("source_href", ""),
                "source_order": p.get("source_order", 0),
                "source_dom_hint": p.get("source_dom_hint", ""),
            })

        # Phase B: LLM-driven adaptation (batch, skip if no real LLM or policy=off)
        if self.llm_adapter and self.llm._default_backend != "mock":
            try:
                llm_result = await self.llm_adapter.adapt_paragraphs_batch(
                    adapted_paragraphs,
                )
                if llm_result.operations:
                    all_adaptation_ops.extend(llm_result.operations)
            except Exception:
                import logging
                logging.getLogger("vn_core").warning(
                    "LLM adaptation failed for %s/%s, continuing with rule-based only",
                    book_id, chapter_id, exc_info=True,
                )

        self._apply_paragraph_operations(adapted_paragraphs, all_adaptation_ops)

        # Phase C: segment + pre-tts adaptation
        for ap in adapted_paragraphs:
            segs = self.segmenter.segment_paragraph(
                ap["paragraph_id"], ap["text"],
                source_href=ap["source_href"],
                source_order=ap["source_order"],
                source_dom_hint=ap["source_dom_hint"],
            )
            all_segments.extend(segs)
            for seg in segs:
                tts_base = self._apply_tts_operations(
                    seg.text,
                    all_adaptation_ops,
                    seg.segment_id,
                    seg.paragraph_id,
                )
                tts_result = self.adapter.adapt_pre_tts(seg.segment_id, tts_base)
                if tts_result.operations:
                    all_adaptation_ops.extend(tts_result.operations)
                adapted_texts[seg.segment_id] = tts_result.adapted_text

        if not all_segments:
            result.errors.append("No segments produced")
            result.success = False
            return result

        # Commit adaptation ops (idempotent, like bake_chapter)
        adaptation_ops_ver = ""
        if all_adaptation_ops:
            from vn_core.contracts.stage_result import StageResult
            ops_data = [
                op.model_dump() if hasattr(op, "model_dump") else op
                for op in all_adaptation_ops
            ]
            adapt_hash = hashlib.sha256(
                json.dumps(ops_data, ensure_ascii=False, sort_keys=True).encode(),
            ).hexdigest()[:40]
            existing_adapt = self.store.get_active_artifact(
                book_id, "adaptation_ops", chapter_id,
            )
            if existing_adapt and existing_adapt.get("input_hash") == adapt_hash:
                adaptation_ops_ver = existing_adapt["artifact_version_id"]
            else:
                ops_artifact_vid = self._next_artifact_version(
                    book_id, "adaptation_ops", chapter_id,
                )
                stage_result = StageResult(
                    stage="adaptation", book_id=book_id, unit_id=chapter_id,
                    proposed_artifacts=[{
                        "artifact_type": "adaptation_ops",
                        "artifact_version_id": ops_artifact_vid,
                        "unit_id": chapter_id,
                        "data": ops_data,
                        "input_hash": adapt_hash,
                    }],
                    decisions=[
                        {
                            "segment_id": op.get("segment_id", chapter_id),
                            "decision_type": (
                                f"text_adaptation:{op.get('op_id', chapter_id)}"
                            ),
                            "value": op,
                            "confidence": op.get("confidence", 0.99),
                            "source": op.get("source", "rule"),
                            "evidence": op.get("evidence", []),
                        }
                        for op in ops_data if op.get("segment_id")
                    ],
                    provenance={
                        "stage": "adaptation", "unit_id": chapter_id,
                        "artifact_version_id": ops_artifact_vid,
                        "generation_config_id": self.generation_config_id,
                        "reading_profile": self.reading_profile,
                    },
                    metrics={"operation_count": len(all_adaptation_ops)},
                )
                csr_result = self.harness.commit_stage_result(self.store, stage_result)
                if csr_result.decision == "pass":
                    adaptation_ops_ver = ops_artifact_vid
                else:
                    result.errors.append(f"Harness rejected adaptation_ops: {csr_result.reason}")
                    result.success = False
                    return result

        # --- plan (full chapter, needed for voice context) ---
        await self._emit("plan_start", {"book_id": book_id, "chapter_id": chapter_id})
        planner_with_model = ReadingPlanner(llm=self.llm, book_model=book_model)
        full_plan = await planner_with_model.plan_chapter(all_segments, chapter_id)
        full_plan = self._apply_reading_profile(full_plan)

        # --- voice casting (full chapter) ---
        voice_assignments = cast_all_characters(
            plan_entries=full_plan,
            voice_registry=self.voice_registry,
            store=self.store,
            book_id=book_id,
        )
        va_list = [
            {
                "character_id": va.character_id, "voice_id": va.voice_id,
                "confidence": va.confidence,
                "user_locked": va.user_locked, "source": va.source,
                "status": "user_locked" if va.user_locked else "inferred",
            }
            for va in voice_assignments.values()
        ]
        va_hash = hashlib.sha256(
            json.dumps(sorted(va_list, key=lambda x: x.get("character_id", "")),
                       ensure_ascii=False).encode(),
        ).hexdigest()[:40]
        existing_va = self.store.get_active_artifact(book_id, "voice_assignment", chapter_id)
        if existing_va and existing_va.get("input_hash") == va_hash:
            voice_artifact_vid = existing_va["artifact_version_id"]
        else:
            voice_artifact_vid = self._next_artifact_version(
                book_id, "voice_assignment", chapter_id,
            )
            va_commit = self.harness.commit_voice_assignments(
                store=self.store, book_id=book_id, unit_id=chapter_id,
                assignments=va_list,
                generation_config_id=self.generation_config_id,
                artifact_version_id=voice_artifact_vid,
            )
            if va_commit.decision != "pass":
                voice_artifact_vid = ""

        # --- commit pre-TTS artifacts ---
        segments_jsonl = "\n".join(
            json.dumps(s.model_dump(), ensure_ascii=False) for s in all_segments
        )
        reading_plan_jsonl = "\n".join(
            json.dumps(p.model_dump(), ensure_ascii=False) for p in full_plan
        )
        committed_seg_ver = self._commit_artifact_idempotent(
            book_id, "segments", chapter_id, file_path="",
            input_hash=hashlib.sha256(segments_jsonl.encode()).hexdigest()[:40],
        )
        committed_plan_ver = self._commit_artifact_idempotent(
            book_id, "reading_plan", chapter_id, file_path="",
            input_hash=hashlib.sha256(reading_plan_jsonl.encode()).hexdigest()[:40],
        )

        # --- select window segments ---
        window_segments = all_segments[start : start + count]
        window_plan = [p for p in full_plan
                       if p.segment_id in {s.segment_id for s in window_segments}]
        if not window_segments:
            result.errors.append("Window produced zero segments")
            result.success = False
            return result

        window_id = f"{chapter_id}_buffer_{start:03d}_{start + len(window_segments):03d}"
        result.segments = window_segments
        result.plan = window_plan
        result.voice_assignments = {
            k: v.model_dump() for k, v in voice_assignments.items()
        }

        # --- TTS for window only ---
        from vn_core.orchestration.cache_keys import audio_take_cache_key as _at_key
        await self._emit("tts_start", dict(
            book_id=book_id, chapter_id=chapter_id, segments=len(window_plan),
        ))
        audio_durations: dict[str, int] = {}
        semaphore = asyncio.Semaphore(self.concurrent_tts)

        async def _synth_one(entry):
            va = voice_assignments.get(entry.speaker_id)
            voice_id = va.voice_id if va else self.voice_registry.get_fallback_voice("narrator")
            tts_text = adapted_texts.get(entry.segment_id, entry.text)
            tts_req = self.tts_composer.compose(
                segment_id=entry.segment_id, tts_base_text=tts_text,
                voice_id=voice_id, engine=self.tts_engine,
                reading_style=entry.reading_style.model_dump(),
                prosody_hint=entry.reading_style.prosody_hint,
                format=self.audio_codec,
            )
            at_ck = _at_key(
                segment_id=entry.segment_id,
                text=tts_req.text,
                voice_id=voice_id,
                engine=self.tts_engine,
                reading_style=entry.reading_style.model_dump(),
                generation_config_id=self.generation_config_id,
                format=tts_req.format,
                pronunciation=self._pronunciation_cache_context(),
            )
            cached_at = self.store.find_artifact_by_cache_key(book_id, "audio_take", at_ck)
            if cached_at:
                cp = cached_at.get("file_path", "")
                if cp and Path(cp).exists() and self.store.check_dependencies_active(
                    book_id, cached_at["artifact_version_id"],
                )["all_active"]:
                    await self._emit("tts_cache_hit", {
                        "book_id": book_id, "chapter_id": chapter_id,
                        "segment_id": entry.segment_id,
                    })
                    dur = get_audio_duration_ms(cp)
                    return entry.segment_id, None, cp, dur if dur else 800, at_ck
            async with semaphore:
                tts_res = await self.tts_gateway.synthesize(tts_req)
            return entry.segment_id, tts_res, "", 0, at_ck

        tasks = [_synth_one(entry) for entry in window_plan]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        audio_paths: dict[str, str] = {}
        tts_results: dict[str, object] = {}
        audio_take_vids: list[str] = []
        for r in results:
            if isinstance(r, Exception):
                result.errors.append(str(r))
                continue
            sid, tres, cpath, cdur, ack = r
            if cpath:
                audio_paths[sid] = cpath
                audio_durations[sid] = cdur
                # Track cached audio_take version for window_package deps
                cached_at = self.store.find_artifact_by_cache_key(
                    book_id, "audio_take", ack,
                )
                if cached_at:
                    audio_take_vids.append(cached_at["artifact_version_id"])
                continue
            tts_results[sid] = tres
            ok = tres.status == "success" and tres.audio_path
            md = get_audio_duration_ms(tres.audio_path) if ok else None
            audio_durations[sid] = (
                md if md else (int(tres.duration_ms) if tres.status == "success" else 800)
            )
            if tres.status == "success" and tres.audio_path:
                audio_paths[sid] = tres.audio_path
                at_vid = self._next_artifact_version(book_id, "audio_take", sid)
                self.store.write_artifact(
                    book_id=book_id, artifact_version_id=at_vid,
                    artifact_type="audio_take", unit_id=sid,
                    file_path=tres.audio_path, input_hash=ack,
                )
                core_deps = [
                    (committed_seg_ver, "segments"),
                    (committed_plan_ver, "reading_plan"),
                ]
                for dv, dr in core_deps:
                    self.store.add_dependency(book_id, at_vid, dv, dr)
                if voice_artifact_vid:
                    self.store.add_dependency(
                        book_id, at_vid, voice_artifact_vid, "voice_assignment",
                    )
                if adaptation_ops_ver:
                    self.store.add_dependency(
                        book_id, at_vid, adaptation_ops_ver, "adaptation_ops",
                    )
                audio_take_vids.append(at_vid)

        if window_plan:
            n_plan = len(window_plan)
            n_audio = len(audio_paths)
            if n_audio == 0:
                result.errors.append("Window TTS produced no audio")
                result.success = False
                return result
            if n_audio < n_plan:
                missing = [
                    p.segment_id for p in window_plan
                    if p.segment_id not in audio_paths
                ]
                result.errors.append(
                    f"Window TTS incomplete: {n_audio}/{n_plan} segments. "
                    f"Missing: {missing[:5]}",
                )
                result.success = False
                return result

        # --- timing (window only) ---
        timing = build_timing(
            segment_ids=[s.segment_id for s in window_segments],
            segment_durations_ms=[audio_durations.get(s.segment_id, 800) for s in window_segments],
        )

        # --- cleaned HTML (window only) ---
        cleaned_body = generate_cleaned_html(
            chapter_id=chapter_id, segments=window_segments, adapted_texts=None,
        )
        cleaned_html = wrap_full_document(cleaned_body, book_id=book_id)

        # --- package window ---
        codec = self.audio_codec
        ext = self.audio_codec
        pkg_dir = self.output_dir / "packages" / book_id / window_id
        pkg_dir.mkdir(parents=True, exist_ok=True)

        manifest = ReaderPackageManifest(
            book_id=book_id, title=window_id,
            segmenter_version=SEGMENTER_VERSION, audio_codec=codec,
        )
        timing_json_str = json.dumps([t.model_dump() for t in timing], ensure_ascii=False)
        voices_json = json.dumps(
            [v.model_dump() for v in voice_assignments.values()], ensure_ascii=False,
        )

        audio_manifest_json = ""
        if audio_paths:
            adir = pkg_dir / "audio"
            adir.mkdir(parents=True, exist_ok=True)
            apath = adir / f"{window_id}.{ext}"
            if self.audio_codec == "mp3":
                assemble_chapter_mp3(
                    segment_ids=[s.segment_id for s in window_segments],
                    audio_paths=audio_paths, timing_entries=timing,
                    output_path=apath, temp_dir=pkg_dir,
                )
            else:
                assemble_chapter_wav(
                    segment_ids=[s.segment_id for s in window_segments],
                    audio_paths=audio_paths, timing_entries=timing,
                    output_path=apath, temp_dir=pkg_dir,
                )
            str(apath)
            audio_manifest_json = json.dumps({
                "chapters": [{
                    "chapter_id": window_id,
                    "audio_file": f"audio/{apath.name}",
                    "codec": codec,
                    "duration_ms": compute_chapter_duration_ms(timing),
                }],
                "segments": [
                    {
                        "segment_id": sid,
                        "source_file": str(Path(audio_paths[sid]).name),
                        "engine": self.tts_engine,
                        "duration_ms": audio_durations.get(sid, 800),
                    }
                    for sid in [s.segment_id for s in window_segments]
                    if sid in audio_paths
                ],
            }, ensure_ascii=False)

        win_seg_jsonl = "\n".join(
            json.dumps(s.model_dump(), ensure_ascii=False) for s in window_segments
        )
        win_plan_jsonl = "\n".join(
            json.dumps(p.model_dump(), ensure_ascii=False) for p in window_plan
        )
        self.pkg_service.build_reader_package(
            output_dir=str(pkg_dir), manifest=manifest,
            cleaned_html=cleaned_html,
            segments_jsonl=win_seg_jsonl,
            reading_plan_jsonl=win_plan_jsonl,
            voices_json=voices_json,
            timing_json=timing_json_str,
            audio_manifest_json=audio_manifest_json,
        )

        # --- commit window_package artifact with RenderWindow metadata (atomic) ---
        rw_meta = {
            "window_id": window_id,
            "book_id": book_id,
            "chapter_id": chapter_id,
            "segment_ids": [s.segment_id for s in window_segments],
            "target_count": len(window_segments),
            "status": "playable",
            "package_dir": str(pkg_dir),
            "audio_manifest_path": f"{pkg_dir}/audio_manifest.json",
            "timing_path": f"{pkg_dir}/timing.json",
        }
        win_pkg_ver = self._commit_artifact(
            book_id, "window_package", chapter_id,
            file_path=str(pkg_dir),
            input_hash=hashlib.sha256(window_id.encode()).hexdigest()[:40],
            metadata=rw_meta,
        )
        # Wire window_package dependencies
        for dep_v, role in (
            (committed_seg_ver, "segments"),
            (committed_plan_ver, "reading_plan"),
        ):
            self.store.add_dependency(book_id, win_pkg_ver, dep_v, role)
        if voice_artifact_vid:
            self.store.add_dependency(
                book_id, win_pkg_ver, voice_artifact_vid, "voice_assignment",
            )
        if adaptation_ops_ver:
            self.store.add_dependency(
                book_id, win_pkg_ver, adaptation_ops_ver, "adaptation_ops",
            )
        for at_vid in audio_take_vids:
            self.store.add_dependency(
                book_id, win_pkg_ver, at_vid, "audio_take",
            )

        result.success = True
        result.package_dir = str(pkg_dir)
        result.timing = timing
        result.cleaned_html = cleaned_html
        await self._emit("chapter_done", {
            "book_id": book_id, "chapter_id": chapter_id,
            "window_id": window_id, "package_dir": str(pkg_dir),
        })
        return result

    async def bake_chapter(
        self, book_id: str, chapter_id: str, force: bool = False,
    ) -> BakeResult:
        result = BakeResult(
            book_id=book_id,
            chapter_id=chapter_id,
            generation_config_id=self.generation_config_id,
            reading_profile=self.reading_profile,
        )

        # Cache check: if an active reader_package exists AND deps are fresh, skip
        if not force:
            existing = self.store.get_active_artifact(book_id, "reader_package", chapter_id)
            if existing:
                version_id = existing["artifact_version_id"]
                deps = self.store.get_artifact_dependencies(book_id, version_id)
                dep_check = self.store.check_dependencies_active(book_id, version_id)
                pkg_dir = existing.get("file_path", "")
                package_validation = self.harness.validate(
                    "reader_package",
                    {"package_dir": pkg_dir, "require_audio": True},
                )
                if (
                    deps
                    and dep_check["all_active"]
                    and package_validation.decision == GateDecision.pass_decision
                ):
                    result.success = True
                    result.package_dir = pkg_dir
                    self._hydrate_cached_result(result, Path(pkg_dir))
                    await self._emit("cache_hit", {
                        "book_id": book_id, "chapter_id": chapter_id,
                        "artifact_version": version_id,
                    })
                    return result

        await self._emit("segment_start", {"book_id": book_id, "chapter_id": chapter_id})

        paragraphs = self.store.get_paragraphs(book_id, chapter_id)
        if not paragraphs:
            result.errors.append(f"No paragraphs found for {chapter_id}")
            result.success = False
            await self._emit("chapter_error", dict(
                book_id=book_id, chapter_id=chapter_id, error="no paragraphs",
            ))
            return result

        self.pronunciation.set_book(book_id, self.store)
        book_model = BookModel(self.store, book_id)
        all_segments = []
        adapted_texts: dict[str, str] = {}
        all_adaptation_ops: list[TextAdaptationOperation] = []

        # Phase A: pre-segment rule-based adaptation + collect adapted paragraphs
        adapted_paragraphs = []
        for p in paragraphs:
            pre_result = self.adapter.adapt_pre_segment(
                f"{p['paragraph_id']}_pre", p["text"],
            )
            if pre_result.operations:
                all_adaptation_ops.extend(pre_result.operations)
            adapted_paragraphs.append({
                "paragraph_id": p["paragraph_id"],
                "text": pre_result.adapted_text,
                "source_href": p.get("source_href", ""),
                "source_order": p.get("source_order", 0),
                "source_dom_hint": p.get("source_dom_hint", ""),
            })

        # Phase B: LLM-driven adaptation (skip if no real LLM or policy=off)
        if self.llm_adapter and self.llm._default_backend != "mock":
            try:
                llm_result = await self.llm_adapter.adapt_paragraphs_batch(
                    adapted_paragraphs,
                )
                if llm_result.operations:
                    all_adaptation_ops.extend(llm_result.operations)
            except Exception:
                import logging
                logging.getLogger("vn_core").warning(
                    "LLM adaptation failed for %s/%s, continuing with rule-based only",
                    book_id, chapter_id, exc_info=True,
                )

        self._apply_paragraph_operations(adapted_paragraphs, all_adaptation_ops)

        # Phase C: segment + pre-tts adaptation
        for ap in adapted_paragraphs:
            segs = self.segmenter.segment_paragraph(
                ap["paragraph_id"], ap["text"],
                source_href=ap["source_href"],
                source_order=ap["source_order"],
                source_dom_hint=ap["source_dom_hint"],
            )
            all_segments.extend(segs)
            for seg in segs:
                tts_base = self._apply_tts_operations(
                    seg.text,
                    all_adaptation_ops,
                    seg.segment_id,
                    seg.paragraph_id,
                )
                tts_result = self.adapter.adapt_pre_tts(seg.segment_id, tts_base)
                if tts_result.operations:
                    all_adaptation_ops.extend(tts_result.operations)
                adapted_texts[seg.segment_id] = tts_result.adapted_text

        # Persist adaptation operations via Harness StageResult (idempotent)
        adaptation_ops_ver = ""
        if all_adaptation_ops:
            from vn_core.contracts.stage_result import StageResult
            ops_data = [
                op.model_dump() if hasattr(op, "model_dump") else op
                for op in all_adaptation_ops
            ]
            adapt_hash = hashlib.sha256(
                json.dumps(ops_data, ensure_ascii=False, sort_keys=True).encode(),
            ).hexdigest()[:40]

            # Idempotent: reuse version if content unchanged
            existing_adapt = self.store.get_active_artifact(
                book_id, "adaptation_ops", chapter_id,
            )
            if existing_adapt and existing_adapt.get("input_hash") == adapt_hash:
                adaptation_ops_ver = existing_adapt["artifact_version_id"]
            else:
                ops_artifact_vid = self._next_artifact_version(
                    book_id, "adaptation_ops", chapter_id,
                )
                stage_result = StageResult(
                    stage="adaptation",
                    book_id=book_id,
                    unit_id=chapter_id,
                    proposed_artifacts=[{
                        "artifact_type": "adaptation_ops",
                        "artifact_version_id": ops_artifact_vid,
                        "unit_id": chapter_id,
                        "data": ops_data,
                        "input_hash": adapt_hash,
                    }],
                    decisions=[
                        {
                            "segment_id": op.get("segment_id", chapter_id),
                            "decision_type": (
                                f"text_adaptation:{op.get('op_id', chapter_id)}"
                            ),
                            "value": op,
                            "confidence": op.get("confidence", 0.99),
                            "source": op.get("source", "rule"),
                            "evidence": op.get("evidence", []),
                        }
                        for op in ops_data
                        if op.get("segment_id")
                    ],
                    dependencies=[],
                    provenance={
                        "stage": "adaptation",
                        "unit_id": chapter_id,
                        "artifact_version_id": ops_artifact_vid,
                        "generation_config_id": self.generation_config_id,
                        "reading_profile": self.reading_profile,
                    },
                    metrics={"operation_count": len(all_adaptation_ops)},
                )
                csr_result = self.harness.commit_stage_result(
                    self.store, stage_result,
                )
                if csr_result.decision == "pass":
                    adaptation_ops_ver = ops_artifact_vid
                else:
                    err_msg = (
                        f"Harness rejected adaptation_ops: {csr_result.reason}"
                    )
                    result.errors.append(err_msg)
                    result.success = False
                    await self._emit("chapter_error", dict(
                        book_id=book_id, chapter_id=chapter_id, error=err_msg,
                    ))
                    self.harness.write_exception(
                        store=self.store, book_id=book_id, unit_id=chapter_id,
                        stage="adaptation", exception_type="schema_error",
                        message=err_msg,
                    )
                    return result

        if not all_segments:
            result.errors.append("No segments produced")
            result.success = False
            await self._emit("chapter_error", dict(
                book_id=book_id, chapter_id=chapter_id, error="no segments",
            ))
            return result

        result.segments = all_segments
        await self._emit("segment_done", dict(
            book_id=book_id, chapter_id=chapter_id, segments=len(all_segments),
        ))

        # Stage: plan
        await self._emit("plan_start", {"book_id": book_id, "chapter_id": chapter_id})
        planner_with_model = ReadingPlanner(llm=self.llm, book_model=book_model)
        plan = await planner_with_model.plan_chapter(all_segments, chapter_id)
        plan = self._apply_reading_profile(plan)
        result.plan = plan

        for entry in plan:
            self.harness.write_decision(
                store=self.store,
                book_id=book_id,
                segment_id=entry.segment_id,
                decision_type="speaker",
                value={
                    "speaker_id": entry.speaker_id,
                    "confidence": entry.speaker_confidence,
                },
                confidence=entry.speaker_confidence,
                source="planner",
                evidence=entry.evidence,
            )
        await self._emit("plan_done", dict(
            book_id=book_id, chapter_id=chapter_id, plan_entries=len(plan),
        ))

        # Stage: voice casting
        voice_assignments = cast_all_characters(
            plan_entries=plan,
            voice_registry=self.voice_registry,
            store=self.store,
            book_id=book_id,
        )
        result.voice_assignments = {
            k: v.model_dump() for k, v in voice_assignments.items()
        }

        # Commit voice assignments via Harness — so they become a versioned artifact
        va_list = [
            {
                "character_id": va.character_id,
                "voice_id": va.voice_id,
                "confidence": va.confidence,
                "user_locked": va.user_locked,
                "source": va.source,
                "status": "user_locked" if va.user_locked else "inferred",
            }
            for va in voice_assignments.values()
        ]
        # Idempotent: reuse existing version if voice assignments haven't changed
        va_hash = hashlib.sha256(
            json.dumps(sorted(va_list, key=lambda x: x.get("character_id", "")),
                       ensure_ascii=False).encode(),
        ).hexdigest()[:40]
        existing_va = self.store.get_active_artifact(
            book_id, "voice_assignment", chapter_id,
        )
        if existing_va and existing_va.get("input_hash") == va_hash:
            voice_artifact_vid = existing_va["artifact_version_id"]
        else:
            voice_artifact_vid = self._next_artifact_version(
                book_id, "voice_assignment", chapter_id,
            )
            va_commit = self.harness.commit_voice_assignments(
                store=self.store,
                book_id=book_id,
                unit_id=chapter_id,
                assignments=va_list,
                generation_config_id=self.generation_config_id,
                artifact_version_id=voice_artifact_vid,
            )
            if va_commit.decision != "pass":
                voice_artifact_vid = ""
                # Non-fatal: bake can continue with fallback voices
                result.errors.append(
                    f"Voice assignment commit rejected: {va_commit.reason}",
                )

        # Stage: context fetch
        context_spec = ContextSpec(
            task="tts_render",
            segment_ids=[s.segment_id for s in all_segments[:100]],
            chapter_id=chapter_id,
            scene_state=True,
        )
        fetch_engine = ContextFetchEngine(self.store, book_model)
        fetch_engine.fetch(context_spec)

        # Commit segments + plan + voice + adaptation artifacts BEFORE TTS so
        # that audio_take dependencies point to real committed versions.
        seg_validation = self.harness.validate("segments", all_segments)
        if seg_validation.decision == GateDecision.fail_decision:
            result.errors.append(f"Segment validation failed: {seg_validation.reason}")
            result.success = False
            await self._emit("chapter_error", dict(
                book_id=book_id, chapter_id=chapter_id,
                error=f"segment_validation: {seg_validation.reason}",
            ))
            self.harness.write_exception(
                store=self.store, book_id=book_id, unit_id=chapter_id,
                stage="segment", exception_type="segment_validation",
                message=seg_validation.reason,
            )
            return result

        plan_validation = self.harness.validate("reading_plan", plan)
        if plan_validation.decision == GateDecision.fail_decision:
            result.errors.append(f"Plan validation failed: {plan_validation.reason}")
            result.success = False
            await self._emit("chapter_error", dict(
                book_id=book_id, chapter_id=chapter_id,
                error=f"plan_validation: {plan_validation.reason}",
            ))
            self.harness.write_exception(
                store=self.store, book_id=book_id, unit_id=chapter_id,
                stage="planning", exception_type="plan_validation",
                message=plan_validation.reason,
            )
            return result

        # Commit all pre-TTS artifacts now
        segments_jsonl = "\n".join(
            json.dumps(s.model_dump(), ensure_ascii=False) for s in all_segments
        )
        reading_plan_jsonl = "\n".join(
            json.dumps(p.model_dump(), ensure_ascii=False) for p in plan
        )
        seg_input_hash = hashlib.sha256(segments_jsonl.encode()).hexdigest()[:40]
        plan_input_hash = hashlib.sha256(reading_plan_jsonl.encode()).hexdigest()[:40]

        committed_seg_ver = self._commit_artifact_idempotent(
            book_id, "segments", chapter_id,
            file_path="",
            input_hash=seg_input_hash,
        )
        committed_plan_ver = self._commit_artifact_idempotent(
            book_id, "reading_plan", chapter_id,
            file_path="",
            input_hash=plan_input_hash,
        )
        committed_voice_ver = voice_artifact_vid  # already committed
        committed_adapt_ver = adaptation_ops_ver  # already committed

        # Stage: TTS synthesis (concurrent, with audio_take cache)
        await self._emit("tts_start", dict(
            book_id=book_id, chapter_id=chapter_id, segments=len(plan),
        ))
        audio_durations: dict[str, int] = {}
        semaphore = asyncio.Semaphore(self.concurrent_tts)

        # Content-based cache key: does NOT use artifact version numbers.
        # Same text + voice + engine + style + config = same key, always.
        from vn_core.orchestration.cache_keys import audio_take_cache_key as _at_key

        cache_hit_count = 0

        async def _synthesize_one(entry):
            nonlocal cache_hit_count
            va = voice_assignments.get(entry.speaker_id)
            voice_id = (
                va.voice_id
                if va
                else self.voice_registry.get_fallback_voice("narrator")
            )
            tts_text = adapted_texts.get(entry.segment_id, entry.text)

            tts_request = self.tts_composer.compose(
                segment_id=entry.segment_id,
                tts_base_text=tts_text,
                voice_id=voice_id,
                engine=self.tts_engine,
                reading_style=entry.reading_style.model_dump(),
                prosody_hint=entry.reading_style.prosody_hint,
                format=self.audio_codec,
            )

            # Content-based cache key — stable across bakes with same inputs.
            # It uses final BackendSpeechRequest.text after pronunciation
            # normalization, so lexicon changes invalidate stale audio.
            at_cache_key = _at_key(
                segment_id=entry.segment_id,
                text=tts_request.text,
                voice_id=voice_id,
                engine=self.tts_engine,
                reading_style=entry.reading_style.model_dump(),
                generation_config_id=self.generation_config_id,
                format=tts_request.format,
                pronunciation=self._pronunciation_cache_context(),
            )
            cached_at = self.store.find_artifact_by_cache_key(
                book_id, "audio_take", at_cache_key,
            )
            if cached_at:
                cached_path = cached_at.get("file_path", "")
                cache_file_ok = cached_path and Path(cached_path).exists()
                dep_ok = self.store.check_dependencies_active(
                    book_id, cached_at["artifact_version_id"],
                )
                if cache_file_ok and dep_ok["all_active"]:
                    cache_hit_count += 1
                    await self._emit("tts_cache_hit", {
                        "book_id": book_id, "chapter_id": chapter_id,
                        "segment_id": entry.segment_id,
                        "artifact_version_id": cached_at["artifact_version_id"],
                    })
                    measured = get_audio_duration_ms(cached_path)
                    return entry.segment_id, None, cached_path, (
                        measured if measured is not None else 800
                    ), at_cache_key

            async with semaphore:
                tts_result = await self.tts_gateway.synthesize(tts_request)
            return entry.segment_id, tts_result, "", 0, at_cache_key

        completed_tts = 0
        total_tts = len(plan)

        async def _tracked_run(entry):
            nonlocal completed_tts
            try:
                result_val = await _synthesize_one(entry)
            except Exception:
                completed_tts += 1
                raise
            completed_tts += 1
            await self._emit("tts_progress", {
                "book_id": book_id, "chapter_id": chapter_id,
                "completed": completed_tts, "total": total_tts,
                "segment_id": entry.segment_id,
            })
            return result_val

        tracked_tasks = [_tracked_run(entry) for entry in plan]
        results = await asyncio.gather(*tracked_tasks, return_exceptions=True)
        audio_paths: dict[str, str] = {}
        tts_results: dict[str, object] = {}
        for r in results:
            if isinstance(r, Exception):
                result.errors.append(str(r))
                continue
            seg_id, tts_result, cached_path, cached_dur, at_ck = r

            if cached_path:
                # Cache hit — reuse existing audio
                audio_paths[seg_id] = cached_path
                audio_durations[seg_id] = cached_dur
                continue

            tts_results[seg_id] = tts_result
            measured_duration = (
                get_audio_duration_ms(tts_result.audio_path)
                if tts_result.status == "success" and tts_result.audio_path
                else None
            )
            audio_durations[seg_id] = (
                measured_duration
                if measured_duration is not None
                else int(tts_result.duration_ms)
                if tts_result.status == "success"
                else 800
            )
            if tts_result.status == "success" and tts_result.audio_path:
                audio_paths[seg_id] = tts_result.audio_path
                # Write audio_take artifact for future cache reuse.
                # Dependencies point to REAL committed artifact versions.
                at_vid = self._next_artifact_version(
                    book_id, "audio_take", seg_id,
                )
                self.store.write_artifact(
                    book_id=book_id,
                    artifact_version_id=at_vid,
                    artifact_type="audio_take",
                    unit_id=seg_id,
                    file_path=tts_result.audio_path,
                    input_hash=at_ck,
                )
                at_deps = [
                    (committed_seg_ver, "segments"),
                    (committed_plan_ver, "reading_plan"),
                ]
                if committed_voice_ver:
                    at_deps.append((committed_voice_ver, "voice_assignment"))
                if committed_adapt_ver:
                    at_deps.append((committed_adapt_ver, "adaptation_ops"))
                for dep_v, role in at_deps:
                    self.store.add_dependency(book_id, at_vid, dep_v, role)

        await self._emit("tts_done", dict(
            book_id=book_id, chapter_id=chapter_id, audio_segments=len(audio_paths),
        ))

        missing_audio = [entry.segment_id for entry in plan if entry.segment_id not in audio_paths]
        if missing_audio:
            err_msg = (
                f"TTS synthesis missing audio for {len(missing_audio)} "
                f"of {len(plan)} segments; first: {missing_audio[:3]}"
            )
            result.errors.append(err_msg)
            result.success = False
            await self._emit("chapter_error", dict(
                book_id=book_id, chapter_id=chapter_id, error=err_msg,
            ))
            self.harness.write_exception(
                store=self.store, book_id=book_id, unit_id=chapter_id,
                stage="tts_render", exception_type="tts_partial_failed",
                message=err_msg,
            )
            return result

        # Stage: timing
        await self._emit("timing_start", {"book_id": book_id, "chapter_id": chapter_id})
        chapter_audio_codec = self.audio_codec
        timing = build_timing(
            segment_ids=[s.segment_id for s in all_segments],
            segment_durations_ms=[
                audio_durations.get(s.segment_id, 800) for s in all_segments
            ],
            chapter_audio=f"audio/{chapter_id}.{chapter_audio_codec}",
        )
        result.timing = timing
        await self._emit("timing_done", dict(
            book_id=book_id, chapter_id=chapter_id, timing_entries=len(timing),
        ))

        # Stage: XHTML generation
        await self._emit("xhtml_start", {"book_id": book_id, "chapter_id": chapter_id})
        cleaned_body = generate_cleaned_html(
            chapter_id=chapter_id,
            segments=all_segments,
            adapted_texts=None,  # never leak tts_only adaptations into display
        )
        cleaned_html = wrap_full_document(cleaned_body, book_id=book_id)
        result.cleaned_html = cleaned_html
        await self._emit("xhtml_done", {"book_id": book_id, "chapter_id": chapter_id})

        # Stage: packaging
        await self._emit("package_start", {"book_id": book_id, "chapter_id": chapter_id})
        manifest = ReaderPackageManifest(
            book_id=book_id,
            title=chapter_id,
            segmenter_version=SEGMENTER_VERSION,
            audio_codec=chapter_audio_codec,
        )
        segments_jsonl = "\n".join(
            json.dumps(s.model_dump(), ensure_ascii=False) for s in all_segments
        )
        reading_plan_jsonl = "\n".join(
            json.dumps(p.model_dump(), ensure_ascii=False) for p in plan
        )
        voices_json = json.dumps(
            [v.model_dump() for v in voice_assignments.values()],
            ensure_ascii=False,
        )
        timing_json = json.dumps(
            [t.model_dump() for t in timing], ensure_ascii=False,
        )

        pkg_dir = self.output_dir / "packages" / book_id / chapter_id
        audio_manifest_json = ""
        chapter_audio_file_path = ""
        if audio_paths:
            audio_dir = pkg_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            codec = self.audio_codec
            chapter_audio_ext = self.audio_codec
            chapter_audio_path = audio_dir / f"{chapter_id}.{chapter_audio_ext}"
            try:
                if self.audio_codec == "mp3":
                    assemble_chapter_mp3(
                        segment_ids=[s.segment_id for s in all_segments],
                        audio_paths=audio_paths,
                        timing_entries=timing,
                        output_path=chapter_audio_path,
                        temp_dir=audio_dir,
                    )
                else:
                    assemble_chapter_wav(
                        segment_ids=[s.segment_id for s in all_segments],
                        audio_paths=audio_paths,
                        timing_entries=timing,
                        output_path=chapter_audio_path,
                        temp_dir=audio_dir,
                    )
                chapter_audio_file_path = str(chapter_audio_path)
                audio_manifest_json = json.dumps(
                    {
                        "chapters": [
                            {
                                "chapter_id": chapter_id,
                                "audio_file": f"audio/{chapter_audio_path.name}",
                                "codec": codec,
                                "duration_ms": compute_chapter_duration_ms(timing),
                            }
                        ],
                        "segments": [
                            {
                                "segment_id": seg_id,
                                "source_file": str(Path(audio_paths[seg_id]).name),
                                "engine": getattr(tts_results.get(seg_id), "engine", ""),
                                "duration_ms": audio_durations.get(seg_id, 800),
                            }
                            for seg_id in [s.segment_id for s in all_segments]
                            if seg_id in audio_paths
                        ],
                    },
                    ensure_ascii=False,
                )
            except Exception as e:
                result.errors.append(f"Chapter audio assembly failed: {e}")

        pkg_dir = self.pkg_service.build_reader_package(
            output_dir=str(pkg_dir),
            manifest=manifest,
            cleaned_html=cleaned_html,
            segments_jsonl=segments_jsonl,
            reading_plan_jsonl=reading_plan_jsonl,
            voices_json=voices_json,
            audio_manifest_json=audio_manifest_json,
            timing_json=timing_json,
        )
        result.package_dir = str(pkg_dir)

        # Segments + plan already validated and committed before TTS.
        # Now validate + commit post-TTS artifacts: timing, package.
        await self._emit("harness_validating", {"book_id": book_id, "chapter_id": chapter_id})

        timing_validation = self.harness.validate("timing", timing)
        if timing_validation.decision == GateDecision.fail_decision:
            result.errors.append(f"Timing validation failed: {timing_validation.reason}")
            result.success = False
            await self._emit("chapter_error", dict(
                book_id=book_id, chapter_id=chapter_id,
                error=f"timing_validation: {timing_validation.reason}",
            ))
            self.harness.write_exception(
                store=self.store, book_id=book_id, unit_id=chapter_id,
                stage="timing_build", exception_type="timing_validation",
                message=timing_validation.reason,
            )
            return result

        # If TTS was attempted but produced zero audio, fail the bake.
        if plan and not audio_paths:
            err_msg = "TTS synthesis produced no audio for any segment"
            result.errors.append(err_msg)
            result.success = False
            await self._emit("chapter_error", dict(
                book_id=book_id, chapter_id=chapter_id, error=err_msg,
            ))
            self.harness.write_exception(
                store=self.store, book_id=book_id, unit_id=chapter_id,
                stage="tts_render", exception_type="tts_all_failed",
                message=err_msg,
            )
            return result

        package_validation = self.harness.validate(
            "reader_package",
            {"package_dir": str(pkg_dir), "require_audio": True},
        )
        if package_validation.decision == GateDecision.fail_decision:
            result.errors.append(f"Package validation failed: {package_validation.reason}")
            result.success = False
            await self._emit("chapter_error", dict(
                book_id=book_id, chapter_id=chapter_id,
                error=f"package_validation: {package_validation.reason}",
            ))
            self.harness.write_exception(
                store=self.store, book_id=book_id, unit_id=chapter_id,
                stage="packaging", exception_type="package_validation",
                message=package_validation.reason,
            )
            return result

        # Commit post-TTS artifacts (segments/plan already committed before TTS)
        timing_ver = self._commit_artifact(
            book_id, "timing", chapter_id,
            file_path=str(pkg_dir / "timing.json"),
            input_hash=hashlib.sha256(timing_json.encode()).hexdigest()[:40],
        )
        html_ver = self._commit_artifact(
            book_id, "cleaned_html", chapter_id,
            file_path=str(pkg_dir / "cleaned.html"),
            input_hash=hashlib.sha256(cleaned_html.encode()).hexdigest()[:40],
        )
        chapter_audio_ver = ""
        if chapter_audio_file_path:
            chapter_audio_ver = self._commit_artifact(
                book_id, "chapter_audio", chapter_id,
                file_path=chapter_audio_file_path,
            )
        package_ver = self._commit_artifact(
            book_id, "reader_package", chapter_id,
            file_path=str(pkg_dir),
        )
        # Wire dependencies using the already-committed versions
        self.store.add_dependency(
            book_id, committed_plan_ver, committed_seg_ver, "segments",
        )
        self.store.add_dependency(book_id, timing_ver, committed_seg_ver, "segments")
        if chapter_audio_ver:
            self.store.add_dependency(book_id, timing_ver, chapter_audio_ver, "chapter_audio")
        self.store.add_dependency(book_id, html_ver, committed_seg_ver, "segments")
        for dep_ver, role in (
            (committed_seg_ver, "segments"),
            (committed_plan_ver, "reading_plan"),
            (timing_ver, "timing"),
            (html_ver, "cleaned_html"),
            (chapter_audio_ver, "chapter_audio"),
            (adaptation_ops_ver, "adaptation_ops"),
            (voice_artifact_vid, "voice_assignment"),
        ):
            if dep_ver:
                self.store.add_dependency(book_id, package_ver, dep_ver, role)

        self.harness.write_provenance(
            store=self.store, unit_id=chapter_id,
            stage="segment", artifact_version_id=committed_seg_ver,
            generation_config_id=self.generation_config_id,
            output_hash=hashlib.sha256(segments_jsonl.encode()).hexdigest()[:40],
            reading_profile=self.reading_profile,
        )
        self.harness.write_provenance(
            store=self.store, unit_id=chapter_id,
            stage="planning", artifact_version_id=committed_plan_ver,
            generation_config_id=self.generation_config_id,
            output_hash=hashlib.sha256(reading_plan_jsonl.encode()).hexdigest()[:40],
            reading_profile=self.reading_profile,
        )
        if chapter_audio_ver:
            self.harness.write_provenance(
                store=self.store, unit_id=chapter_id,
                stage="tts_render", artifact_version_id=chapter_audio_ver,
                generation_config_id=self.generation_config_id,
                reading_profile=self.reading_profile,
            )
        self.harness.write_provenance(
            store=self.store, unit_id=chapter_id,
            stage="packaging", artifact_version_id=package_ver,
            generation_config_id=self.generation_config_id,
            reading_profile=self.reading_profile,
        )

        result.success = True
        await self._emit("chapter_done", {
            "book_id": book_id, "chapter_id": chapter_id,
            "segments": len(all_segments), "plan_entries": len(plan),
            "timing_entries": len(timing), "package_dir": str(pkg_dir),
        })
        return result

    def _apply_paragraph_operations(
        self,
        adapted_paragraphs: list[dict],
        operations: list[TextAdaptationOperation],
    ):
        """Apply approved display operations before segmentation."""
        if not operations:
            return

        for paragraph in adapted_paragraphs:
            paragraph_id = paragraph["paragraph_id"]
            paragraph["text"] = self._apply_operations_for_targets(
                paragraph["text"],
                operations,
                targets={paragraph_id},
                allowed_scopes={
                    AdaptationScope.display_and_tts.value,
                    AdaptationScope.display_only.value,
                },
            )

    def _apply_tts_operations(
        self,
        text: str,
        operations: list[TextAdaptationOperation],
        segment_id: str,
        paragraph_id: str,
    ) -> str:
        """Apply TTS-only operations after segmentation."""
        if not operations:
            return text
        return self._apply_operations_for_targets(
            text,
            operations,
            targets={segment_id, paragraph_id},
            allowed_scopes={AdaptationScope.tts_only.value},
        )

    @staticmethod
    def _apply_operations_for_targets(
        text: str,
        operations: list[TextAdaptationOperation],
        targets: set[str],
        allowed_scopes: set[str],
    ) -> str:
        result = text
        for op in operations:
            target = getattr(op, "segment_id", "")
            scope = getattr(op, "scope", "")
            if isinstance(scope, AdaptationScope):
                scope_value = scope.value
            else:
                scope_value = str(scope)
            if target not in targets or scope_value not in allowed_scopes:
                continue
            original = getattr(op, "original", "")
            normalized = getattr(op, "normalized", "")
            if original and original in result:
                result = result.replace(original, normalized, 1)
        return result

    def _pronunciation_cache_context(self) -> dict:
        return {
            "system_lexicon_version": self.pronunciation.system_version,
            "user_lexicon_version": self.pronunciation.user_version,
            "pronunciation_fingerprint": self.pronunciation.cache_fingerprint,
        }

    def _apply_reading_profile(self, plan: list) -> list:
        if self.reading_profile == "enhanced":
            return plan

        return [
            entry.model_copy(
                update={
                    "speaker_candidate": None,
                    "speaker_id": "char_narrator",
                    "speaker_confidence": 1.0,
                    "reading_style": ReadingStyle(),
                    "enhancements": Enhancements(),
                    "voice_constraints": VoiceConstraints(),
                    "evidence": ["reading_profile=faithful"],
                    "fallback_policy": "use_narrator",
                }
            )
            for entry in plan
        ]

    def _next_artifact_version(
        self, book_id: str, artifact_type: str, unit_id: str,
    ) -> str:
        """Compute the next artifact version ID without writing."""
        conn = self.store._get_conn()
        rows = conn.execute(
            """SELECT artifact_version_id FROM artifacts
            WHERE book_id=? AND artifact_type=? AND unit_id=?""",
            (book_id, artifact_type, unit_id),
        ).fetchall()
        prefix = f"{book_id}_{artifact_type}_{unit_id}_v"
        max_counter = 0
        for row in rows:
            version_id = row[0]
            if not version_id.startswith(prefix):
                continue
            try:
                max_counter = max(max_counter, int(version_id.rsplit("_v", 1)[1]))
            except (IndexError, ValueError):
                continue
        counter = max_counter + 1
        return f"{book_id}_{artifact_type}_{unit_id}_v{counter:03d}"

    def _hydrate_cached_result(self, result: BakeResult, pkg_dir: Path):
        segments_path = pkg_dir / "segments.jsonl"
        if segments_path.exists():
            result.segments = [
                Segment(**json.loads(line))
                for line in segments_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        timing_path = pkg_dir / "timing.json"
        if timing_path.exists():
            result.timing = [
                TimingEntry(**entry)
                for entry in json.loads(timing_path.read_text(encoding="utf-8"))
            ]

        html_path = pkg_dir / "cleaned.html"
        if html_path.exists():
            result.cleaned_html = html_path.read_text(encoding="utf-8")

    def _commit_artifact_idempotent(
        self, book_id: str, artifact_type: str, unit_id: str,
        file_path: str = "", input_hash: str = "",
    ) -> str:
        """Commit artifact, reusing the existing version if input_hash matches.

        If an active artifact of the same type+unit already exists with the
        same input_hash, its version_id is returned without creating a new
        version.  This keeps dependencies alive across repeated bakes with
        identical content.
        """
        if input_hash:
            existing = self.store.get_active_artifact(book_id, artifact_type, unit_id)
            if existing and existing.get("input_hash") == input_hash:
                return existing["artifact_version_id"]

        version_id = self._next_artifact_version(book_id, artifact_type, unit_id)
        self.harness.commit(
            store=self.store,
            book_id=book_id,
            artifact_type=artifact_type,
            unit_id=unit_id,
            artifact_version_id=version_id,
            file_path=file_path,
            input_hash=input_hash,
        )
        return version_id

    def _commit_artifact(
        self, book_id: str, artifact_type: str, unit_id: str,
        file_path: str = "", input_hash: str = "",
        metadata: dict | None = None,
    ) -> str:
        """Commit artifact with incrementing version. Returns the version ID used."""
        version_id = self._next_artifact_version(book_id, artifact_type, unit_id)

        self.harness.commit(
            store=self.store,
            book_id=book_id,
            artifact_type=artifact_type,
            unit_id=unit_id,
            artifact_version_id=version_id,
            file_path=file_path,
            input_hash=input_hash,
            metadata=metadata,
        )
        return version_id

    def _sync_scan(
        self, scanner: BookScanner, book_id: str,
        chapter_id: str, text: str,
    ) -> dict:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        scanner.scan_chapter(book_id, chapter_id, text),
                    )
                    return future.result(timeout=60)
            else:
                return loop.run_until_complete(
                    scanner.scan_chapter(book_id, chapter_id, text),
                )
        except RuntimeError:
            return asyncio.run(
                scanner.scan_chapter(book_id, chapter_id, text),
            )
