# Harness、Timing、Packaging 与 Reader

定义质量控制平面、timing 构建、Reader Package、Web Reader MVP、Koodo 接入分层和 Exception Console。

[返回设计索引](README.md)

## 13. Harness Engineering

Harness Engineering 是全项目控制平面，不只是 LLM 端的 QA。所有写入 Project Store 的操作都必须经过 Harness Gate，包括 artifact 写入、Book Model patch、job state 更新、exception 写入和 active version 切换。它横跨：

```text
导入 -> 文本适配 -> 分句 -> 朗读计划 -> 小说记忆 -> 角色 -> 音色
-> TTS -> ASR/音频质检 -> timing -> 阅读器播放 -> 预缓存调度
```

核心能力：

- Schema Validator：所有 JSONL、manifest、timing、voice、job 输出必须过 schema。
- Invariant Checker：段落不能丢、不能乱序、不能重复，`segment_id` 必须稳定。
- Artifact Registry：记录 cleaned HTML、reading plan、take、章节音频、timing、Reader Package、导出包的位置和版本。
- Job State Tracker：记录每个 chapter / segment 的阶段、状态、优先级、重试次数。
- Retry Policy：按异常类型决定重试、换 take、换后端、回滚、降级或进入异常队列。
- Quality Scorer：统一计算文本差异、角色置信度、ASR 分数、音频质量、timing 覆盖率。
- Provenance Logger：记录模型、prompt、输入 hash、输出 hash、TTS 参数、voice_id 和生成时间。
- Exception Queue：只暴露无法自动修复的少量异常。
- Metrics Dashboard：展示预缓存进度、失败率、成本、耗时、缓存命中率和剩余工作量。

Harness Gate 接口需要在 MVP 最开始定义：

```text
validate(artifact_type, proposed_data, context)
  -> pass
  -> retry(reason)
  -> fail(reason)
  -> stale(reason)
```

每个 service 开发时都对齐 Gate 的契约产出结果，而不是事后补校验。

自动质量闸包括：

- LLM 输出不能丢段、乱序、重复。
- Text Adaptation operation 必须可追踪、可回滚，差异超过阈值标记 suspicious。
- Book Model 更新必须有证据锚点和置信度。
- 同一角色跨章节音色保持一致。
- TTS 后跑 ASR 反校验。
- ASR 文本和目标文本差异过大则重试。
- 检查静音、截断、音量、爆音、时长异常。
- 多次失败才暴露给用户处理。

异常默认先自动处理，而不是直接交给人工：

```text
asr_mismatch       -> 换 take 重试
tts_timeout        -> 重试或切换 fallback 后端
voice_missing      -> 使用 fallback voice，并标记待处理
large_text_diff    -> 回滚该句校对或进入异常队列
speaker_uncertain  -> 继承上下文角色、降低置信度或进入异常队列
timing_missing     -> 重新构建章节音频和 timing
cache_stale        -> 新建 run_id 或 cache_buster 后重跑
```

自动策略失败后，异常进入 Exception Console 或后续高级控制台，而不是阻塞全书：

```text
low_confidence_speaker
large_text_diff
asr_mismatch
tts_timeout
audio_too_short
voice_missing
cache_stale
timing_missing
```

## 14. Timing Builder

句子/半句高亮不需要逐字精度，但 timing 不能靠估算。

生成方式：

```text
每个 segment 生成 wav
-> 用 ffprobe / sample count 读取真实时长
-> 按 segment 类型插入可配置静音间隔
-> 拼接章节音频
-> 累加真实 duration + gap duration
-> 写 timing.json
```

中文听书不能把所有 TTS 片段硬拼接，否则句子之间会显得太赶。Timing Builder 需要显式管理间隔：

```json
{
  "audio_spacing": {
    "clause_gap_ms": 120,
    "sentence_gap_ms": 180,
    "paragraph_gap_ms": 350,
    "chapter_intro_silence_ms": 500,
    "chapter_outro_silence_ms": 800
  }
}
```

间隔本身也必须进入 timing 累加。高亮通常只覆盖有文本的 segment；gap 时间内可以保持上一句高亮、清除高亮，或使用阅读器配置决定。

推荐存毫秒和 sample 两套字段：

```json
{
  "segment_id": "ch001_p023_s002",
  "segmenter_version": "zh_clause_v1",
  "chapter_audio": "Chapter_001.mp3",
  "start_ms": 128400,
  "end_ms": 130120,
  "gap_after_ms": 180,
  "start_sample": 6163200,
  "end_sample": 6245760,
  "sample_rate": 48000
}
```

浏览器播放用 `start_ms/end_ms`，`sample` 用于调试和后续精确重建。MP3 存在 encoder delay 和 seek 精度问题，第一版可以接受；若后续要更准，可输出 M4A/Opus 或无损章节音频。

`timing.json` 表示章节时间轴，不应绑定死某一种音频编码。音频文件只是导出载体。Reader Package 需要声明 timing profile：

```json
{
  "audio_codec": "mp3",
  "timing_unit": "ms",
  "seek_precision": "approximate",
  "encoder_delay_ms": 0
}
```

内部尽量保留 segment WAV 和 canonical timeline。导出 MP3、M4A、Opus 时，可以为不同编码生成对应 timing profile。第一版 MP3 足够，因为句子/半句高亮容忍几十到几百毫秒误差；如果后续追求更准，可以切到 M4A/Opus 或采用分段播放。

## 15. Packaging Service

`Packaging` 是 Service Layer 的正式模块，负责把已经通过 Harness Gate 的 active artifacts 组合成阅读器可消费的 Reader Package。它不是 Export Targets 的泛称，也不负责 M4B、Audiobookshelf、DAW 等外部格式导出。

输入：

```text
cleaned_html
segments
reading_plan
voice_assignments
audio_manifest
chapter_audio
timing
package_profile
```

输出：

```text
Reader Package
  manifest.json
  cleaned HTML / EPUB-derived content
  segments.jsonl
  voices.json
  audio_manifest.json
  timing.json
  chapter audio
```

Packaging 不调用 LLM，不调用 Speech Gateway，不重新做文本修改或音频生成。它只读取 Project Store 中当前 active 的上游 artifact，校验版本依赖，生成新的 `reader_package` artifact，并通过 Harness Gate 提交。

Packaging 与 Export 的边界：

```text
Packaging
  内部产物，服务阅读器同步播放，是主路径

Export
  用户显式触发的外部产物，如 MP3 per chapter、M4B、Audiobookshelf metadata、Audacity/DAW package
  可删除、可重建，不是 Project Store 的核心真值
```

## 15.1 Reader Package Contract

最终给阅读器的不是裸 MP3，而是一组版本化包：

```text
manifest.json
book.cleaned.xhtml / book.cleaned.epub
segments.jsonl
voices.json
audio_manifest.json
timing.json
Chapter_001.mp3
```

`manifest.json` 示例：

```json
{
  "package_version": "0.1",
  "book_id": "book_001",
  "title": "示例小说",
  "text_format": "cleaned-html",
  "highlight_granularity": "sentence_clause",
  "segmenter_version": "zh_clause_v1",
  "audio_codec": "mp3",
  "timing_unit": "ms",
  "seek_precision": "approximate",
  "segments": "segments.jsonl",
  "timing": "timing.json",
  "audio_manifest": "audio_manifest.json",
  "voices": "voices.json"
}
```

`timing.json` 示例：

```json
{
  "segment_id": "ch001_p023_s002",
  "segmenter_version": "zh_clause_v1",
  "chapter_audio": "Chapter_001.mp3",
  "start_ms": 128400,
  "end_ms": 130120,
  "gap_after_ms": 180
}
```

阅读器只需要按播放时间找到 `segment_id`，然后高亮对应 span。

## 15.2 Koodo 接入分层

Koodo 不应从第一天就作为 deep fork 目标。它已有插件系统，语音插件能够把当前朗读文本交给外部 TTS 服务并返回音频路径；这足以作为 VoiceNovel Core Server 的第一阶段接入探针，但还不足以默认承载完整 AI 听书体验。

推荐分三层推进：

```text
Koodo Voice Plugin
  只验证 TTS provider 接入：text -> Core Server -> audio path
  不消费 Reader Package，不负责 timing/highlight/offline package

Koodo Reader Package Adapter
  如果插件或轻量扩展点能访问章节内容、播放控制和 DOM 高亮，则消费 Reader Package
  负责 manifest、segments、chapter audio、timing、预缓存状态和断点续听

Koodo thin fork
  当插件无法稳定控制 cleaned content 渲染、章节音频、timing、高亮或离线缓存时进入
  只放适配层，不把 VoiceNovel pipeline 写入 Koodo
```

Koodo voice plugin 的成功标准是：可以配置 Core Server 地址、选择 voice/profile、把 Koodo 当前 TTS 文本交给 Core Server、返回可播放音频，并在失败时回退到普通 TTS。它不是 Reader Package Contract 的验收标准。

Koodo Reader Package Adapter / thin fork 的成功标准是：能够按 `segment_id` 高亮 cleaned content，按章节播放预生成音频，读取 `timing.json`，展示当前章/下一章预缓存状态，支持离线包和断点续听。

## 15.3 Web Reader MVP Spec

Web Reader 是 MVP 的验证端，不是后期附属页面。第一版不追求完整书库管理，但必须稳定消费 Reader Package 并完成句子/半句高亮播放。

最低规格：

```text
播放器          HTMLAudioElement 优先；Web Audio API 留作后续增强
音频粒度        按章节加载 chapter audio，不整书一次加载
timing 加载     按章节加载 timing.json，可预取下一章 timing
同步机制        timeupdate + requestAnimationFrame；按当前时间二分查找 active segment
高亮粒度        只使用 segment_id，高亮句子/半句 DOM span
跳章/跳句       切换 chapter audio + timing + scroll anchor
断点续听        保存 chapter_id、segment_id、audio_time_ms
预缓存状态      显示当前章、下一章 ready / rendering / failed
异常降级        缺少角色音色时继续用旁白或 fallback voice 播放
```

Reader 不直接访问 Project Store，也不 import 后端 core。它只读取 `manifest.json`、cleaned HTML、chapter audio、`timing.json` 和必要的状态 API。这样后续 Koodo Reader Package Adapter、Electron Reader 或移动端 Reader 都可以复用同一 Reader Package Contract。

## 16. Exception Console

Exception Console 是轻量异常控制台，不是全文 Editor。它的定位是“异常驱动的修复台 + 关键锁定管理”，用于处理 harness 无法自动收敛的问题，而不是让用户逐条审完整本书。后续可以扩展为更完整的高级控制台，但默认听书路径不依赖人工审校。

异常修复能力：

- 查看角色归属异常。
- 查看 LLM 修改过大的句子。
- 单句/单段重新生成。
- 单句重新合成。

锁定管理能力：

- 锁定角色声线。
- 锁定文本，不允许后续 LLM 再改。
- 锁定某个 selected take，避免后续自动重试覆盖。
- 锁定角色合并/拆分结果，保护 Character Memory。

这能在保持自动化主路径的同时，给长篇小说提供可控的人工介入入口。
