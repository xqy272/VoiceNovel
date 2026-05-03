# Project Store 与共享契约

定义唯一真值源、artifact 版本语义、存储形态和 contracts-first 边界。

[返回设计索引](README.md)

## Project Store 设计原则

- 原文不可变，派生产物可重建。
- Reader 只读取已提交的 active artifacts，不读取候选产物。
- 所有 artifact 带 `book_id`、`artifact_version_id`、`schema_version`、`input_hash` 和 active pointer。
- Service 不直接写文件、不直接改 Book Model、不直接改 job state。
- active version 切换必须经过 Harness Gate。
- MVP 从第一天使用 SQLite 管理元数据、状态、索引、job、provenance、exceptions；文件系统只存 EPUB、HTML、WAV/MP3、导出包等大体积 blob。
- JSONL 可作为导出、debug、迁移和人工查看格式，但不作为唯一真值源。
- 数据库物理 schema 可以迭代，但 artifact contract / JSON Schema 必须先稳定。

ID 语义必须拆清：

```text
generation_config_id  生成配置快照：prompt_version / reading_profile / execution_mode / adapter_version 等
run_id                一次具体生成运行：用户点击生成、预缓存批次、重跑任务
artifact_version_id   某个产物版本：segments、reading_plan、audio_take、timing 等
cache_buster          显式强制失效缓存
```

`cache_key` 不应依赖笼统的 run，而应 hash 真正影响输出的字段。用户只改第 5 章某个角色的 `voice_id` 时，不应让第 1-4 章缓存失效；失效范围由 artifact dependency graph 决定。

推荐存储形态：

```text
data/{book_id}/
  source/               # 原始 EPUB/TXT，只读
  artifacts/            # 系统内部产物，由 Harness 管理
    text/               # adaptation ops, cleaned HTML, reading_plan
    audio_segments/     # segment WAV / take
    audio_chapters/     # chapter WAV / intermediate chapter audio
    timing/
    reader_assets/
  store/
    project.sqlite
  exports/              # 用户显式导出，可删除、可重建
    reader_package/
    audiobook/
    daw/
```

`project.sqlite` 负责记录 active version、artifact metadata、job state、provenance、exceptions、Book Model 条目和 voice assignment；`artifacts/` 保存内部生成产物；`exports/` 只保存用户触发导出的派生结果。

## Contracts First

在实现任何 service 前，先定义共享契约：

```text
Segment
TextAdaptationOperation
ReadingPlanEntry
VoiceAssignment
BackendSpeechRequest
AudioTake
TimingEntry
ReaderManifest
JobState
ProvenanceEntry
ExceptionEntry
MemoryPatch
ContextSpec
ContextCapsule
```

契约应同时产出 Python 模型和 JSON Schema；前端可从 schema 生成 TypeScript 类型。所有 service、Project Store、Reader Package 和 Harness Gate 都以这些 contracts 为共同语言。
