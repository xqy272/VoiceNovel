"""LLM Prompt Registry: versioned, template-based prompt management.

Each prompt has a name, semver version, model_family, templates, output_schema,
and metadata. Once a version is registered, it is immutable.

Usage:
    registry = PromptRegistry()
    registry.load_builtins()          # load from registry.yaml
    prompt = registry.get("speaker_attribution")   # latest version
    prompt = registry.get("speaker_attribution", "1.0.0")
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PromptDefinition:
    name: str
    version: str
    model_family: str = "openai"
    system_template: str = ""
    user_template: str = "{input}"
    output_schema: dict = field(default_factory=dict)
    description: str = ""

    def render_system(self, **kwargs) -> str:
        """Render the system prompt template with kwargs."""
        if not self.system_template:
            return ""
        try:
            return self.system_template.format(**kwargs)
        except KeyError:
            return self.system_template
        except Exception:
            return self.system_template

    def render_user(self, **kwargs) -> str:
        """Render the user prompt template with kwargs."""
        if not self.user_template:
            return ""
        try:
            return self.user_template.format(**kwargs)
        except KeyError:
            from collections import defaultdict
            return self.user_template.format_map(defaultdict(str, **kwargs))
        except Exception:
            return self.user_template

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "model_family": self.model_family,
            "system_template": self.system_template,
            "user_template": self.user_template,
            "output_schema": self.output_schema,
            "description": self.description,
        }


class PromptRegistry:
    def __init__(self):
        self._prompts: dict[str, dict[str, PromptDefinition]] = {}

    # ── registration ──────────────────────────────────────────────────────

    def register(self, definition: PromptDefinition):
        """Register a prompt version. Raises if version already exists."""
        if definition.name not in self._prompts:
            self._prompts[definition.name] = {}
        if definition.version in self._prompts[definition.name]:
            raise ValueError(
                f"Prompt '{definition.name}' version '{definition.version}' is "
                f"already registered and immutable."
            )
        self._prompts[definition.name][definition.version] = definition

    def get(self, name: str, version: str | None = None) -> PromptDefinition | None:
        """Get a prompt by name. Returns latest version if version is None."""
        versions = self._prompts.get(name)
        if not versions:
            return None
        if version:
            return versions.get(version)
        sorted_versions = sorted(
            versions.keys(),
            key=lambda v: tuple(map(int, v.split("."))),
        )
        return versions[sorted_versions[-1]]

    def list_prompts(self) -> list[str]:
        """List all registered prompt names."""
        return sorted(self._prompts.keys())

    def list_versions(self, name: str) -> list[str]:
        """List all versions for a given prompt name."""
        if name not in self._prompts:
            return []
        return sorted(
            self._prompts[name].keys(),
            key=lambda v: tuple(map(int, v.split("."))),
        )

    # ── YAML loading ──────────────────────────────────────────────────────

    def load_builtins(self):
        """Load built-in prompts from the bundled registry.yaml."""
        yaml_path = Path(__file__).parent / "registry.yaml"
        if not yaml_path.exists():
            return
        self.load_yaml(yaml_path)

    def load_yaml(self, path: str | Path):
        """Load prompt definitions from a YAML file."""
        try:
            import yaml
        except ImportError:
            return

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "prompts" not in data:
            return

        for name, entry in data["prompts"].items():
            meta = entry.get("meta", {})
            for version_info in entry.get("versions", []):
                version = version_info.get("version", "0.1.0")
                model_family = version_info.get(
                    "model_family",
                    meta.get("model_family", "openai"),
                )

                # Resolve templates: version can override, fall back to meta defaults
                system_template = version_info.get(
                    "system_template",
                    meta.get("system_template", ""),
                )
                user_template = version_info.get(
                    "user_template",
                    meta.get("user_template", "{input}"),
                )
                output_schema = version_info.get("output_schema", meta.get("output_schema", {}))
                description = version_info.get("description", meta.get("description", ""))

                self.register(PromptDefinition(
                    name=name,
                    version=version,
                    model_family=model_family,
                    system_template=system_template,
                    user_template=user_template,
                    output_schema=output_schema,
                    description=description,
                ))

    def load_json(self, path: str | Path):
        """Load prompt definitions from a JSON file (alternative format)."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for item in data if isinstance(data, list) else data.get("prompts", []):
            self.register(PromptDefinition(
                name=item["name"],
                version=item.get("version", "0.1.0"),
                model_family=item.get("model_family", "openai"),
                system_template=item.get("system_template", ""),
                user_template=item.get("user_template", "{input}"),
                output_schema=item.get("output_schema", {}),
                description=item.get("description", ""),
            ))

    # ── stats ─────────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return sum(len(versions) for versions in self._prompts.values())

    def to_dict(self) -> dict:
        return {
            name: {ver: d.to_dict() for ver, d in versions.items()}
            for name, versions in self._prompts.items()
        }
