# MVP 范围与暂缓项

收敛第一阶段必须包含的闭环能力、实现顺序和明确暂缓范围。

[返回设计索引](README.md)

## 推荐 MVP

第一阶段不要直接深改 Koodo。先做 VoiceNovel Station、Reference Web Reader 和 API-first pipeline，验证完整链路；同时做一个 Koodo voice plugin 兼容接入作为低风险探针，验证 Koodo 能否通过现有语音插件调用 Core Server。MVP 需要收窄，优先证明“听书体验闭环能稳定跑起来”，并验证 Project Store / Service / Orchestrator / Harness 的状态管理闭环；不要过早追求图数据库、可插拔 Skill Pack、全量 Agent、多 Agent、复杂 Sleep 或完整 ASR harness：

```text
EPUB/TXT
-> Project Store
-> Text Adaptation
-> 中文分句
-> cleaned HTML
-> reading_plan.jsonl
-> Book Model
-> Voice Registry
-> Speech Gateway
-> 预缓存队列
-> Harness Engineering
-> Chapter MP3 + timing.json
-> 句子/半句高亮播放
```

MVP 必须包含：

- Project Store：SQLite 元数据/状态 + 文件 blob，active version、schema、provenance 基本可用。
- Contracts first：Segment、TextAdaptationOperation、ReadingPlanEntry、VoiceAssignment、BackendSpeechRequest、AudioTake、TimingEntry、ReaderManifest、ReaderPackageManifest、JobState、Provenance、Exception、ContextSpec、ContextCapsule、ReaderAdapterRequest、ReaderAdapterResponse 的 Python model + JSON Schema。
- Golden test book：选 2-3 章短篇小说，手工维护 cleaned HTML、reading_plan、timing、reader package 作为全链路回归基准。
- VoiceNovel Station 最小控制台：导入、配置 Core Server / provider、触发任务、查看进度、检查 Reader Package、处理异常和查看成本预估。
- 实现顺序从 Reference Web Reader + 手工 Reader Package 起步，再倒推 Timing、Mock TTS、Segmenter、Text Adaptation、Reading Planner 和 Orchestrator。
- 轻量 artifact dependency 表：记录产物依赖并校验依赖 active，不做复杂图数据库或版本树 UI。
- 冷启动四阶段路径：本地快速路径、LLM quick scan、最小可播放缓冲、后台完善。
- TXT/EPUB 导入。
- Text Adaptation：基础清洗、明显错字、TTS 发音规范化和高置信度文本适配。
- 中文保守句子/半句切分，复杂段落允许回退整句/整段。
- `segment_id` 稳定生成，并锁定 `segmenter_version`。
- AI 校对后的 cleaned HTML。
- LLM 朗读计划、上下文产线、基础 Book Model 和 Character Memory。
- `ContextSpec -> Fetch Engine -> typed Context Capsule` 简化版，以及 chapter-level `memory_snapshot_id`。
- `faithful` / `enhanced` 两档听书模式，增强能力必须可关闭和可降级。
- Mock TTS + 一个真实 TTS API，优先 CosyVoice Docker；Edge-TTS 可作为旁白/兜底。
- Koodo voice plugin compatibility endpoint + 示例插件：只验证 Koodo 当前朗读文本到 Core Server 的 TTS 调用，不承诺 Reader Package、高亮同步或离线包。
- 最小 Playback-Driven Scheduler：冷启动 bootstrapping、固定 fallback voice、当前章节优先、下一章预缓存、TTS segment 可并发、timing 按章串行。
- `economy` / `balanced` 两档并发调度。
- 断点续跑、segment 级缓存、`generation_config_id`、`run_id` 和 `cache_buster`。
- 基于真实音频时长和可配置 gap 的 `timing.json`。
- Packaging Service：从 active artifacts 构建 Reader Package，并通过 Harness Gate 提交。
- 简化版 Harness Engineering：Gate 接口、schema 校验、invariant 检查、重试/降级、异常队列。
- Web Reader 句子/半句高亮播放。
- 简化版 Cost Planner 和 Preflight Check。

MVP 暂缓：

- 完整 ASR 反校验。
- 复杂音色生命周期。
- GPT-SoVITS / ChatTTS / FishSpeech 多后端。
- `dramatic-lite` 轻剧场模式、复杂音效和多轨混音。
- 图数据库 / 图抽象层。
- 可插拔 Skill Pack 框架。
- Agent / Multi-Agent 框架。
- 复杂 Sleep / Background Consolidation。
- `aggressive` / `unlimited` 并发模式。
- M4B / Audiobookshelf / Audacity 导出。
- Koodo Reader Package Adapter / thin fork 深度接入。
- 复杂商业许可证自动判断。

等 Reader Package 和 Station 稳定后，再评估 Koodo 插件能力是否足够承载 Reader Package；不足时再进入 Koodo thin fork、Electron 或移动端阅读器。
