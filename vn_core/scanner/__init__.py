"""Book Scanner: LLM-based character, term, and scene extraction for cold start."""

from __future__ import annotations

import json

from vn_core.harness import HarnessGate
from vn_core.llm_gateway import LLMGateway, LLMMessage, LLMRequest
from vn_core.store import ProjectStore

CHARACTER_EXTRACTION_PROMPT = """Analyze this Chinese novel text and extract all named characters.

For each character, provide:
- name: the primary name used in the text
- aliases: list of other names/titles used for this character
- traits: list of personality/physical traits (use "male"/"female" for gender)
- first_seen: chapter or section where character first appears

Respond in JSON format:
{
  "characters": [
    {"name": "陆明", "aliases": ["少主", "陆公子"],
     "traits": ["male", "young", "determined"], "first_seen": "ch001"}
  ],
  "glossary": [
    {"term": "剑法", "definition": "martial arts sword technique", "category": "skill"}
  ]
}

Text:
"""


SCENE_SUMMARY_PROMPT = """Summarize this chapter in 2-3 sentences, focusing on:
1. Which characters are active (present and speaking)
2. The main location/setting
3. Key events or plot developments

Also list the active characters as an array of their names.

Respond in JSON:
{
  "summary": "...",
  "active_characters": ["name1", "name2"],
  "location": "...",
  "key_events": ["event1", "event2"]
}

Chapter text:
"""


class BookScanner:
    def __init__(self, llm: LLMGateway, store: ProjectStore,
                 harness_gate: HarnessGate | None = None):
        self.llm = llm
        self.store = store
        self.harness = harness_gate or HarnessGate()

    async def scan_chapter(
        self,
        book_id: str,
        chapter_id: str,
        chapter_text: str,
    ) -> dict:
        result = await self._extract_characters(book_id, chapter_id, chapter_text)
        scene = await self._extract_scene(book_id, chapter_id, chapter_text)
        result["scene"] = scene
        return result

    async def scan_book(
        self,
        book_id: str,
        chapters: list[dict],
    ) -> dict:
        all_characters: dict[str, dict] = {}
        all_glossary: list[dict] = []

        for ch in chapters:
            result = await self.scan_chapter(
                book_id, ch["chapter_id"], ch["text"]
            )
            for char_data in result.get("characters", []):
                name = char_data.get("name", "")
                if name and name not in all_characters:
                    all_characters[name] = char_data
                elif name:
                    existing = all_characters[name]
                    existing_aliases = set(existing.get("aliases", []))
                    new_aliases = set(char_data.get("aliases", []))
                    existing["aliases"] = list(existing_aliases | new_aliases)
                    existing_traits = set(existing.get("traits", []))
                    new_traits = set(char_data.get("traits", []))
                    existing["traits"] = list(existing_traits | new_traits)

            for term_data in result.get("glossary", []):
                all_glossary.append(term_data)

        return {"characters": list(all_characters.values()), "glossary": all_glossary}

    async def _extract_characters(
        self,
        book_id: str,
        chapter_id: str,
        text: str,
    ) -> dict:
        truncated = text[:6000]
        request = LLMRequest(
            task="character_extraction",
            messages=[
                LLMMessage(role="system", content=CHARACTER_EXTRACTION_PROMPT),
                LLMMessage(role="user", content=truncated),
            ],
            temperature=0.1,
            max_tokens=2048,
        )
        response = await self.llm.generate(request)

        if response.error:
            return {"characters": [], "glossary": []}

        try:
            result = json.loads(response.content)
            characters = result.get("characters", [])
            glossary = result.get("glossary", [])

            # Build character/glossary patches for Harness commit
            char_patches = []
            glossary_patches = []
            for char_data in characters:
                name = char_data.get("name", "")
                if not name:
                    continue
                char_id = f"char_{name}"
                char_patches.append({
                    "name": name,
                    "character_id": char_id,
                    "names": [name] + char_data.get("aliases", []),
                    "aliases": char_data.get("aliases", []),
                    "traits": char_data.get("traits", []),
                    "first_seen": char_data.get("first_seen", chapter_id),
                    "confidence": 0.7,
                    "status": "inferred",
                    "evidence": [],
                })

            for term_data in glossary:
                term = term_data.get("term", "")
                if term:
                    glossary_patches.append({
                        "term": term,
                        "definition": term_data.get("definition", ""),
                        "category": term_data.get("category", ""),
                        "pronunciation": term_data.get("pronunciation", ""),
                        "confidence": term_data.get("confidence", 0.7),
                    })

            if char_patches or glossary_patches:
                csr = self.harness.commit_scan_result(
                    store=self.store,
                    book_id=book_id,
                    unit_id=chapter_id,
                    characters=char_patches,
                    glossary_terms=glossary_patches,
                )
                if csr.decision != "pass":
                    # Partial write — return what was extracted but note failure
                    return {
                        "characters": characters,
                        "glossary": glossary,
                        "harness_error": csr.reason,
                    }

            return {"characters": characters, "glossary": glossary}

        except (json.JSONDecodeError, ValueError):
            return {"characters": [], "glossary": []}

    async def _extract_scene(
        self,
        book_id: str,
        chapter_id: str,
        text: str,
    ) -> dict:
        truncated = text[:4000]
        request = LLMRequest(
            task="scene_summary",
            messages=[
                LLMMessage(role="system", content=SCENE_SUMMARY_PROMPT),
                LLMMessage(role="user", content=truncated),
            ],
            temperature=0.1,
            max_tokens=1024,
        )
        response = await self.llm.generate(request)

        if response.error:
            return {"summary": "", "active_characters": []}

        try:
            result = json.loads(response.content)
            snapshot_data = {
                "summary": result.get("summary", ""),
                "active_characters": result.get("active_characters", []),
                "location": result.get("location", ""),
                "key_events": result.get("key_events", []),
            }
            self.store.upsert_scene_snapshot(
                book_id=book_id,
                chapter_id=chapter_id,
                snapshot_data=snapshot_data,
                created_by="scanner",
            )
            return result
        except (json.JSONDecodeError, ValueError):
            return {"summary": "", "active_characters": []}
