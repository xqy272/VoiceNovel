"""Voice Casting: match character profiles to voice IDs with scoring and sticky assignment."""

from __future__ import annotations

from vn_core.contracts.reading_plan import ReadingPlanEntry
from vn_core.contracts.voice_assignment import VoiceAssignment
from vn_core.store import ProjectStore
from vn_core.voice import VoiceRegistry


def _gender_match_score(character_traits: list[str], voice_tags: list[str]) -> float:
    gender_keywords = {"male", "female", "neutral"}
    char_gender = None
    voice_gender = None
    for t in character_traits:
        if t in gender_keywords:
            char_gender = t
            break
    for t in voice_tags:
        if t in gender_keywords:
            voice_gender = t
            break
    if char_gender is None or voice_gender is None:
        return 0.3
    if char_gender == voice_gender:
        return 1.0
    if char_gender == "neutral" or voice_gender == "neutral":
        return 0.5
    return 0.0


def _age_match_score(character_traits: list[str], voice_tags: list[str]) -> float:
    age_keywords = {"child", "young_adult", "adult", "senior"}
    char_age = None
    voice_age = None
    for t in character_traits:
        if t in age_keywords:
            char_age = t
            break
    for t in voice_tags:
        if t in age_keywords:
            voice_age = t
            break
    if char_age is None or voice_age is None:
        return 0.3
    if char_age == voice_age:
        return 1.0
    adjacent = {"young_adult": {"adult"}, "adult": {"young_adult", "senior"}}
    if voice_age in adjacent.get(char_age, set()):
        return 0.5
    return 0.0


def score_voice(
    character_traits: list[str],
    voice_config: dict,
) -> float:
    if voice_config.get("status") != "approved":
        return 0.0
    voice_tags = set(voice_config.get("tags", []))
    char_tags = set(character_traits)

    tag_overlap = len(char_tags & voice_tags) / max(len(char_tags | voice_tags), 1)
    gender_score = _gender_match_score(character_traits, list(voice_tags))
    age_score = _age_match_score(character_traits, list(voice_tags))
    quality = voice_config.get("quality", {}).get("overall_quality", 0.5)
    license_ok = 1.0 if voice_config.get("license", "") in ("free", "internal") else 0.3

    return (
        tag_overlap * 0.3
        + gender_score * 0.3
        + age_score * 0.15
        + quality * 0.15
        + license_ok * 0.1
    )


def cast_voice(
    character_id: str,
    character_traits: list[str],
    voice_registry: VoiceRegistry,
    store: ProjectStore | None = None,
    book_id: str = "",
) -> VoiceAssignment:
    if store and book_id:
        existing = store._get_conn().execute(
            "SELECT voice_id, user_locked FROM voice_assignments "
            "WHERE book_id=? AND character_id=?",
            (book_id, character_id),
        ).fetchone()
        if existing and existing[1]:
            return VoiceAssignment(
                character_id=character_id,
                voice_id=existing[0],
                confidence=1.0,
                user_locked=True,
                source="user",
            )

    candidates = voice_registry.list_voices(status="approved")
    best_score = 0.0
    best_voice_id = ""

    for voice in candidates:
        s = score_voice(character_traits, voice)
        if s > best_score:
            best_score = s
            best_voice_id = voice["voice_id"]

    if best_score >= 0.4 and best_voice_id:
        assignment = VoiceAssignment(
            character_id=character_id,
            voice_id=best_voice_id,
            confidence=min(best_score, 1.0),
            user_locked=False,
            source="auto",
        )
    else:
        fallback_role = "fallback"
        gender_keywords = {"male", "female"}
        for trait in character_traits:
            if trait in gender_keywords:
                fallback_role = f"{trait}_dialogue"
                break
        if character_id == "char_narrator":
            fallback_role = "narrator"
        fallback_id = voice_registry.get_fallback_voice(fallback_role)
        assignment = VoiceAssignment(
            character_id=character_id,
            voice_id=fallback_id,
            confidence=0.3,
            user_locked=False,
            source="fallback",
        )

    if store and book_id:
        store.upsert_voice_assignment(
            book_id=book_id,
            character_id=character_id,
            voice_id=assignment.voice_id,
            confidence=assignment.confidence,
            user_locked=assignment.user_locked,
            source=assignment.source,
        )

    return assignment


def cast_all_characters(
    plan_entries: list[ReadingPlanEntry],
    voice_registry: VoiceRegistry,
    store: ProjectStore | None = None,
    book_id: str = "",
) -> dict[str, VoiceAssignment]:
    unique_speakers: dict[str, list[str]] = {}
    for entry in plan_entries:
        if entry.speaker_id not in unique_speakers:
            unique_speakers[entry.speaker_id] = entry.voice_constraints.tone or []
        if entry.voice_constraints.tone:
            existing = unique_speakers[entry.speaker_id]
            merged = list(set(existing + entry.voice_constraints.tone))
            unique_speakers[entry.speaker_id] = merged

    if book_id and store:
        for entry in plan_entries:
            if entry.voice_constraints.gender_style == "male":
                unique_speakers.setdefault(entry.speaker_id, [])
                if "male" not in unique_speakers[entry.speaker_id]:
                    unique_speakers[entry.speaker_id].append("male")
            elif entry.voice_constraints.gender_style == "female":
                unique_speakers.setdefault(entry.speaker_id, [])
                if "female" not in unique_speakers[entry.speaker_id]:
                    unique_speakers[entry.speaker_id].append("female")

    assignments: dict[str, VoiceAssignment] = {}
    for speaker_id, traits in unique_speakers.items():
        traits_copy = list(traits)
        if speaker_id == "char_narrator":
            traits_copy = ["narrator", "neutral", "adult"]
        assignments[speaker_id] = cast_voice(
            character_id=speaker_id,
            character_traits=traits_copy,
            voice_registry=voice_registry,
            store=store,
            book_id=book_id,
        )

    return assignments
