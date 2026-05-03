"""Generate JSON Schema and TypeScript types from Pydantic contracts."""

from __future__ import annotations

import json
from pathlib import Path

from vn_core.contracts.audio_take import AudioTake
from vn_core.contracts.context_capsule import ContextCapsule
from vn_core.contracts.context_spec import ContextSpec
from vn_core.contracts.exception_entry import ExceptionEntry
from vn_core.contracts.generation_config import GenerationConfig
from vn_core.contracts.job_state import JobState
from vn_core.contracts.memory_patch import MemoryPatch
from vn_core.contracts.provenance import ProvenanceEntry
from vn_core.contracts.reader_adapter import ReaderAdapterRequest, ReaderAdapterResponse
from vn_core.contracts.reader_manifest import ReaderManifest, ReaderPackageManifest, TimingProfile
from vn_core.contracts.reading_plan import ReadingPlanEntry, ReadingStyle, VoiceConstraints
from vn_core.contracts.segment import Segment
from vn_core.contracts.speech_request import BackendSpeechRequest
from vn_core.contracts.text_adaptation import TextAdaptationOperation
from vn_core.contracts.timing_entry import AudioSpacing, TimingEntry
from vn_core.contracts.voice_assignment import VoiceAssignment

CONTRACT_MODELS = [
    AudioTake,
    ContextCapsule,
    ContextSpec,
    ExceptionEntry,
    GenerationConfig,
    JobState,
    MemoryPatch,
    ProvenanceEntry,
    ReaderAdapterRequest,
    ReaderAdapterResponse,
    ReaderManifest,
    ReaderPackageManifest,
    TimingProfile,
    ReadingPlanEntry,
    ReadingStyle,
    VoiceConstraints,
    Segment,
    BackendSpeechRequest,
    TextAdaptationOperation,
    AudioSpacing,
    TimingEntry,
    VoiceAssignment,
]


def generate_json_schemas(output_dir: str | Path | None = None) -> dict[str, dict]:
    """Generate JSON Schema from all contract models.

    Returns dict of model_name -> schema_dict.
    Optionally writes individual schema files to output_dir.
    """
    schemas = {}
    for model in CONTRACT_MODELS:
        schema = model.model_json_schema()
        schemas[model.__name__] = schema

    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        for name, schema in schemas.items():
            path = out / f"{name}.json"
            path.write_text(
                json.dumps(schema, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        combined_path = out / "contracts.json"
        combined_path.write_text(
            json.dumps(schemas, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return schemas


def generate_typescript_types(
    output_path: str | Path = "web_reader/src/types.ts",
) -> str:
    """Generate TypeScript type definitions from JSON Schemas.

    Produces a .ts file with interface definitions matching the contracts.
    """
    schemas = generate_json_schemas()
    lines = [
        "// Auto-generated TypeScript types from VoiceNovel contracts.",
        "// Run: py -3.12 -m vn_core.contracts.export_ts",
        "",
    ]

    type_map = {
        "string": "string",
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
    }

    for name, schema in schemas.items():
        props = schema.get("properties", {})
        required = schema.get("required", [])
        lines.append(f"export interface {name} {{")
        for prop_name, prop_schema in props.items():
            any_of = prop_schema.get("anyOf")
            if any_of:
                ts_types = []
                for v in any_of:
                    t = v.get("type", "any")
                    ts_types.append(type_map.get(t, "any"))
                ts_type = " | ".join(ts_types)
            else:
                prop_type = prop_schema.get("type", "any")
                if prop_type == "array":
                    items = prop_schema.get("items", {})
                    item_type = type_map.get(items.get("type", "any"), "any")
                    ts_type = f"{item_type}[]"
                elif prop_type == "object":
                    ts_type = "Record<string, unknown>"
                else:
                    ts_type = type_map.get(prop_type, "any")

            opt = "" if prop_name in required else "?"
            lines.append(f"  {prop_name}{opt}: {ts_type};")
        lines.append("}")
        lines.append("")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "data/schemas"
    schemas = generate_json_schemas(out)
    print(f"Generated {len(schemas)} JSON schemas to {out}")
