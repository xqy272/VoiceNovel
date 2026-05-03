"""VoiceNovel Core: AI multi-role audiobook system core."""

from vn_core.adaptation import AdaptationResult, TextAdapter, basic_cleanup
from vn_core.adaptation.llm_adapter import AdaptationPolicy, LLMTextAdapter
from vn_core.book_model import BookModel
from vn_core.context import ContextFetchEngine
from vn_core.contracts.audio_take import AudioTake
from vn_core.contracts.context_capsule import ContextCapsule
from vn_core.contracts.context_spec import ContextSpec
from vn_core.contracts.exception_entry import ExceptionEntry
from vn_core.contracts.job_state import JobState
from vn_core.contracts.memory_patch import MemoryPatch
from vn_core.contracts.provenance import ProvenanceEntry
from vn_core.contracts.reader_adapter import ReaderAdapterRequest, ReaderAdapterResponse
from vn_core.contracts.reader_manifest import ReaderManifest, ReaderPackageManifest, TimingProfile
from vn_core.contracts.reading_plan import ReadingPlanEntry
from vn_core.contracts.segment import Segment
from vn_core.contracts.speech_request import BackendSpeechRequest
from vn_core.contracts.text_adaptation import TextAdaptationOperation
from vn_core.contracts.timing_entry import TimingEntry
from vn_core.contracts.voice_assignment import VoiceAssignment
from vn_core.cost_planner import CostEstimate, CostPlanner
from vn_core.export.audiobookshelf import export_audiobookshelf
from vn_core.export.daw import export_daw_package
from vn_core.export.m4b import export_m4b
from vn_core.harness import GateDecision, GateResult, HarnessGate
from vn_core.importers import ImportedChapter, SourceParagraph, import_book, import_epub, import_txt
from vn_core.llm_gateway import LLMGateway, LLMMessage, LLMRequest
from vn_core.llm_gateway.backends import (
    AnthropicLLMBackend,
    DeepSeekLLMBackend,
    MockLLMBackend,
    OpenAILLMBackend,
)
from vn_core.orchestration import ExecutionMode, Orchestrator, OrchestratorConfig
from vn_core.packaging import PackagingService
from vn_core.planner import ReadingPlanner
from vn_core.preflight import PreflightCheck, PreflightResult
from vn_core.prompts import PromptDefinition, PromptRegistry
from vn_core.render import (
    CosyVoiceAdapter,
    EdgeTTSAdapter,
    MockTTSAdapter,
    SpeechGateway,
    TTSResult,
)
from vn_core.render.tts_input_composer import TTSInputComposer
from vn_core.scanner import BookScanner
from vn_core.segmenter import SEGMENTER_VERSION, ChineseSegmenter
from vn_core.store import ProjectStore
from vn_core.timing import (
    AudioSpacing,
    assemble_chapter_mp3,
    build_timing,
    compute_chapter_duration_ms,
    convert_wav_to_mp3,
    ffmpeg_available,
)
from vn_core.voice import FALLBACK_VOICES, VoiceRegistry
from vn_core.voice.casting import cast_all_characters, cast_voice
from vn_core.xhtml import generate_cleaned_html, wrap_full_document

__all__ = [
    "AdaptationResult", "TextAdapter", "basic_cleanup",
    "AdaptationPolicy", "LLMTextAdapter",
    "BookModel",
    "CostEstimate", "CostPlanner",
    "AudioTake", "ContextCapsule", "ContextSpec",
    "ExceptionEntry", "JobState", "MemoryPatch", "ProvenanceEntry",
    "ReaderAdapterRequest", "ReaderAdapterResponse",
    "ReaderManifest", "ReaderPackageManifest", "TimingProfile",
    "ReadingPlanEntry", "Segment",
    "BackendSpeechRequest", "TextAdaptationOperation",
    "TimingEntry", "VoiceAssignment",
    "ContextFetchEngine",
    "GateDecision", "GateResult", "HarnessGate",
    "ImportedChapter", "SourceParagraph",
    "import_book", "import_epub", "import_txt",
    "LLMGateway", "LLMMessage", "LLMRequest",
    "AnthropicLLMBackend", "DeepSeekLLMBackend", "MockLLMBackend", "OpenAILLMBackend",
    "ExecutionMode", "Orchestrator", "OrchestratorConfig",
    "PackagingService", "ReadingPlanner",
    "PromptDefinition", "PromptRegistry",
    "PreflightCheck", "PreflightResult",
    "CosyVoiceAdapter", "EdgeTTSAdapter", "MockTTSAdapter", "SpeechGateway", "TTSResult",
    "TTSInputComposer",
    "BookScanner",
    "SEGMENTER_VERSION", "ChineseSegmenter",
    "ProjectStore",
    "AudioSpacing", "assemble_chapter_mp3",
    "build_timing", "compute_chapter_duration_ms",
    "convert_wav_to_mp3", "ffmpeg_available",
    "FALLBACK_VOICES", "VoiceRegistry",
    "cast_all_characters", "cast_voice",
    "export_m4b", "export_audiobookshelf", "export_daw_package",
    "generate_cleaned_html", "wrap_full_document",
]
