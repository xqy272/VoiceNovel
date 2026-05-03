# 成本、预检、溯源、导出与许可策略

描述 Cost Planner、Preflight、Provenance、Export Targets 和 License/Model Policy Gate。

[返回设计索引](README.md)

## 17. Cost Planner

长篇小说生成前必须 dry-run 估算：

```json
{
  "chapters": 120,
  "segments": 43820,
  "text_chars": 1850000,
  "llm_input_tokens_est": 2400000,
  "llm_output_tokens_est": 900000,
  "tts_chars": 1850000,
  "asr_audio_minutes_est": 2100,
  "storage_gb_est": 8.4,
  "local_gpu_hours_est": 18.5,
  "api_cost_est": {
    "llm": 12.4,
    "tts": 48.0,
    "asr": 9.2
  }
}
```

预缓存模式下，成本估算需要分两种：

- 启动成本：当前章节达到可播放缓冲需要多少 token、TTS 字符、时间和费用。
- 全书成本：若用户主动烘焙全书，需要多少时间、费用和磁盘。

Cost Planner 同时负责并发档位预算：

```text
economy    低成本，限制 LLM 并发和 TTS 并发
balanced   默认，允许适度章节预理解和 TTS 并发
aggressive 接口预留，多路候选和多 take，需要用户显式选择
unlimited  接口预留，不进入 MVP
```

MVP 只实现 `economy` 和 `balanced` 两档。

## 18. Preflight Check

生成前检查：

- 用户声明使用场景：`personal`、`research`、`commercial`、`internal_company`、`public_distribution`。

- LLM endpoint 可用。
- TTS endpoint 可用。
- ASR endpoint 可用。
- ffmpeg / ffprobe 可用。
- 磁盘空间足够。
- GPU / VRAM 足够。
- 模型是否已下载。
- 当前网络和 API key 是否可用。
- 许可证风险是否符合当前使用场景。

License Gate 必须基于用户声明用途过滤模型、音色和导出方式。个人听书、研究、公司内部、公开分发、商业产品的风险边界不同，不能只做通用提示。

## 19. Provenance

每个阶段记录可复现信息：

```json
{
  "segment_id": "ch001_p023_s002",
  "stage": "reading_plan",
  "generation_config_id": "gencfg_001",
  "run_id": "run_20260430_001",
  "artifact_version_id": "planver_003",
  "llm_model": "gpt-4.1",
  "prompt_version": "reading_plan_v3",
  "input_hash": "sha256...",
  "output_hash": "sha256...",
  "cache_key": "sha256...",
  "cache_buster": null,
  "reading_profile": "enhanced",
  "created_at": "2026-04-30T12:00:00Z"
}
```

这对 debug、缓存、断点续跑、成本追踪和结果复现都很关键。

## 20. Export Targets

阅读器是首要目标，Reader Package 由 Packaging Service 生成；Export Targets 只负责用户显式导出的外部格式。Export 应依赖 active Reader Package 或 Project Store 中的 active artifacts，可删除、可重建，不应反向影响主播放链路。

建议支持：

- Reader Package
- MP3 per chapter
- M4B
- WAV per segment
- Audacity / DAW package
- Audiobookshelf compatible metadata

## 21. License / Model Policy Gate

需要记录每个组件和模型的许可证限制：

```json
{
  "component": "ChatTTS",
  "license": "AGPL / non-commercial model constraints",
  "commercial_safe": false,
  "allowed_usage": ["personal", "research"],
  "blocked_usage": ["commercial", "public_distribution"]
}
```

Koodo 的 AGPL、ChatTTS 的代码/模型许可、部分声音克隆模型的非商业限制，都应在架构层面隔离。Koodo voice plugin 路线可以降低维护成本和 fork 复杂度，但不能被当作自动绕过许可证审查的手段；只要分发 Koodo 派生版本、捆绑插件、复用其代码或以商业形态提供集成，都需要单独记录合规判断。
