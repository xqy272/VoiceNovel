# 调度、预缓存、并发与 Take Library

覆盖 Render Queue、预缓存调度、并发执行、断点续传、缓存键和 take 选优。

[返回设计索引](README.md)

## 10. Render Queue / Prefetch Scheduler

AI 听书需要“假实时”体验，因此渲染队列不是单纯批处理，而是围绕播放位置动态调度。

启动与冷启动策略：

```text
用户打开 AI 听书
-> 检查当前位置章节是否已有可播放音频和 Book Model 基础上下文
-> 如果 Book Model 冷启动，先运行轻量 bootstrapping
-> 快速扫描目录/章节标题/当前章和后 1-2 章
-> 抽取高频人名候选、术语候选、对话密度、章节摘要
-> 建立初始 characters / glossary / scene_state
-> 优先生成当前位置的最小可播放缓冲
-> 达到最小可播放缓冲后开始播放
-> 后台持续推进 Audio Horizon 和 Intelligence Horizon
-> 用户跳转较远时，取消低优先级远端任务，优先渲染新位置
```

冷启动不是独立功能，而是“假实时预缓存”的启动阶段。它不做全书理解，也不做复杂 sleep；只做足够让当前章节的 Text Adaptation、Reading Planner、Voice Casting 不从空上下文开始的最小理解。

冷启动需要固定路径，不能依赖自由探索式 agent：

```text
Phase 1 本地快速路径
  EPUB/TXT 当前章导入 -> 规则清洗 -> 保守分句 -> 冷启动 fallback voice
  目标：尽快得到前 N 个可 TTS 的 segment，不等待完整 Book Model

Phase 2 LLM 快速理解
  当前章 + 左右窗口 quick scan -> 角色候选、别名、术语、对话密度、初始 scene_snapshot
  结果以 proposed memory patches 进入 Harness Gate

Phase 3 最小可播放缓冲
  优先生成前 20-40 个 segment 或约 2-3 分钟音频
  旁白音色和临时角色音色可以先行，角色识别结果返回后再改善后续 segment

Phase 4 后台完善
  Audio Horizon 跟随播放位置推进
  Intelligence Horizon 提前整理后续章节
```

第一段可播放音频不能被完整 Book Model 阻塞。若 LLM quick scan 超时，系统应使用旁白/中性对话声线先开始播放，并把后续章节质量提升交给后台预缓存。

冷启动 fallback voice 使用固定映射，不走完整 Voice Casting：

```text
narrator         -> default_narrator_voice
male_dialogue   -> default_male_dialogue_voice
female_dialogue -> default_female_dialogue_voice
unknown_dialogue-> default_dialogue_voice
fallback         -> default_narrator_voice
```

Phase 2 quick scan 或 Reading Planner 返回角色识别结果后，已识别角色再进入正常 Voice Casting；中低置信度角色继续使用 fallback voice，并在后续章节有更多证据时再稳定绑定。

建议默认窗口：

```json
{
  "startup_buffer_segments": 80,
  "startup_buffer_minutes": 3,
  "prefetch_chapters_ahead": 2,
  "keep_hot_chapters_before": 1,
  "keep_hot_chapters_after": 3,
  "max_background_jobs": 2
}
```

任务优先级：

```text
P0 当前播放 segment 缺失或失败
P1 当前章节剩余部分
P2 下一章
P3 后续预缓存章节
P4 用户主动全书烘焙
```

调度器同时维护两个 horizon：

```text
Audio Horizon        已经可播放的音频范围
Intelligence Horizon 已经理解/整理过的小说范围
```

例如用户正在听第 10 章：

```text
Audio Horizon: 第 10-12 章
Intelligence Horizon: 第 10-15 章
```

这意味着系统可以先整理后面更多章节的角色、术语、场景和发音信息，再把音频生成资源优先给当前播放附近的章节。Audio Horizon 服务“不要断播”，Intelligence Horizon 服务“越往后越稳定”。

用户可主动触发：

- 烘焙当前章节
- 烘焙选定章节
- 从当前位置继续烘焙
- 烘焙全书
- 暂停/恢复后台烘焙
- 仅 Wi-Fi / 仅插电 / 限速烘焙

## 10.1 Parallel Execution

并发执行是本项目的重要能力，但不能无脑并发。它服务两个目标：降低用户等待时间，以及缩短长篇小说处理耗时。

可以并发的任务：

- 不同章节的 Text Adaptation 候选检测。
- 章节摘要生成。
- 术语/角色候选抽取。
- TTS segment 合成。
- ASR 反校验。
- 音频质量检测。
- Context Capsule 预生成。
- 后续章节预缓存。

不应无约束并发的任务：

- 同一角色的最终归并写入。
- 同一 segment 的互斥文本修改。
- 同一章节 timing 构建。
- 同一个 `voice_id` 的资源密集型克隆任务。
- 依赖前序记忆状态的强一致决策。

并发规则：

```text
读可以并发，写要受控
候选抽取可以并发，最终提交要事务化
TTS 可以高度并发，但受 GPU/API 限流
低风险章节可 speculative execution
高风险决策必须经过 Harness gate
```

Orchestrator 应按 artifact dependency DAG 调度，而不是按“章节阶段”隐式串行。典型依赖：

```text
source_paragraph
-> adaptation_ops
-> cleaned_text
-> segments
-> reading_plan
-> voice_assignment
-> tts_request
-> audio_take
-> chapter_audio
-> timing
-> reader_package

segments + pre_tts_ops + reading_plan + voice_assignment -> tts_request
audio_take + spacing_config -> timing
cleaned_html + timing + chapter_audio -> reader_package
```

MVP 不需要图数据库或复杂版本树，但需要轻量依赖记录，否则无法判断 timing、audio、reader package 是否基于当前 active 输入生成。SQLite 中保留一张表即可：

```text
artifact_dependencies(
  artifact_version_id,
  depends_on_artifact_version_id,
  dependency_role
)
```

第一版只做两件事：提交产物时记录依赖；读取 active artifact 时校验依赖是否仍为 active。复杂级联清理、版本树 UI 和批量迁移可以放到 v2。

`pre_tts` 和 `Reading Planner` 可以并行，因为它们都不改变 segment 结构。`Voice Casting` 在 Character Memory / voice_constraints 足够稳定后即可提前运行，不必等待整章 Reading Plan 完全结束。

每个 job 应记录：

```text
task_type
input_artifact_versions
output_artifact_type
memory_snapshot_id
cache_key
```

并发档位：

```text
economy       成本优先，少并发
balanced      默认，适度并发
aggressive    速度/质量优先，多路 LLM + 多 take，MVP 只保留接口
unlimited     用户明确选择，不限制成本，MVP 不实现
```

MVP 只实现 `economy` 和 `balanced`。`aggressive/unlimited` 进入 Cost Planner 和接口设计，但不进入第一阶段实现。

## 11. Job Orchestrator / 断点续传

Orchestrator 是系统里唯一负责副作用编排的模块。Service Layer 只返回结果和 proposed patches，不直接写 Project Store、不直接更新 Book Model、不直接切换 job state。Orchestrator 负责把 service result 送入 Harness Gate，并在通过后提交 artifact、memory patch、job state 和 provenance。

核心执行循环：

```text
while has pending jobs:
  task = priority_queue.pop()
  if cache_key has active success artifact:
    mark done
    continue
  context_spec = service.context_spec(task)
  capsule = ContextFetchEngine.fetch(context_spec)
  result = service.execute(task, capsule)
  decision = HarnessGate.validate(result)
  pass      -> commit artifact + apply memory patches + record provenance
  retry     -> requeue with backoff / priority adjustment
  fail      -> write exception
  stale     -> keep candidate or discard, then requeue against newer snapshot
```

每个阶段都按 chapter / segment 持久化状态：

```json
{
  "job_id": "job_001",
  "generation_config_id": "gencfg_001",
  "run_id": "run_20260430_001",
  "memory_snapshot_id": "memsnap_045",
  "execution_mode": "balanced",
  "stage": "tts_render",
  "unit_id": "ch001_p023_s002",
  "status": "done",
  "priority": "P1",
  "input_artifact_versions": ["segver_001", "planver_003", "voiceassign_002"],
  "output_artifact_type": "audio_take",
  "input_hash": "sha256...",
  "cache_key": "sha256...",
  "cache_buster": null,
  "artifact": "audio/ch001/ch001_p023_s002_take001.wav",
  "retry_count": 1
}
```

断点续传依赖：

- `input_hash`
- `voice_id`
- `engine`
- `engine_params`
- `artifact`
- `prompt_version`
- `adapter_version`
- `generation_config_id`
- `run_id`
- `cache_buster`
- `memory_snapshot_id`
- `execution_mode`

缓存键不能只看文本。建议：

```text
cache_key = hash(
  text,
  tts_override,
  segmenter_version,
  voice_id,
  reading_style,
  enhancements,
  engine,
  engine_params,
  prompt_version,
  adapter_version,
  system_lexicon_version,
  user_lexicon_version,
  book_model_snapshot_id,
  cache_buster
)
```

`generation_config_id` 用于把 prompt、profile、adapter、execution mode 等配置快照归组；`run_id` 表示一次具体运行；`artifact_version_id` 标识具体产物版本。`cache_key` 只依赖真实影响输出的字段，不依赖笼统的 run。`cache_buster` 用于调试期或用户手动重跑，显式让缓存失效。

同一 `cache_key` 不重复生成。用户跳转时只调整任务优先级，不删除已完成产物；用户主动“重新生成”时创建新的 `run_id` 或写入 `cache_buster`。局部修改只应通过 artifact dependency graph 使受影响的下游 artifact 失效。

## Memory Snapshot 并发隔离

MVP 中 `memory_snapshot_id` 由 Orchestrator 创建和管理。默认策略是：章节 planning 开始时创建一个 chapter-level snapshot，同一章的 Text Adaptation、Reading Planner、Speaker Attribution 读取同一个 snapshot；这些 service 输出 `MemoryPatch(base_snapshot_id)`，章级 planning 结束后由 Harness Gate 合并为新的 Book Model snapshot。

Long Context Book Scanner、后台 consistency audit 和用户主动全书烘焙可以创建 batch-level snapshot，不强行套用“每章一个”的规则。TTS 任务通常不直接读 Book Model snapshot，而依赖已经提交的 `tts_base_text`、`reading_plan` 和 `voice_assignment`。

并发任务可以读取不同的 `memory_snapshot_id`，这是正常情况。关键是提交时必须检查依赖版本：

```text
依赖版本仍为 active
  -> 可以提交
依赖版本已过期但结果仍有参考价值
  -> 存为 candidate，不切 active
依赖版本与当前 active 冲突
  -> 标记 stale，重新入队
```

TTS 任务不直接依赖 Book Model，而依赖已提交的 `tts_base_text`、`reading_plan` 和 `voice_assignment`。`memory_snapshot_id` 可写入 provenance 方便追溯，但不应成为 Speech Gateway 调用的必要输入。

## 12. Take Library

每个 `segment_id` 可以有多个生成结果，系统自动选择最佳 take。

Take Library 覆盖的是 TTS 单 segment 维度的多次合成与选优。更高层的多方案 LLM、多个 speaker attribution candidate、多套 text adaptation candidate，属于 Parallel Execution / Cost Planner 的 `aggressive` 模式，MVP 不实现，只保留接口。

```json
{
  "segment_id": "ch001_p023_s002",
  "selected_take_id": "take_002",
  "takes": [
    {
      "take_id": "take_001",
      "path": "audio/ch001/ch001_p023_s002_take001.wav",
      "asr_score": 0.91,
      "loudness_ok": true,
      "selected": false
    },
    {
      "take_id": "take_002",
      "path": "audio/ch001/ch001_p023_s002_take002.wav",
      "asr_score": 0.97,
      "loudness_ok": true,
      "selected": true
    }
  ]
}
```

这样可以支持自动重试、手动重配、保留最佳结果和后期重新打包。
