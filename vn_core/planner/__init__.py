"""Reading Planner: speaker attribution, reading style, and voice casting guidance."""

from __future__ import annotations

import json
import re

from vn_core.contracts.reading_plan import (
    Enhancements,
    ReadingPlanEntry,
    ReadingStyle,
    VoiceConstraints,
)
from vn_core.contracts.segment import Segment
from vn_core.llm_gateway import LLMGateway, LLMMessage, LLMRequest


class ReadingPlanner:
    def __init__(self, llm: LLMGateway | None = None, book_model=None):
        self.llm = llm or LLMGateway()
        self.book_model = book_model
        self._narrator_id = "char_narrator"

    async def plan_chapter(
        self,
        segments: list[Segment],
        chapter_id: str = "",
        scene_context: dict | None = None,
    ) -> list[ReadingPlanEntry]:
        plan: list[ReadingPlanEntry] = []

        for seg in segments:
            entry = await self._plan_segment(seg, chapter_id, scene_context, plan)
            plan.append(entry)

        plan = self._carry_forward_speakers(plan)
        return plan

    async def _plan_segment(
        self,
        segment: Segment,
        chapter_id: str,
        scene_context: dict | None,
        prior_plan: list[ReadingPlanEntry],
    ) -> ReadingPlanEntry:
        speaker_candidate = self._extract_speaker_candidate(segment.text)
        is_dialogue = segment.is_dialogue_candidate or bool(speaker_candidate)

        if is_dialogue and self.llm._default_backend != "mock":
            entry = await self._llm_attribution(segment, chapter_id, scene_context, prior_plan)
        else:
            entry = self._rule_attribution(segment, speaker_candidate, is_dialogue, prior_plan)

        return entry

    def _extract_speaker_candidate(self, text: str) -> str | None:
        patterns = [
            r'^["\u201c\u300c](.+?)[说喊叫咆哮低声道笑哭嚷叨答问吼嚷怒道]\s*[：:，,]?\s*["\u201d\u300d]',
            r'(.+?)[说喊叫咆哮低声道笑哭嚷叨答问吼嚷怒道]\s*[：:]\s*["\u201c\u300c]',
            r'(.+?)(说|喊|叫|道|回答|问|笑道|低声说)[：:]',
        ]
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                return m.group(1).strip()
        return None

    def _rule_attribution(
        self,
        segment: Segment,
        speaker_candidate: str | None,
        is_dialogue: bool,
        prior_plan: list[ReadingPlanEntry],
    ) -> ReadingPlanEntry:
        if not is_dialogue:
            return self._narrator_entry(segment)

        speaker_id = self._narrator_id
        confidence = 0.3
        evidence = []

        if speaker_candidate:
            if self.book_model:
                char = self.book_model.lookup_character_by_name_or_alias(speaker_candidate)
                if char:
                    speaker_id = char["character_id"]
                    confidence = 0.85
                    evidence.append(f"matched name/alias '{speaker_candidate}' to {speaker_id}")
                else:
                    speaker_id = f"char_unknown_{speaker_candidate}"
                    confidence = 0.6
                    evidence.append(f"unmatched speaker candidate '{speaker_candidate}'")
            else:
                speaker_id = f"char_{speaker_candidate}"
                confidence = 0.5
                evidence.append(f"no book_model; using raw name '{speaker_candidate}'")
        elif prior_plan:
            last_dialogue = next(
                (p for p in reversed(prior_plan) if p.speaker_id != self._narrator_id), None
            )
            if last_dialogue:
                speaker_id = self._narrator_id
                confidence = 0.4
                evidence.append(
                    f"alternating dialogue heuristic; previous "
                    f"was {last_dialogue.speaker_id}"
                )

        reading_style = self._infer_style(segment, speaker_id, is_dialogue)

        return ReadingPlanEntry(
            segment_id=segment.segment_id,
            segmenter_version=segment.segmenter_version,
            source_href=segment.source_href,
            source_order=segment.source_order,
            text=segment.text,
            speaker_candidate=speaker_candidate,
            speaker_id=speaker_id,
            speaker_confidence=confidence,
            reading_style=reading_style,
            enhancements=Enhancements(),
            voice_constraints=self._infer_voice_constraints(speaker_id, is_dialogue),
            evidence=evidence,
            fallback_policy="use_narrator" if confidence < 0.6 else "use_assigned",
        )

    async def _llm_attribution(
        self,
        segment: Segment,
        chapter_id: str,
        scene_context: dict | None,
        prior_plan: list[ReadingPlanEntry],
    ) -> ReadingPlanEntry:
        context_text = ""
        if prior_plan:
            recent = prior_plan[-3:]
            context_text = "\n".join(f"[{p.speaker_id}]: {p.text}" for p in recent)

        prompt = f"""Analyze this Chinese novel segment and determine who is speaking.

Segment: {segment.text}

Recent context:
{context_text or "(start of chapter)"}

Known characters:
{json.dumps(self._get_known_characters(), ensure_ascii=False) if self.book_model else "none"}

Respond in JSON:
{{
  "speaker_candidate": "name or null",
  "speaker_id": "character_id or char_narrator",
  "speaker_confidence": 0.0-1.0,
  "emotion": "neutral/happy/sad/angry/fearful/restrained/excited/calm",
  "intensity": 0.0-1.0,
  "prosody_hint": "short_pause/normal_pause/long_pause",
  "evidence": ["reason1", "reason2"]
}}"""

        request = LLMRequest(
            task="speaker_attribution",
            messages=[LLMMessage(role="user", content=prompt)],
            temperature=0.2,
            max_tokens=512,
        )

        response = await self.llm.generate(request)

        if response.error:
            return self._rule_attribution(
                segment,
                self._extract_speaker_candidate(segment.text),
                True,
                prior_plan,
            )

        try:
            result = json.loads(response.content)
            speaker_candidate = result.get("speaker_candidate")
            speaker_id = result.get("speaker_id", self._narrator_id)
            confidence = float(result.get("speaker_confidence", 0.5))
            evidence = result.get("evidence", [])

            if self.book_model and speaker_candidate:
                char = self.book_model.lookup_character_by_name_or_alias(speaker_candidate)
                if char:
                    speaker_id = char["character_id"]
                    confidence = max(confidence, 0.85)

            reading_style = ReadingStyle(
                emotion=result.get("emotion", "neutral"),
                intensity=float(result.get("intensity", 0.0)),
                prosody_hint=result.get("prosody_hint", "normal_pause"),
            )

            return ReadingPlanEntry(
                segment_id=segment.segment_id,
                segmenter_version=segment.segmenter_version,
                source_href=segment.source_href,
                source_order=segment.source_order,
                text=segment.text,
                speaker_candidate=speaker_candidate,
                speaker_id=speaker_id,
                speaker_confidence=confidence,
                reading_style=reading_style,
                voice_constraints=self._infer_voice_constraints(speaker_id, True),
                evidence=evidence,
                fallback_policy="use_narrator" if confidence < 0.5 else "use_assigned",
            )
        except (json.JSONDecodeError, ValueError):
            return self._rule_attribution(
                segment,
                self._extract_speaker_candidate(segment.text),
                True,
                prior_plan,
            )

    def _narrator_entry(self, segment: Segment) -> ReadingPlanEntry:
        return ReadingPlanEntry(
            segment_id=segment.segment_id,
            segmenter_version=segment.segmenter_version,
            source_href=segment.source_href,
            source_order=segment.source_order,
            text=segment.text,
            speaker_candidate=None,
            speaker_id=self._narrator_id,
            speaker_confidence=1.0,
            reading_style=ReadingStyle(
                emotion="neutral", intensity=0.0, prosody_hint="normal_pause"
            ),
            voice_constraints=VoiceConstraints(gender_style="neutral", tone=["calm"]),
            evidence=["narrator: no dialogue markers"],
            fallback_policy="use_narrator",
        )

    def _infer_style(self, segment: Segment, speaker_id: str, is_dialogue: bool) -> ReadingStyle:
        text = segment.text
        emotion = "neutral"
        intensity = 0.0
        prosody = "normal_pause"

        if any(m in text for m in ["！", "？", "…", "——"]):
            intensity = 0.5
        if "！" in text:
            emotion = "excited"
            intensity = 0.7
        elif "？" in text:
            emotion = "curious"
            intensity = 0.3
        elif "……" in text or "………" in text:
            emotion = "hesitant"
            prosody = "long_pause"

        if is_dialogue:
            intensity = min(intensity + 0.2, 1.0)

        return ReadingStyle(emotion=emotion, intensity=intensity, prosody_hint=prosody)

    def _carry_forward_speakers(self, plan: list[ReadingPlanEntry]) -> list[ReadingPlanEntry]:
        last_dialogue_speaker = self._narrator_id

        for entry in plan:
            if entry.speaker_confidence < 0.4 and entry.speaker_id != self._narrator_id:
                entry.speaker_id = last_dialogue_speaker
                entry.speaker_confidence = min(entry.speaker_confidence + 0.1, 0.5)
                entry.evidence.append(
                    "carry_forward: low confidence, using previous dialogue speaker"
                )

            if entry.speaker_id != self._narrator_id:
                last_dialogue_speaker = entry.speaker_id

        return plan

    def _infer_voice_constraints(self, speaker_id: str, is_dialogue: bool) -> VoiceConstraints:
        if speaker_id == self._narrator_id:
            return VoiceConstraints(gender_style="neutral", tone=["calm", "narrative"])

        if self.book_model:
            char = self.book_model.get_character(speaker_id)
            if char:
                traits = (
                    json.loads(char.get("traits", "[]"))
                    if isinstance(char.get("traits"), str)
                    else char.get("traits", [])
                )
                gender = (
                    "male" if "male" in traits
                    else "female" if "female" in traits
                    else None
                )
                tone = [
                    t for t in traits
                    if t not in ("male", "female", "child", "young_adult", "adult", "senior")
                ]
                return VoiceConstraints(gender_style=gender, tone=tone)

        return VoiceConstraints(gender_style=None, tone=[])

    def _get_known_characters(self) -> list[dict]:
        if not self.book_model:
            return []
        return self.book_model.get_characters()
