"""UserLexicon: per-user pronunciation overrides from a JSON file.

Priority: UserLock > BookModel override > UserLexicon > SystemLexicon
"""

from __future__ import annotations

import json
from pathlib import Path


class UserLexicon:
    """User-level pronunciation preferences loaded from a JSON file.

    File format:
    {
      "version": "1.0",
      "overrides": {
        "原文字": "读音替换",
        "原文字2": "读音替换2"
      },
      "disabled_system_rules": ["rule_id_1", "rule_id_2"]
    }
    """

    def __init__(self, lexicon_path: str | Path | None = None):
        self._overrides: dict[str, str] = {}
        self._disabled_rules: set[str] = set()
        self._version: str = "0.0"

        if lexicon_path:
            self.load(lexicon_path)

    def load(self, path: str | Path):
        """Load overrides from a JSON lexicon file."""
        p = Path(path)
        if not p.exists():
            return

        data = json.loads(p.read_text(encoding="utf-8"))
        self._version = data.get("version", "0.0")
        self._overrides = data.get("overrides", {})
        self._disabled_rules = set(data.get("disabled_system_rules", []))

    def apply(self, text: str) -> str:
        """Apply user-level overrides to text (simple string replacement)."""
        result = text
        for original, replacement in self._overrides.items():
            result = result.replace(original, replacement)
        return result

    def get_override(self, text: str) -> str | None:
        """Get the user override for a specific text, if any."""
        return self._overrides.get(text)

    def is_rule_disabled(self, rule_id: str) -> bool:
        """Check if a system rule is disabled by the user."""
        return rule_id in self._disabled_rules

    @property
    def version(self) -> str:
        return self._version

    def to_dict(self) -> dict:
        return {
            "version": self._version,
            "overrides": dict(self._overrides),
            "disabled_system_rules": sorted(self._disabled_rules),
        }
