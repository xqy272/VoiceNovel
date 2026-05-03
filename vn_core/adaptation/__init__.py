"""Text Adaptation: rule-based pre-segment pass and LLM-assisted operations."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from vn_core.contracts.text_adaptation import (
    AdaptationCategory,
    AdaptationScope,
    TextAdaptationOperation,
)


@dataclass
class AdaptationResult:
    operations: list[TextAdaptationOperation] = field(default_factory=list)
    adapted_text: str = ""


def basic_cleanup(text: str) -> str:
    cleaned = text.replace("\r\n", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = unicodedata.normalize("NFKC", cleaned)
    cleaned = cleaned.strip()
    return cleaned


def fix_punctuation(
    text: str, segment_id_prefix: str = ""
) -> tuple[str, list[TextAdaptationOperation]]:
    ops: list[TextAdaptationOperation] = []
    result = text

    pairs = [
        (r"\u2026{2,}", "\u2026"),
        (r"\u2014{2,}", "\u2014\u2014"),
    ]
    op_idx = 0
    for pattern, replacement in pairs:
        new_result = re.sub(pattern, replacement, result)
        if new_result != result:
            ops.append(
                TextAdaptationOperation(
                    op_id=(
                        f"{segment_id_prefix}_punct_{op_idx:03d}"
                        if segment_id_prefix
                        else f"punct_{op_idx:03d}"
                    ),
                    segment_id=segment_id_prefix,
                    original=result,
                    normalized=new_result,
                    category=AdaptationCategory.punctuation,
                    scope=AdaptationScope.display_and_tts,
                    confidence=0.99,
                    risk="low",
                    evidence=["repeated punctuation normalization"],
                    source="rule",
                )
            )
            op_idx += 1
            result = new_result

    return result, ops


def normalize_numbers_display(
    text: str, segment_id_prefix: str = ""
) -> tuple[str, list[TextAdaptationOperation]]:
    ops: list[TextAdaptationOperation] = []
    result = text

    year_pattern = re.compile(r"(?<!\d)(\d{4})(?!\d)")

    def year_repl(m: re.Match) -> str:
        year = int(m.group(1))
        if 1900 <= year <= 2099:
            return "\u3000".join([d for d in m.group(1)])
        return m.group(0)

    new_result = year_pattern.sub(year_repl, result)
    if new_result != result:
        ops.append(
            TextAdaptationOperation(
                op_id=f"{segment_id_prefix}_num_001" if segment_id_prefix else "num_001",
                segment_id=segment_id_prefix,
                original=result,
                normalized=new_result,
                category=AdaptationCategory.tts_normalization,
                scope=AdaptationScope.tts_only,
                confidence=0.95,
                risk="low",
                evidence=["number readability normalization"],
                source="rule",
            )
        )
        result = new_result

    return result, ops


class TextAdapter:
    def __init__(self, policy: str = "balanced"):
        self.policy = policy

    def adapt_pre_segment(
        self,
        segment_id: str,
        text: str,
    ) -> AdaptationResult:
        all_ops: list[TextAdaptationOperation] = []

        cleaned = basic_cleanup(text)
        if cleaned != text:
            all_ops.append(
                TextAdaptationOperation(
                    op_id=f"{segment_id}_clean_001",
                    segment_id=segment_id,
                    original=text,
                    normalized=cleaned,
                    category=AdaptationCategory.basic_cleanup,
                    scope=AdaptationScope.display_and_tts,
                    confidence=0.99,
                    risk="low",
                    evidence=["whitespace/encoding normalization"],
                    source="rule",
                )
            )

        fixed, punct_ops = fix_punctuation(cleaned, segment_id)
        all_ops.extend(punct_ops)

        return AdaptationResult(operations=all_ops, adapted_text=fixed if fixed else cleaned)

    def adapt_pre_tts(
        self,
        segment_id: str,
        text: str,
    ) -> AdaptationResult:
        all_ops: list[TextAdaptationOperation] = []

        normalized, num_ops = normalize_numbers_display(text, segment_id)
        all_ops.extend(num_ops)

        return AdaptationResult(
            operations=all_ops,
            adapted_text=normalized if normalized else text
        )

    def apply_operations(
        self,
        text: str,
        operations: list[TextAdaptationOperation],
        scope: AdaptationScope | None = None,
    ) -> str:
        result = text
        for op in operations:
            if scope and op.scope != scope and op.scope != AdaptationScope.display_and_tts:
                continue
            if op.scope == AdaptationScope.suggest_only:
                continue
            if op.original in result:
                result = result.replace(op.original, op.normalized, 1)
        return result


# ---------------------------------------------------------------------------
# Replay / Diff / Rollback helpers
# ---------------------------------------------------------------------------


def replay_adaptation_ops(
    source_text: str,
    ops: list[dict],
    scope: str | None = None,
) -> tuple[str, list[str]]:
    """Replay adaptation ops onto source_text and return (result, warnings).

    ``ops`` can be a list of ``TextAdaptationOperation`` or dicts with keys
    ``original``, ``normalized``, ``scope``, ``op_id``.

    If ``scope`` is provided, only ops whose scope matches or is
    ``display_and_tts`` are applied.  ``suggest_only`` ops are always
    skipped.

    Unknown op fields are ignored; malformed ops produce a warning in the
    returned list but do not crash.
    """
    warnings: list[str] = []
    result = source_text
    for op in ops:
        if not isinstance(op, (dict, TextAdaptationOperation)):
            warnings.append(f"skipping non-dict op: {op!r}")
            continue
        try:
            op_scope = op.get("scope") if isinstance(op, dict) else getattr(op, "scope", None)
            op_scope = str(op_scope) if op_scope else ""
        except Exception:
            op_scope = ""

        # Scope filtering
        if scope:
            if op_scope not in (scope, "display_and_tts", "DisplayAndTts", ""):
                continue
        if op_scope in ("suggest_only", "SuggestOnly"):
            continue

        try:
            original = (
                op.get("original") if isinstance(op, dict)
                else getattr(op, "original", "")
            )
            normalized = (
                op.get("normalized") if isinstance(op, dict)
                else getattr(op, "normalized", "")
            )
        except Exception:
            warnings.append(f"skipping malformed op: {op}")
            continue

        if not isinstance(original, str) or not isinstance(normalized, str):
            warnings.append(f"skipping op with non-str fields: {op}")
            continue

        if original in result:
            result = result.replace(original, normalized, 1)
        else:
            op_id = op.get("op_id") if isinstance(op, dict) else getattr(op, "op_id", "?")
            warnings.append(f"original text not found for op {op_id}")

    return result, warnings


def replay_display_text(source_text: str, ops: list[dict]) -> tuple[str, list[str]]:
    """Replay only ops that affect display (excludes tts_only)."""
    return replay_adaptation_ops(source_text, ops, scope="display_and_tts")


def replay_tts_text(source_text: str, ops: list[dict]) -> tuple[str, list[str]]:
    """Replay all ops including tts_only for TTS output."""
    return replay_adaptation_ops(source_text, ops, scope=None)


def diff_text(before: str, after: str) -> dict:
    """Return a simple structured diff between two text strings.

    Returns ``{"before": str, "after": str, "changes": list[dict]}`` where
    each change has ``kind`` (``equal``, ``replace``, ``insert``, ``delete``)
    and the relevant spans.  This is a minimal character-level diff; it is
    not a UI-level patch format.
    """
    changes: list[dict] = []
    i = 0
    j = 0
    while i < len(before) and j < len(after):
        if before[i] == after[j]:
            changes.append({"kind": "equal", "char": before[i]})
            i += 1
            j += 1
        else:
            common_start = i
            while i < len(before) and j < len(after) and before[i] != after[j]:
                i += 1
                j += 1
            changes.append({
                "kind": "replace",
                "before_span": before[common_start:i] if i < len(before) else before[common_start:],
                "after_span": after[common_start:j] if j < len(after) else after[common_start:],
            })
    if i < len(before):
        changes.append({"kind": "delete", "before_span": before[i:]})
    if j < len(after):
        changes.append({"kind": "insert", "after_span": after[j:]})
    return {"before": before, "after": after, "changes": changes}


def rollback_adaptation_ops(
    source_text: str,
    existing_ops: list[dict],
    op_ids_to_revert: set[str],
    stage_reason: str = "rollback",
) -> tuple[list[dict], str]:
    """Generate new operation set that disables specified ops.

    Does NOT delete historical ops. Instead, creates a new list where
    reverted ops are replaced with no-op entries (``original == normalized``)
    and a ``rollback_reason`` annotation.

    Returns ``(new_ops, result_text)``.
    """
    new_ops: list[dict] = []
    text = source_text

    for op in existing_ops:
        op_id = op.get("op_id") if isinstance(op, dict) else getattr(op, "op_id", "")
        if op_id in op_ids_to_revert:
            # Create a no-op that records the rollback
            original = op.get("original") if isinstance(op, dict) else getattr(op, "original", "")
            new_ops.append({
                "op_id": f"{op_id}_rollback",
                "segment_id": (
                    op.get("segment_id", "") if isinstance(op, dict)
                    else getattr(op, "segment_id", "")
                ),
                "original": original,
                "normalized": original,  # no change
                "category": "basic_cleanup",
                "scope": "display_and_tts",
                "confidence": 1.0,
                "risk": "low",
                "evidence": [f"rollback: {stage_reason}"],
                "source": "user",
                "rollback_reason": stage_reason,
            })
        else:
            new_ops.append(dict(op) if isinstance(op, dict) else op)
            # Replay this op into text
            orig = op.get("original") if isinstance(op, dict) else getattr(op, "original", "")
            norm = op.get("normalized") if isinstance(op, dict) else getattr(op, "normalized", "")
            if orig in text:
                text = text.replace(orig, norm, 1)

    return new_ops, text


# ── LLM-driven adaptation (lazy import to avoid circular deps) ───────────

from vn_core.adaptation.llm_adapter import AdaptationPolicy, LLMTextAdapter  # noqa: E402

__all__ = [
    "AdaptationResult", "TextAdapter", "basic_cleanup", "fix_punctuation",
    "replay_adaptation_ops", "replay_display_text", "replay_tts_text",
    "diff_text", "rollback_adaptation_ops",
    "AdaptationPolicy", "LLMTextAdapter",
]
