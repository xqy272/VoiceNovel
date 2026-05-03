"""Pronunciation Engine: multi-layer TTS text normalization.

Priority chain (highest to lowest):
    UserLock > BookModel override > UserLexicon > SystemLexicon > model inference
"""

from __future__ import annotations

import hashlib
import json

from vn_core.pronunciation.system_lexicon import apply_system_rules
from vn_core.pronunciation.system_lexicon import get_version as get_system_version
from vn_core.pronunciation.user_lexicon import UserLexicon
from vn_core.store import ProjectStore


class PronunciationEngine:
    """Normalize text for TTS using layered pronunciation rules.

    Usage:
        engine = PronunciationEngine()
        engine.set_book(book_id, store)
        normalized = engine.normalize("他2024年来到北京。")
        # → "他 二零二四 年来到北京。"
    """

    def __init__(self, user_lexicon: UserLexicon | None = None):
        self._user_lexicon = user_lexicon or UserLexicon()
        self._store: ProjectStore | None = None
        self._book_id: str | None = None
        self._book_overrides: dict[str, str] = {}
        self._user_locks: dict[str, str] = {}

    def set_book(self, book_id: str, store: ProjectStore):
        """Bind to a specific book for BookModel-level overrides."""
        self._store = store
        self._book_id = book_id
        self._refresh_book_overrides()

    def _refresh_book_overrides(self):
        """Reload book-level pronunciation overrides from store."""
        if not self._store or not self._book_id:
            self._book_overrides = {}
            self._user_locks = {}
            return
        rows = self._store.get_pronunciation_overrides(self._book_id)
        self._book_overrides = {}
        self._user_locks = {}
        for row in rows:
            text = row.get("text", "")
            reading = row.get("reading", "")
            status = row.get("status", "inferred")
            if status == "user_locked":
                self._user_locks[text] = reading
            else:
                self._book_overrides[text] = reading

    def normalize(self, text: str) -> str:
        """Apply all pronunciation layers and return normalized text.

        Priority (highest first): UserLocks > BookModel > UserLexicon > SystemLexicon

        Each layer's replacements operate on the ORIGINAL text independently,
        then are merged in priority order. This prevents a lower-priority
        replacement from breaking a higher-priority match or vice versa.
        """
        # Collect replacements from each layer (applied to original text)
        replacements: list[tuple[str, str, int]] = []  # (old, new, priority)

        # Layer 4: SystemLexicon (lowest priority = 0)
        # Applied as a full-pass transform, not individual replacements
        system_result = apply_system_rules(text)

        # Layer 3: UserLexicon (priority 1)
        for original, replacement in self._user_lexicon._overrides.items():
            if original in text:
                replacements.append((original, replacement, 1))

        # Layer 2: BookModel overrides (priority 2)
        for original, reading in self._book_overrides.items():
            if original in text:
                replacements.append((original, reading, 2))

        # Layer 1: UserLocks (highest priority = 3)
        for original, reading in self._user_locks.items():
            if original in text:
                replacements.append((original, reading, 3))

        if not replacements:
            return system_result

        # Sort by priority (highest first), then by length (longest first)
        replacements.sort(key=lambda x: (-x[2], -len(x[0])))

        # Apply replacements to original text, highest priority first
        result = text
        for old, new, _pri in replacements:
            result = result.replace(old, new)

        # Apply system rules to final result (for parts not covered by overrides)
        result = apply_system_rules(result)

        return result

    def get_applied_rules(self, text: str) -> list[dict]:
        """Return a list describing which rules were applied to this text."""
        rules = []
        normalized = self.normalize(text)
        if normalized != text:
            rules.append({
                "original": text,
                "normalized": normalized,
                "system_lexicon_version": get_system_version(),
                "user_lexicon_version": self._user_lexicon.version,
            })
        return rules

    @property
    def system_version(self) -> str:
        return get_system_version()

    @property
    def user_version(self) -> str:
        return self._user_lexicon.version

    @property
    def cache_fingerprint(self) -> str:
        """Stable fingerprint for pronunciation inputs that affect TTS text."""
        payload = {
            "book_overrides": self._book_overrides,
            "user_locks": self._user_locks,
            "system_version": self.system_version,
            "user_lexicon": self._user_lexicon.to_dict(),
            "user_version": self.user_version,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:40]
