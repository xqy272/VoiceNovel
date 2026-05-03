# Voice Casting — AI Agent Guide

## Purpose
Matches character profiles to voice IDs from the Voice Registry using scoring heuristics.

## Key Concepts
- **VoiceAssignment**: Maps character_id → voice_id with confidence and source
- **Scoring**: Based on gender, age, tone tags, quality, license, and user locks
- **Sticky assignment**: Once a character binds to a voice, it doesn't drift across chapters
- **Fallback chain**: character traits → registry matching → fallback voice map

## Module: `vn_core/voice/casting.py`

### `cast_voice(character_profile, voice_registry, store, book_id) -> VoiceAssignment`
1. Check user-locked assignment first
2. Match character traits against voice tags
3. Score candidates by gender/age/tone/quality overlap
4. Select best candidate above threshold
5. Fall back to FALLBACK_VOICES mapping

### `cast_all_characters(plan_entries, voice_registry, store, book_id) -> dict[str, VoiceAssignment]`
Casts voices for all unique speakers in a reading plan.