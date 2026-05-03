"""SceneStateExtractor: compute rich scene metadata from reading plan output.

No LLM calls — pure aggregation of ReadingPlanner results.
"""

from __future__ import annotations


def extract_from_plan(plan_entries: list) -> dict:
    """Extract rich scene state from a list of ReadingPlanEntry objects.

    Returns a dict suitable for storage in scene_snapshots.snapshot_data.
    """
    if not plan_entries:
        return _empty_state()

    speakers: dict[str, int] = {}
    narrator_count = 0
    dialogue_count = 0
    total = len(plan_entries)
    emotions: list[dict] = []
    last_speaker: str | None = None
    last_addressee: str | None = None
    speaker_sequence: list[str] = []

    for i, entry in enumerate(plan_entries):
        sid = getattr(entry, "speaker_id", "char_narrator") or "char_narrator"
        if sid == "char_narrator":
            narrator_count += 1
        else:
            dialogue_count += 1
            speakers[sid] = speakers.get(sid, 0) + 1
            speaker_sequence.append(sid)

        # Track emotion arc (sample every ~10% of chapter)
        if total > 0 and i % max(1, total // 10) == 0:
            style = getattr(entry, "reading_style", None)
            if style:
                emotions.append({
                    "position": round(i / total, 2) if total > 0 else 0,
                    "emotion": getattr(style, "emotion", "neutral") or "neutral",
                })

    # Detect turn pattern
    turn_pattern = _detect_turn_pattern(speaker_sequence)

    # Last speaker / addressee
    non_narrator = [s for s in speaker_sequence if s != "char_narrator"]
    if non_narrator:
        last_speaker = non_narrator[-1]
        if len(non_narrator) >= 2 and non_narrator[-1] != non_narrator[-2]:
            last_addressee = non_narrator[-2]

    dialogue_density = round(dialogue_count / total, 2) if total > 0 else 0.0
    narrator_ratio = round(narrator_count / total, 2) if total > 0 else 1.0

    return {
        "last_speaker": last_speaker,
        "last_addressee": last_addressee,
        "turn_pattern": turn_pattern,
        "dialogue_density": dialogue_density,
        "narrator_ratio": narrator_ratio,
        "character_turn_counts": speakers,
        "emotional_arc": emotions,
        "segment_count": total,
        "dialogue_segment_count": dialogue_count,
        "narrator_segment_count": narrator_count,
    }


def merge_with_existing(existing: dict | None, new_state: dict) -> dict:
    """Merge new scene state into existing snapshot, preserving old fields."""
    if not existing:
        return new_state
    merged = dict(existing)
    merged.update(new_state)
    return merged


def _detect_turn_pattern(speaker_sequence: list[str]) -> str:
    """Classify the dialogue turn pattern from a speaker sequence."""
    if len(speaker_sequence) < 2:
        return "none"

    unique = list(dict.fromkeys(speaker_sequence))
    if len(unique) == 1:
        return "monologue"
    if len(unique) == 2:
        # Check if alternating
        alternating = True
        for i in range(1, len(speaker_sequence)):
            if speaker_sequence[i] == speaker_sequence[i - 1]:
                alternating = False
                break
        return "alternating" if alternating else "two_party"
    return "multi_party"


def _empty_state() -> dict:
    return {
        "last_speaker": None,
        "last_addressee": None,
        "turn_pattern": "none",
        "dialogue_density": 0.0,
        "narrator_ratio": 1.0,
        "character_turn_counts": {},
        "emotional_arc": [],
        "segment_count": 0,
        "dialogue_segment_count": 0,
        "narrator_segment_count": 0,
    }
