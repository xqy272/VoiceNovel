# Book Model、上下文检索与角色记忆

说明小说理解投影、上下文检索服务、角色记忆和跨章节一致性。

[返回设计索引](README.md)

## 6. Book Model

当系统开始跨章节处理小说时，LLM 不只是一次性分析当前段落，还会持续积累、校正和复用小说信息。这个能力不应零散地塞进 prompt 或 Character Memory，而应该设计成每本书的 Book Model。

Book Model 是 Project Store 的运行时投影和索引，不是第二套真值源。它从 Project Store 中的 `intelligence/`、`reading_plan/`、`adaptation ops`、`voice assignments`、`exceptions` 等产物构建，服务 Text Adaptation、LLM Context Pipeline、Character Memory、Voice Registry、TTS 发音和 Harness。

MVP 中它不是图数据库，也不要求预建图抽象层。先用 SQLite 关系表表达角色、别名、术语、场景、决策和证据，接口预留未来图查询能力即可。避免因为过早以 Graph 为中心设计，把简单的关系查询变成复杂图遍历。

词典和知识分层：

```text
SystemLexicon   系统级通用资源：规避写法、常见缩写、多音字、单位读法
UserLexicon     用户级偏好：用户自定义读法、替换习惯、禁用/启用规则
BookModel       本书专有知识：角色、别名、设定、专有术语、场景状态
```

优先级：

```text
UserLock > BookModel > UserLexicon > SystemLexicon > model inference
```

因此通用的 de-obfuscation 和 pronunciation 不应每本书从零积累。Book Model 只持有本书专有的术语、别名、关系、场景和决策；Context Capsule 组装时合并三层资源。

核心存储对象：

- Character：角色、别名、称谓、声线、证据、置信度、锁定状态。
- Alias：人物别名、组织简称、称号、关系称呼。
- Book Glossary：本书专有术语、技能、地名、组织、物品、专有读法。
- Book Pronunciation Overrides：本书专有读法，覆盖 SystemLexicon / UserLexicon。
- Scene State：当前章节/场景活跃角色、地点、时间、对话轮次。
- Relationship：人物关系、阵营、称谓变化。
- Event Timeline：已发生事件的摘要和证据锚点。
- Reading Decisions：已提交的说话人归属、音色绑定、朗读风格、用户锁定和置信度记录。
- Exceptions：低置信度、冲突、待确认项。

记忆项必须带证据和版本：

```json
{
  "memory_id": "mem_char_alias_001",
  "book_id": "book_001",
  "type": "alias",
  "value": {
    "alias": "少主",
    "target_character_id": "char_lu_ming"
  },
  "confidence": 0.87,
  "status": "inferred",
  "evidence_segments": ["ch001_p012_s003", "ch002_p088_s001"],
  "created_by": "llm_context_pipeline",
  "run_id": "run_20260430_001",
  "updated_at": "2026-04-30T12:00:00Z"
}
```

状态类型：

```text
observed       原文明确出现
inferred       LLM 根据上下文推断
user_locked    用户确认或锁定
superseded     被新证据替代
conflict       与已有记忆冲突，进入异常队列
```

更新流程：

```text
Chapter / scene processed
-> Extract candidates
-> Resolve against existing memory
-> Attach evidence and confidence
-> Validate conflicts
-> Commit memory update
-> Retrieve relevant memory for later LLM context
```

检索策略：

- 当前 scene 优先：活跃角色、地点、最近对话状态。
- 当前章节优先：本章已出现角色、术语、别名。
- 全书记忆兜底：角色库、术语表、发音表、用户锁定项。
- 避免无关长上下文污染 prompt，只召回与当前 segment / chapter 相关的 top-k 记忆。

Book Model 需要遵守可追溯原则。任何影响显示文本、TTS 输入、说话人、音色或发音的记忆，都必须能回溯到 Project Store 中的原文证据、LLM 输出和生成版本。必要时可以丢弃内存索引并从 Project Store 重建。

`Reading Decisions` 是记录表，不是决策模块。做出决策的是 `Reading Planner`、`Voice Casting` 和 Harness Gate；Book Model 只保存已经提交的结果、证据、置信度、来源和用户锁定状态。否则状态层会重新变成业务逻辑层。

MVP 的 Book Model 不需要完整图谱，但不能完全没有场景状态。建议最小结构为：

```text
characters
glossary
pronunciation_overrides
decisions
scene_snapshots
```

`scene_snapshots` 可以先用章节/场景级 JSON 字段保存 `active_characters`、`last_speaker`、`last_addressee`、`recent_turn_pattern`、`location` 等轻量信息。它不承担复杂推理，但能显著提升连续对话、称谓变化和省略主语场景下的 speaker attribution。

`scene_snapshots` 不应在 MVP 中引入额外 LLM 调用。它主要从 Reading Planner 的章节级输出、冷启动 quick scan 和 Long Context Book Scanner 的摘要中提取；其中 Reading Planner 是主路径，因为它本来就在分析说话人和对话状态，顺带产出场景快照成本最低。

## Context Retrieval Service

Context Retrieval Service 是 Book Model 的使用层。各模块不应直接把整库塞进 prompt，也不应该由一个中央 Builder 替所有 service 理解业务语义。更好的结构是：

```text
Service declares ContextSpec
-> Context Fetch Engine executes queries
-> Capsule Assembler builds typed Context Capsule
```

每个 service 自己声明上下文需求，Fetch Engine 只负责执行查询和合并 SystemLexicon / UserLexicon / BookModel。这样新增 service 不需要修改一个中央 god object。

```json
{
  "task": "speaker_attribution",
  "segment_ids": ["ch001_p023_s002", "ch001_p023_s003"],
  "context_spec": {
    "scene_state": true,
    "active_characters": {"top_k": 5},
    "recent_dialogue": {"segments_before": 10},
    "aliases": "for_active_characters",
    "glossary": false,
    "pronunciation": false
  },
  "memory_snapshot_id": "memsnap_045",
  "scene": {
    "active_characters": ["char_lu_ming", "char_lin_wan"],
    "recent_turn_pattern": "alternating"
  },
  "characters": [],
  "aliases": [],
  "glossary": [],
  "prior_decisions": [],
  "locked_items": []
}
```

不同任务使用不同 Context Capsule：

- Text Adaptation Capsule：术语、规避写法、发音词典、同章上下文。
- Speaker Attribution Capsule：当前场景、活跃角色、最近对话轮次、别名。
- Voice Casting Capsule：角色画像、重要度、历史声线、用户锁定。
- Pronunciation Capsule：专有词读法、多音字、人名地名、单位数字。
- QA Review Capsule：历史决策、冲突项、异常队列、用户锁定项。

召回原则：

- `observed` 和 `user_locked` 权重大于 `inferred`。
- `conflict` 记忆不能静默进入 prompt。
- 只召回与当前任务相关的 top-k 记忆。
- 并发任务读取固定 `memory_snapshot_id`，完成后提交 proposed patch，由 Harness 决定是否写回。

## 7. Character Memory

跨章节角色一致性必须由角色记忆维护，不能让 LLM 每章自由创建角色。

Character Memory 是 Book Model 的角色子系统，专门负责人物实体、别名、说话人归属、关系和音色绑定。它可以独立建模，是因为角色一致性对多角色听书体验影响最大。

角色归并和说话人识别是 hard problem，尤其是中文小说里的“他说/她道/那少年/少主/师兄/陆公子”。设计上不能假设它 100% 正确，而要依赖置信度、上下文继承和局部修复。

```json
{
  "character_id": "char_lu_ming",
  "names": ["陆明"],
  "aliases": ["陆公子", "少主"],
  "traits": ["male", "young_adult", "cold"],
  "first_seen": "ch001",
  "assigned_voice_id": "cosy_male_cold_001",
  "evidence": ["ch001_p012", "ch002_p088"]
}
```

角色识别流程：

```text
当前章节朗读计划
-> 与全书角色库做 entity resolution
-> 绑定稳定 character_id
-> 绑定或复用 voice_id
-> 低置信度关系进入异常队列
```

置信度策略：

```text
高置信度 -> 自动绑定 character_id
中置信度 -> 继承上下文角色或使用默认旁白/临时声线
低置信度 -> 进入异常队列，但不阻塞后续章节预缓存
```

Character Memory 需要支持角色合并、拆分、别名确认和锁定。用户在 Exception Console 或后续高级控制台中锁定过的角色关系，不应被后续 LLM 自动覆盖。
