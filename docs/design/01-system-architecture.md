# 系统架构与工程基线

描述整体架构、写入流程、MVP 架构收敛原则、技术栈和建议目录结构。

[返回设计索引](README.md)

## 系统架构

```text
Project Store:
  versioned source of truth for every book
  source / artifacts / exports / book model / jobs / provenance

Service Layer:
  stateless capability modules
  Text Adaptation / Segmenter / Reading Planner / Voice Casting
  / Timing / Packaging

External Gateways:
  LLM Gateway: provider adapter / prompt registry / routing / cache / rate limit
  Speech Gateway: TTS adapter / provider routing / backend fallback / rate limit

Book Model:
  structured novel understanding
  characters / aliases / relationships / glossary / pronunciation
  / scene state / reading decisions / user locks / conflicts

Context Layer:
  service-declared ContextSpec -> Fetch Engine -> typed Context Capsule

Orchestrator:
  scheduling / prefetch / retry / cache / concurrency / priority

Harness Gate:
  schema / invariant / conflict / quality / provenance checks

Experience Layer:
  VoiceNovel Station / Reader Adapter Protocol / Reference Web Reader
  / Koodo Voice Plugin / Koodo Reader Package Adapter / Concrete Reader Adapters / Exception Console
```

这不是一条单向线性 pipeline，而是一个“播放体验驱动的版本化生成系统”。`Project Store` 是唯一真值源；`Service Layer` 是无状态计算；`External Gateways` 负责外部模型和语音服务通讯；`Book Model` 是从 Project Store 构建的小说理解投影；各 service 声明自己的 `ContextSpec`，由 Context Fetch Engine 检索并装配 typed Context Capsule；`Orchestrator` 负责预缓存、并发、断点续跑和优先级；所有写入都必须经过 `Harness Gate`。

Experience Layer 分成生产控制面和消费适配面。`VoiceNovel Station` 是桌面/开发控制台，负责导入、配置、运行管线、异常处理、成本预估和 Reader Package 检查；阅读器集成只消费 Core Server API 和 Reader Package。Koodo 的第一阶段接入应优先走 `Koodo Voice Plugin`，把它当作 Speech Gateway 的宿主侧 provider 适配探针；只有当插件无法稳定访问章节内容、播放控制、timing、高亮 DOM 或离线缓存时，才升级到 `Koodo Reader Package Adapter` 或 thin fork。

核心写入流程：

```text
task
-> read active artifacts from Project Store
-> service declares ContextSpec
-> fetch and assemble typed Context Capsule
-> run stateless service
-> produce proposed artifacts / memory patches / exceptions
-> Harness Gate
-> commit to Project Store
-> refresh Book Model projection
-> update job state / provenance
```

`Harness Engineering` 不作为最后一步存在，而是贯穿所有模块。它负责 schema 校验、invariant 检查、artifact registry、任务状态、缓存策略、重试/降级、质量评分、异常队列、provenance 和 metrics。


## MVP 架构收敛原则

- Project Store 第一版使用 SQLite + 文件 blob；不引入 Redis/Celery，任务队列也用 SQLite-backed queue。
- Book Model 第一版用内存 Map / SQLite 关系表实现，不以图数据库或图遍历为中心设计接口；接口预留关系查询和未来图查询能力。
- Skill Pack 框架放到 v2；MVP 先用内置 `glossary.json`、`pronunciation.json` 和少量规则模板。
- Agent / Multi-Agent 不进入 MVP 主路径；MVP 采用模块化 LLM call + Harness gate。某类问题反复出现且结构化处理不够时，再升级为专项 Agent。
- Sleep / Background Consolidation 先不作为 MVP 核心；MVP 只做必要的章节摘要、角色/术语整理和预缓存任务。
- 并发执行必须由调度器和 Harness 约束。MVP 只做 `economy` 和 `balanced` 两档，`aggressive/unlimited` 只保留接口。
- Koodo 接入第一版不深改主应用。先实现 Koodo voice plugin 到 Core Server 的最小链路，用它验证本地/局域网/远程 Core Server 的部署体验；完整 Reader Package 播放、高亮同步和离线包能力仍以 Reference Web Reader 作为基准。

## 工程实现基线

第一版实现应优先选择能快速打通 TTS / 音频 / LLM / 本地文件生态的技术栈，而不是围绕阅读器 UI 先做重工程：

```text
后端管线       Python 3.12+
服务层         FastAPI
前端播放器     TypeScript + Vite + Svelte 或轻量 vanilla TS
项目存储       SQLite + 文件 blob
任务队列       SQLite-backed queue，单机 worker pool
LLM Gateway    provider adapter + prompt registry + structured output + rate limit
Speech Gateway FastAPI adapter，优先兼容 /v1/audio/speech，并兼容商业语音 API 和自部署 TTS
前后端通信     REST 负责配置/导入/触发任务，WebSocket 或 SSE 负责进度/预缓存/异常推送
音频处理       ffmpeg / ffprobe
契约层         Python model + JSON Schema，前端从 schema 生成 TypeScript 类型
```

Reader 不依赖 `vn_core`，只消费 Reader Package：`manifest.json`、`timing.json`、cleaned HTML 和 chapter audio。这样 MVP Web Reader、后续 Koodo Reader Package Adapter、Electron Reader 或移动端都可以复用同一包格式。Koodo voice plugin 是更窄的 TTS provider 适配路径，只验证“把文本交给 Core Server 合成音频”，不能替代 Reader Package Contract。

建议目录结构：

```text
voicenovel/
  vn_core/
    contracts/
    store/
    importers/
    adaptation/
    segmenter/
    planner/
    book_model/
    voice/
    tts/
    render/
    timing/
    packaging/              # Reader Package 构建，内部打包 service
    harness/
    orchestration/
    export/                 # M4B / Audiobookshelf / DAW 等外部导出
    preflight/
  vn_server/
    api/
    main.py
  vn_reader/
    src/
      player.ts
      highlighter.ts
      ui/
  integrations/
    koodo_voice_plugin/
    koodo_package_adapter/
  tests/
    golden_books/
  data/
    {book_id}/
      source/
      artifacts/
      store/project.sqlite
      exports/
```

开发顺序应先写 `contracts/`、Project Store 接口、Harness Gate 接口和 golden test book，再写具体 service。这样每个模块一开始就对齐同一套输入输出，而不是后期靠 glue code 拼接。
