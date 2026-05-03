"""LLM-driven text adaptation for Chinese novels.

Detects typos, de-obfuscation patterns, term inconsistencies, and TTS issues
using an LLM, producing structured TextAdaptationOperation objects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from vn_core.contracts.context_capsule import ContextCapsule
from vn_core.contracts.text_adaptation import (
    AdaptationCategory,
    AdaptationScope,
    TextAdaptationOperation,
)
from vn_core.llm_gateway import LLMGateway, LLMMessage, LLMRequest


class AdaptationPolicy(str, Enum):
    conservative = "conservative"
    balanced = "balanced"
    aggressive = "aggressive"


@dataclass
class AdaptationBatchResult:
    operations: list[TextAdaptationOperation]
    error: str = ""
    cached: bool = False


# Confidence thresholds per policy
POLICY_THRESHOLDS = {
    AdaptationPolicy.conservative: 0.90,
    AdaptationPolicy.balanced: 0.75,
    AdaptationPolicy.aggressive: 0.60,
}

# Categories allowed per policy
POLICY_CATEGORIES = {
    AdaptationPolicy.conservative: {
        AdaptationCategory.basic_cleanup,
        AdaptationCategory.punctuation,
        AdaptationCategory.tts_normalization,
    },
    AdaptationPolicy.balanced: {
        AdaptationCategory.basic_cleanup,
        AdaptationCategory.punctuation,
        AdaptationCategory.typo,
        AdaptationCategory.de_obfuscation,
        AdaptationCategory.terminology,
        AdaptationCategory.dialogue_fix,
        AdaptationCategory.tts_normalization,
    },
    AdaptationPolicy.aggressive: {
        AdaptationCategory.basic_cleanup,
        AdaptationCategory.punctuation,
        AdaptationCategory.typo,
        AdaptationCategory.de_obfuscation,
        AdaptationCategory.terminology,
        AdaptationCategory.dialogue_fix,
        AdaptationCategory.tts_normalization,
    },
}

CATEGORY_MAP: dict[str, AdaptationCategory] = {
    "cleanup": AdaptationCategory.basic_cleanup,
    "punctuation": AdaptationCategory.punctuation,
    "typo_fix": AdaptationCategory.typo,
    "de_obfuscation": AdaptationCategory.de_obfuscation,
    "term_consistency": AdaptationCategory.terminology,
    "dialogue_fix": AdaptationCategory.dialogue_fix,
    "tts_normalization": AdaptationCategory.tts_normalization,
}

SCOPE_MAP: dict[str, AdaptationScope] = {
    "display_and_tts": AdaptationScope.display_and_tts,
    "tts_only": AdaptationScope.tts_only,
    "display_only": AdaptationScope.display_only,
    "suggest_only": AdaptationScope.suggest_only,
}


class LLMTextAdapter:
    """Use LLM to detect and propose text adaptation operations."""

    def __init__(
        self,
        llm: LLMGateway,
        policy: AdaptationPolicy = AdaptationPolicy.balanced,
        batch_size: int = 8,
    ):
        self.llm = llm
        self.policy = policy
        self.batch_size = batch_size

    async def adapt_paragraphs_batch(
        self,
        paragraphs: list[dict],
        context_capsule: ContextCapsule | None = None,
    ) -> AdaptationBatchResult:
        """Adapt multiple paragraph texts in a single LLM call.

        Each dict in paragraphs should have: paragraph_id, text.
        """
        if not paragraphs:
            return AdaptationBatchResult(operations=[])

        all_ops: list[TextAdaptationOperation] = []
        op_counter = [0]

        for i in range(0, len(paragraphs), self.batch_size):
            batch = paragraphs[i:i + self.batch_size]
            result = await self._adapt_batch(batch, context_capsule, op_counter)
            all_ops.extend(result.operations)
            if result.error:
                return AdaptationBatchResult(operations=all_ops, error=result.error)

        return AdaptationBatchResult(operations=all_ops)

    async def adapt_paragraph(
        self,
        paragraph_id: str,
        text: str,
        context_capsule: ContextCapsule | None = None,
    ) -> AdaptationBatchResult:
        """Adapt a single paragraph."""
        result = await self.adapt_paragraphs_batch(
            [{"paragraph_id": paragraph_id, "text": text}],
            context_capsule,
        )
        return result

    async def _adapt_batch(
        self,
        paragraphs: list[dict],
        context_capsule: ContextCapsule | None,
        op_counter: list[int],
    ) -> AdaptationBatchResult:
        """Send a batch of paragraphs to LLM for adaptation."""
        capsule = context_capsule or ContextCapsule(task="text_adaptation")

        # Build context
        character_names = ", ".join(
            c.get("name", c.get("character_id", "?"))
            for c in capsule.active_characters[:5]
        ) or "none"
        scene_summary = capsule.scene_summary or "unknown"
        glossary_terms = ", ".join(
            g.get("term", "?") for g in capsule.glossary_terms[:10]
        ) or "none"
        batch_text = "\n---\n".join(
            f"[{p['paragraph_id']}] {p['text']}" for p in paragraphs
        )

        # Try prompt registry first, fall back to inline prompt
        request = self.llm.build_from_prompt(
            "text_adaptation",
            template_vars={
                "paragraph_text": batch_text,
                "character_names": character_names,
                "scene_summary": scene_summary,
                "glossary_terms": glossary_terms,
            },
            task="text_adaptation",
            temperature=0.1,
            max_tokens=2048,
        )
        if request is None:
            # No prompt registry available — use inline prompt
            prompt = f"""You are a Chinese novel text editor.
Analyze paragraphs and identify text issues
that should be corrected for TTS (text-to-speech) reading and display.

Categories: cleanup, punctuation, typo_fix, de_obfuscation, term_consistency,
dialogue_fix, tts_normalization

For each issue, output a JSON array of operations with: op_id, segment_id
(use the exact bracketed paragraph_id), original, normalized, category, scope
(display_and_tts or tts_only), confidence (0-1), risk, evidence.

Only report issues you are confident about. If the text is clean, return an empty array.
Respond with only a JSON array, no other text.

Paragraphs:
{batch_text}

Context: characters={character_names}, scene={scene_summary}, glossary={glossary_terms}"""
            request = LLMRequest(
                task="text_adaptation",
                messages=[LLMMessage(role="user", content=prompt)],
                temperature=0.1,
                max_tokens=2048,
            )

        response = await self.llm.generate(request)

        if response.error:
            return AdaptationBatchResult(operations=[], error=response.error)

        try:
            raw_ops = json.loads(response.content)
            if not isinstance(raw_ops, list):
                return AdaptationBatchResult(operations=[])

            ops = self._parse_operations(raw_ops, paragraphs, op_counter)
            return AdaptationBatchResult(operations=ops, cached=response.cached)
        except json.JSONDecodeError as e:
            return AdaptationBatchResult(operations=[], error=f"JSON parse error: {e}")

    def _parse_operations(
        self,
        raw_ops: list[dict],
        paragraphs: list[dict],
        op_counter: list[int],
    ) -> list[TextAdaptationOperation]:
        """Parse raw LLM JSON into validated TextAdaptationOperation objects."""
        valid_ids = {p["paragraph_id"] for p in paragraphs}
        threshold = POLICY_THRESHOLDS[self.policy]
        allowed_categories = POLICY_CATEGORIES[self.policy]

        ops: list[TextAdaptationOperation] = []
        for raw in raw_ops:
            category_str = raw.get("category", "")
            category = CATEGORY_MAP.get(category_str)
            if category is None or category not in allowed_categories:
                continue

            confidence = float(raw.get("confidence", 0.0))
            if confidence < threshold:
                continue

            scope_str = raw.get("scope", "display_and_tts")
            scope = SCOPE_MAP.get(scope_str, AdaptationScope.display_and_tts)
            if scope == AdaptationScope.suggest_only:
                continue  # don't auto-apply suggestions

            segment_id = self._resolve_paragraph_id(raw, paragraphs, valid_ids)
            if not segment_id:
                continue

            op_counter[0] += 1
            op = TextAdaptationOperation(
                op_id=raw.get("op_id", f"llm_op_{op_counter[0]:04d}"),
                segment_id=segment_id,
                original=raw.get("original", ""),
                normalized=raw.get("normalized", ""),
                category=category,
                scope=scope,
                confidence=confidence,
                risk=raw.get("risk", "low"),
                evidence=raw.get("evidence", []),
                source="llm_context",
            )
            ops.append(op)

        return ops

    @staticmethod
    def _resolve_paragraph_id(
        raw: dict,
        paragraphs: list[dict],
        valid_ids: set[str],
    ) -> str | None:
        requested = raw.get("segment_id") or raw.get("paragraph_id") or ""
        if requested in valid_ids:
            return requested

        if len(paragraphs) == 1:
            return paragraphs[0]["paragraph_id"]

        original = raw.get("original", "")
        if original:
            matches = [
                p["paragraph_id"]
                for p in paragraphs
                if original in p.get("text", "")
            ]
            if len(matches) == 1:
                return matches[0]

        return None
