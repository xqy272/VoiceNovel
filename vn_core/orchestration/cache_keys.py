"""Stable cache key builders for pipeline artifacts.

Every key is deterministic: same inputs produce the same key regardless of
insertion order, runtime state, or Python version.  Use these helpers
instead of ad-hoc hashing in job construction.

Key principles
  - ``None`` and ``""`` are distinct: ``None`` is dropped from the key,
    while ``""`` is kept.  This matches the Orchestrator behaviour.
  - Dict / list inputs are serialised with ``sort_keys=True`` so that key
    order does not matter.
  - ``cache_buster`` is always appended last so that a simple string
    append (rather than a full re-hash) could logically invalidate.

"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _stable_str(value: Any) -> str:
    """Convert *value* to a stable string for hashing."""
    if value is None:
        return "__NONE__"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _build_key(parts: dict[str, Any]) -> str:
    """Build a SHA-256 cache key from a dict of named parts.

    Parts with value ``None`` are skipped.  ``cache_buster``, if
    present, is moved to the end.
    """
    ordered: list[tuple[str, str]] = []
    cache_buster_val = parts.pop("cache_buster", None)

    for k in sorted(parts):
        v = parts[k]
        if v is None:
            continue
        ordered.append((k, _stable_str(v)))

    if cache_buster_val is not None:
        ordered.append(("cache_buster", _stable_str(cache_buster_val)))

    content = "|".join(f"{k}={v}" for k, v in ordered)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:40]


# -- public helpers -----------------------------------------------------------

def reader_package_cache_key(
    book_id: str,
    chapter_id: str,
    generation_config_id: str,
    reading_profile: str,
    execution_mode: str,
    tts_engine: str,
    input_artifact_versions: list[str] | None = None,
    voice_assignment_version: str | None = None,
    adaptation_ops_version: str | None = None,
    cache_buster: str | None = None,
) -> str:
    """Stable cache key for a reader_package job.

    ``input_artifact_versions``, ``voice_assignment_version``, and
    ``adaptation_ops_version`` are included so that a change in any
    upstream artifact invalidates the cache.
    """
    sorted_versions: list[str] | None = None
    if input_artifact_versions:
        sorted_versions = sorted(input_artifact_versions)

    return _build_key({
        "kind": "reader_package",
        "book_id": book_id,
        "chapter_id": chapter_id,
        "generation_config_id": generation_config_id,
        "reading_profile": reading_profile,
        "execution_mode": execution_mode,
        "tts_engine": tts_engine,
        "input_artifact_versions": sorted_versions,
        "voice_assignment_version": voice_assignment_version,
        "adaptation_ops_version": adaptation_ops_version,
        "cache_buster": cache_buster,
    })


def audio_take_cache_key(
    segment_id: str,
    text: str,
    voice_id: str,
    engine: str,
    reading_style: dict | None = None,
    generation_config_id: str = "",
    input_artifact_versions: list[str] | None = None,
    cache_buster: str | None = None,
) -> str:
    """Stable cache key for an audio_take (per-segment TTS) artifact.

    ``reading_style`` is serialised with sorted keys so that dict
    ordering does not affect the key.
    """
    sorted_versions: list[str] | None = None
    if input_artifact_versions:
        sorted_versions = sorted(input_artifact_versions)

    return _build_key({
        "kind": "audio_take",
        "segment_id": segment_id,
        "text": text,
        "voice_id": voice_id,
        "engine": engine,
        "reading_style": reading_style or {},
        "generation_config_id": generation_config_id,
        "input_artifact_versions": sorted_versions,
        "cache_buster": cache_buster,
    })
