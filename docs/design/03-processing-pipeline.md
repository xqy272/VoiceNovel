# 文本处理与朗读计划流水线

覆盖导入、文本适配、中文分句、cleaned package、朗读计划、上下文流水线和长上下文策略。

[返回设计索引](README.md)

## 1. Book Import

输入：

```text
.epub / .txt / .html
```

输出结构化章节和段落：

```json
{
  "book_id": "book_001",
  "chapter_id": "ch001",
  "paragraph_id": "ch001_p023",
  "source_text": "他说：“你既然来了，就别想走。”",
  "source_href": "Text/chapter001.xhtml",
  "source_order": 23,
  "source_dom_hint": "body > section:nth-of-type(1) > p:nth-of-type(23)"
}
```

这里必须保留章节、段落、原始顺序和来源位置，后续所有音频、高亮、缓存、重试都依赖这些锚点。

`source_href` 不能只停留在 Book Import 阶段。它必须贯穿到 segment、reading plan、timing、异常队列和 Reader Package。否则后续 debug、回溯 EPUB、Koodo 接入、章节重建都会缺少来源上下文。

EPUB 第一版至少保留：

```json
{
  "source_href": "Text/chapter001.xhtml",
  "paragraph_id": "ch001_p023",
  "source_order": 23,
  "source_dom_hint": "body > section:nth-of-type(1) > p:nth-of-type(23)"
}
```

后续可扩展 EPUB CFI，但 MVP 不把 CFI 作为硬依赖。

## 2. Text Adaptation

Text Adaptation 是服务 AI 听书的文本适配层，不等同于简单“纠错”，也不是创作性改写。它的目标是在保留原始文本可回溯的前提下，让阅读显示、TTS 朗读、分句、角色识别和术语一致性更可靠。

原则：

```text
source_text 原文永远保留
-> Text Adaptation 输出可追踪 operations
-> text 阅读器显示 + 默认 TTS
-> tts_override 可选，仅 TTS 专用
```

默认不做剧情改写、风格润色或剧情扩写；但允许在可追溯、可回滚、可置信度标记的前提下，进行文本清洗、错别字修复、网文规避写法还原、术语一致性修复、标点断句修正和 TTS 朗读规范化。

文本适配类型：

- 基础清洗：编码问题、乱码、OCR 噪声、重复空格、异常换行。
- 标点与断句修复：缺引号、错引号、中英文标点混用、对话断句异常。
- 错别字 / 谐音字 / 形近字：输入法错误、OCR 形近错误、故意错字。
- 网文规避写法还原：字母缩写、拼音缩写、拆字、符号替代、谐音替代、故意错写。
- TTS 发音规范化：数字、年份、单位、英文缩写、人名地名、多音字。
- 术语一致性：门派、技能、地名、装备、组织、称号等专有词前后一致。
- 角色/对话辅助修复：对话标点、称谓、代词、上下文承接，服务 speaker attribution。

每一次适配都记录为 operation，而不是让 LLM 直接输出一整段自由改写：

```json
{
  "op_id": "op_001",
  "segment_id": "ch001_p023_s002",
  "original": "ZF",
  "normalized": "政府",
  "category": "de_obfuscation",
  "scope": "display_and_tts",
  "confidence": 0.91,
  "risk": "medium",
  "evidence": ["上下文讨论行政部门", "角色称其为官方"],
  "source": "llm_context"
}
```

`scope` 决定适配落点：

```text
display_and_tts  阅读器和朗读都改
tts_only         只改朗读，例如 2024 -> 二零二四
display_only     极少使用
suggest_only     不自动应用，只记录建议
```

Text Adaptation Policy：

```text
conservative  只做基础清洗、标点、明显错别字、TTS 发音规范化
balanced      默认档：高置信度规避写法还原 + 术语一致性
aggressive    更积极还原隐晦表达，但更多进入 optional exception
```

处理流程：

```text
Detect candidates
-> Build Context Capsule
-> LLM proposes operations
-> Validator validates
-> Deterministic applier applies
-> Harness records diff / provenance
```

Text Adaptation 可以分成两个 pass：

- `pre_segment`：清洗、标点、明显错字、会影响分句和阅读显示的修复。
- `pre_tts`：数字读法、多音字、单位、人名地名发音、TTS 控制符等 `tts_override`。

## 3. Chinese Segmenter

中文句子/半句切分是独立模块，不能只靠简单正则，也不能完全交给 LLM。

这是项目里的高风险模块之一。难点不是普通中文断句，而是中文小说对话断句：引号、插话、破折号、省略号、一段多角色、未闭合引号都会让简单规则失效。

第一版目标不是语言学意义上的完美分句，而是“句子/半句粒度足够可听、可高亮、可缓存”。策略是保守规则分句 + 小说场景测试集 + `segmenter_version` + 异常回退。遇到复杂段落时，可以退回整句甚至整段，不强行切错。

第一版采用规则切分为主，LLM 只做异常修复和角色识别。每个 segment 需要记录边界原因、来源位置和分句版本：

```json
{
  "segment_id": "ch001_p023_s002",
  "segmenter_version": "zh_clause_v1",
  "paragraph_id": "ch001_p023",
  "source_href": "Text/chapter001.xhtml",
  "source_order": 23,
  "text": "“你既然来了，",
  "quote_depth": 1,
  "is_dialogue_candidate": true,
  "boundary_reason": "comma_inside_quote"
}
```

需要重点处理：

- `他说：“……”`
- `“……”他说。`
- `“……，”他说，“……”`
- `“……？！ ”`
- `……`
- `——`
- 嵌套引号：`“他说‘不可能’。”`
- 未闭合引号
- 一段内多角色对话

需要维护一套中文小说分句回归测试集。每次修改分句规则，都必须验证上述边界场景，避免策略变更破坏历史生成包。

## segment_id 稳定性约束

`segment_id` 对某个 package / `segmenter_version` 稳定，而不是跨所有算法版本永久稳定。建议规则：

```text
segment_id = chapter_id + paragraph_id + segment_index
cache_key 额外包含 segmenter_version
```

设计约束：

- 同一本书一旦进入生成，锁定 `segmenter_version`。
- 修改分句算法后，新书使用新版本，旧书不自动迁移。
- 用户选择“重建分句”时，创建新的 `run_id`，并产出新的 `artifact_version_id` / `package_version`。
- 缓存键必须包含 `segmenter_version`。
- 局部文本小修可以保留原 `segment_id`。
- split / merge segment 时生成 supersede mapping：

```json
{
  "old_segment_id": "ch001_p023_s002",
  "new_segment_ids": ["ch001_p023_s002a", "ch001_p023_s002b"],
  "reason": "segmenter_version_upgrade"
}
```

## 4. Cleaned Reading Package

Cleaned Reading Package 不拥有独立的文本修改权。所有显示文本和 TTS 文本的修改决策都由 Text Adaptation 以 operation 形式产生，并经过 Harness 校验。Cleaned Reading Package 只负责应用已批准的 operations，生成阅读器可消费的文本产物和稳定 DOM 锚点。

允许进入 cleaned text 的修改包括：

- 基础清洗。
- 错别字 / OCR 噪声。
- 标点与明显断句。
- 高置信度网文规避写法还原。
- 术语一致性修复。

不默认进入 cleaned text 的修改：

- 风格润色。
- 剧情扩写。
- 新增台词。
- 大幅段落重写。

生成可阅读文本包：

```html
<p data-pid="ch001_p023">
  <span data-seg-id="ch001_p023_s001">他说：</span>
  <span data-seg-id="ch001_p023_s002">“你既然来了，</span>
  <span data-seg-id="ch001_p023_s003">就别想走。”</span>
</p>
```

阅读器高亮只需要：

```js
document.querySelector('[data-seg-id="ch001_p023_s002"]')
  .classList.add('playing')
```

## 5. LLM Reading Planner

LLM 输出朗读计划 JSONL。它不是为了把文本改造成有声剧剧本，而是给每个 segment 增加说话人、朗读风格、轻量增强和置信度信息。涉及显示文本或 TTS 文本的修复与规范化，应走 Text Adaptation 的可追踪 operation，而不是在 Reading Planner 里自由改写。

执行依赖必须明确：

```text
LLM Context Pipeline
-> Context Capsule
-> LLM Reading Planner
-> Character Memory Resolution
-> proposed reading decisions
-> Harness gate
```

Reading Planner 不直接扫描全书，也不直接读取整库记忆。它只接收 Context Retrieval Service 为当前任务构造的 `Context Capsule`，避免 prompt 污染、成本失控和错误记忆扩散。

术语统一：

```text
Reading Plan        产物
Reading Planner     服务
reading_plan.jsonl  导出/调试格式
```

中文统一称为“朗读计划”。避免继续混用旧称、剧本化称呼或脚本化称呼。

## TTS 输入合成顺序

Text Adaptation 和 Reading Planner 都会影响最终 TTS 输入，但权限不同，合并顺序必须固定：

```text
source_text
-> Text Adaptation pre_segment
-> display_text / segments
-> Text Adaptation pre_tts
-> tts_base_text
-> Reading Plan reading_style / enhancements
-> TTS Adapter Formatter
-> final backend input
```

`Reading Planner` 不直接写 `tts_override`，它只输出 `speaker_id`、`reading_style`、`enhancements`、`prosody_hint` 和 `voice_constraints`。如果某个 TTS 后端需要内联控制符，由 `TTSInputComposer` 把文本、朗读计划、音色和后端能力合成为统一请求，再交给 adapter 转成具体后端参数。这样文本规范化、朗读风格和后端 prompt 不会互相抢修改权。

`TTSInputComposer` 是正式契约模块，不是各 adapter 里的临时 glue code：

```text
tts_base_text
+ reading_style
+ prosody_hint
+ enhancements
+ voice_assignment
+ backend_capabilities
-> BackendSpeechRequest
```

职责边界：

- Text Adaptation 负责文本修复、发音规范化和 `tts_override`。
- Reading Planner 负责说话人、情绪、语气和语义级停顿提示。
- Voice Casting 负责稳定 `voice_id`。
- `TTSInputComposer` 负责合并为后端无关的 `BackendSpeechRequest`。
- `BackendSpeechRequest.text` 是最终朗读文本，已经应用 `tts_base_text`、`tts_override`、朗读风格和后端格式约束；adapter 不再关心它来自原文、显示文本还是发音覆盖。
- TTS Adapter 只负责把 `BackendSpeechRequest` 转为 CosyVoice、Edge-TTS、ChatTTS 等后端参数。

MVP 中 Reading Planner 不输出精确毫秒级停顿字段。间隔时间由 Timing Builder 全权负责。Reading Planner 只允许输出语义级 `prosody_hint`：

```text
short_pause / normal_pause / long_pause
```

Timing Builder 根据 segment 类型、说话人变化、段落边界和 `prosody_hint` 决定具体 gap。这样可以避免 per-segment pause 与全局 gap 规则冲突。

```json
{
  "segment_id": "ch001_p023_s002",
  "segmenter_version": "zh_clause_v1",
  "source_href": "Text/chapter001.xhtml",
  "text": "“你既然来了，",
  "speaker_candidate": "陆明",
  "speaker_id": "char_lu_ming",
  "speaker_confidence": 0.88,
  "reading_style": {
    "emotion": "restrained",
    "intensity": 0.35,
    "prosody_hint": "normal_pause"
  },
  "enhancements": {
    "sfx": null,
    "bgm": null
  },
  "voice_constraints": {
    "gender_style": "male",
    "age_range": "young_adult",
    "tone": ["cold", "restrained"]
  }
}
```

重点是 harness，不是人工逐条审校。低置信度段落进入异常列表，但不阻塞整本书继续预缓存。

朗读增强分层：

```text
faithful        忠实朗读：少角色、少情绪、最稳定
enhanced        增强听书：角色音色 + 轻情绪 + 停顿优化，默认推荐
dramatic-lite   轻剧场：更多情绪/音效/混音，但仍不改写原文
```

MVP 只做 `faithful` 和 `enhanced`。`dramatic-lite` 作为后续实验开关，不进入主路径。

增强约束：

- `enhancements` 不能修改 `text`。
- 增强失败时必须能降级为纯 TTS。
- 增强参数必须进入 `cache_key`。
- 增强参数必须进入 License Gate、Cost Planner 和 Provenance。

## 5.1 LLM Context Pipeline

LLM 处理能力不应靠给每个难题单独写死逻辑，也不应只依赖一个通用 prompt。更稳的做法是：先建设通用上下文产线，再针对高频难题挂专项策略。

通用处理流程：

```text
Chinese Segmenter
-> Detect Problem Pattern
-> Scene Context Builder
-> LLM Reading Planner / Speaker Attribution
-> Character Memory Resolution
-> Confidence / Fallback
-> TTS
```

通用上下文包：

```json
{
  "target_segments": ["ch001_p023_s001", "ch001_p023_s002"],
  "problem_patterns": ["continuous_quote_dialogue"],
  "left_context": "前 5-10 个句子/半句",
  "right_context": "后 2-5 个句子/半句",
  "active_characters": [
    {"character_id": "char_lu_ming", "names": ["陆明"], "aliases": ["少主"]},
    {"character_id": "char_lin_wan", "names": ["林晚"], "aliases": []}
  ],
  "recent_dialogue_state": {
    "last_explicit_speaker": "char_lu_ming",
    "last_addressee": "char_lin_wan",
    "turn_pattern": "alternating"
  },
  "scene_summary": "两人在客栈房间内争执是否离开。"
}
```

连续纯引号对话只是其中一个专项策略。其他高频难题也应走同一套上下文产线：

- 连续纯引号对话：多句对话没有“他说/她道”。
- 一段多角色对话：同一段内出现多个发言者。
- 指代密集段落：大量“他/她/那人/少年/女子”。
- 别名密集段落：角色被称为师兄、少主、陆公子等。
- 场景切换：上一段和下一段角色集合变化明显。
- 插叙/回忆：当前活跃角色与时间线变化。
- 省略主语动作句：动作承接暗示说话人。

LLM 输出必须包含置信度和证据：

```json
{
  "segment_id": "ch001_p023_s004",
  "speaker_id": "char_lin_wan",
  "speaker_confidence": 0.74,
  "evidence": ["连续双人对话，上一句为 char_lu_ming", "回答语气承接上一问"],
  "fallback_policy": "use_scene_dialogue_voice_if_uncertain"
}
```

无人审查时的通用 fallback 策略：

- 高置信度时自动采用 LLM 结果。
- 中置信度时继承 scene state、最近显式说话人、对话轮次或 Character Memory。
- 低置信度时使用中性对话声线、旁白声线或当前章节 fallback voice。
- 不确定但不影响播放的问题标记为 optional exception，用户想管再管。
- 无人处理时系统继续预缓存和播放，不因角色归属不确定而中断听书。

## 5.2 Long Context Strategy / 1M Context Model Usage

本项目应承认并利用现代 LLM 的 1M 级上下文能力，但不能把它简单理解成“每个任务都塞整本书”。1M context 是 Book Model 构建和一致性审计能力，不是日常每个 segment 的默认 prompt 形态。

推荐三层调用策略：

```text
Book Scan
  大上下文 / 1M context
  读取全书或大范围章节，生成角色表、别名、术语、世界观、章节摘要、主线关系

Chapter Planning
  当前章 + 前后窗口 + Book Model
  生成 reading_plan、speaker attribution、章节级文本适配和语音约束

Segment Repair
  小窗口局部调用
  处理低置信度对话、疑难分句、局部错别字、局部角色归属冲突
```

`Long Context Book Scanner` 的产物不直接进入 TTS，而是进入 Book Model：

- characters：角色、别名、称谓、首次出现、重要度。
- glossary：世界观术语、组织、地名、功法、装备、专有名词。
- pronunciation candidates：人名、地名、多音字、缩写和规避写法。
- chapter summaries：章节摘要和场景状态。
- relationship hints：角色关系候选，不在 MVP 做复杂图推理。
- risk flags：可能的角色混淆、时间线变化、称谓变化、连续对话密集章节。

长上下文适合以下场景：

- 初次导入时快速建立全书或前若干章 Book Model。
- 伪实时预缓存前，提前扫描当前位置后方若干章。
- 后台 consistency audit：检查角色归并、术语读法、声线分配是否前后冲突。
- 用户主动全书烘焙前，做一次全书级 planning。
- Sleep / Background Consolidation 阶段整理已生成章节。

长上下文不应替代 Context Fetch Engine，原因是：

- 成本和延迟不适合用户点击听书后的实时路径。
- 输出长度仍有限，无法一次可靠输出全书所有 segment 级结果。
- 长上下文注意力不是绝对可靠，仍需 schema、证据、置信度和 Harness Gate。
- 第三方 API 发送全文有隐私和版权风险，必须由用户配置和 Preflight Check 管理。
- 移动阅读器场景下，播放启动不能被超大 prompt 阻塞。

因此，默认运行方式是：`Long Context Book Scanner` 负责建立和审计 Book Model；日常生产任务仍通过 `ContextSpec -> Fetch Engine -> typed Context Capsule` 获取最小充分上下文。二者是互补关系，不是替代关系。
