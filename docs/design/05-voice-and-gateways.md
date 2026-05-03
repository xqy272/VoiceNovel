# 音色体系与模型网关

定义 Voice Registry、音色生命周期、LLM Gateway 和 Speech/TTS Gateway。

[返回设计索引](README.md)

## 8. Voice Registry / Voice Lifecycle

自定义音色不是静态列表，而是完整生命周期：

```text
imported -> analyzed -> tagged -> tested -> approved -> assigned -> archived
```

音色结构：

```json
{
  "voice_id": "cosy_zh_female_cold_001",
  "name": "清冷成年女声",
  "backend": "cosyvoice",
  "type": "builtin",
  "tags": ["female", "adult", "cold", "calm"],
  "language": ["zh"],
  "quality": {
    "technical_quality": 0.91,
    "asr_confidence": 0.88,
    "noise_score": 0.95,
    "speaker_stability": 0.9,
    "human_rating": null,
    "overall_quality": 0.9
  },
  "license": "user_owned",
  "status": "approved"
}
```

用户上传音频后，系统需要完成：

- 音频质量检测
- 说话人时长检测
- ASR 转写
- 语言识别
- 音色标签生成
- 试听样例生成
- 授权/来源标记

LLM 不自由创造音色名，只能在候选音色中选择稳定 `voice_id`。

音色匹配流程：

```text
角色画像
-> voice_constraints
-> Voice Registry 候选召回
-> 打分排序
-> sticky assignment
-> 用户可选锁定
```

映射打分因素：

- 语言匹配。
- 性别、年龄、气质标签匹配。
- 音色质量分。
- 许可证和用户声明用途是否允许。
- 用户是否锁定。
- 是否已经分配给重要角色。
- 角色重要度。
- 后端可用性。
- 生成成本。

LLM 可以提取角色画像，也可以在 Top-K 候选中解释选择，但最终绑定必须是稳定 `voice_id`。一旦角色绑定音色，默认不随章节漂移。

`quality_score` 不应是一个不可解释的神秘数字，而应由多个来源聚合：

- 音频质量检测：噪声、响度、截断、静音。
- ASR 结果：参考音频可转写度。
- TTS 试听生成后的稳定性。
- 用户可选评分。
- 内置音色的人工标注。

## 8.1 LLM Gateway / Model Communication

本项目应明确围绕 API-first 的 LLM 通讯系统设计。即使后续支持本地模型，也应把本地模型包装成 endpoint，而不是让 Text Adaptation、Reading Planner、Character Memory 等 service 各自直连模型 SDK。

统一调用路径：

```text
Service
-> ContextSpec
-> Context Fetch Engine
-> LLM Gateway
-> Provider Adapter
-> Structured Output Validator / Repair
-> Harness Gate
```

`LLM Gateway` 职责：

- Provider Adapter：OpenAI、DeepSeek、Claude、Gemini、本地 Ollama、自建 OpenAI-compatible endpoint。
- Prompt Registry：所有 prompt 版本化，进入 provenance 和 cache key。
- Model Routing：按任务选择便宜模型、强模型、长上下文模型或 fallback 模型。
- Structured Output：JSON Schema、输出修复、重试、降级。
- Rate Limit：QPS、并发、token/min、provider 配额。
- Cost Tracking：按书、章节、任务统计输入输出 token 和费用。
- Cache：同一 task、prompt、context、model 和配置不重复请求。
- Privacy Policy：明确哪些正文、上下文和用户数据会发送到外部 API。
- Provenance：记录 provider、model、prompt_version、context_hash、input_hash、output_hash、latency、cost。

阅读器集成层不应直接调用 LLM。阅读器只和 Core Server 通讯，由 Core Server 决定调用本地模型、云端 API 还是自建服务器。这样可以同时解决 API key 安全、移动端限制、成本控制、日志追踪和 provider 切换问题。

LLM cache key 至少包含：

```text
task_type
model_id
provider_id
prompt_version
context_hash
book_model_snapshot_id
generation_config_id
cache_buster
```

API-only LLM 是可行的默认路径，但不能让系统变成 per-segment LLM 调用。Reading Planner、Text Adaptation 和 Book Scan 应按章节、场景块或 segment batch 调用；只有局部异常修复才使用小窗口单点调用。

`LLM Gateway` 和 `Speech Gateway` 是 External Gateway，不是普通 stateless service。Service 可以依赖 Gateway，但 Gateway 不反向依赖 service。这样 Text Adaptation、Reading Planner、Voice Casting 等核心逻辑可以用 mock gateway 独立测试。

## 9. Speech Gateway / TTS Gateway

多后端复杂度通过 API Gateway 隔离。API 和本地部署不是对立关系：

```text
远程 API：OpenAI / 云端 CosyVoice / 自建 GPU 服务器
本地部署：本机启动 CosyVoice / GPT-SoVITS，再通过 localhost API 调用
```

统一请求由 `TTSInputComposer` 生成，adapter 不应重新解释业务语义：

```json
{
  "request_id": "ttsreq_ch001_p023_s002_001",
  "engine": "cosyvoice",
  "endpoint": "http://localhost:50000/v1/audio/speech",
  "segment_id": "ch001_p023_s002",
  "voice_id": "cosy_male_cold_001",
  "text": "你既然来了，",
  "style": {
    "emotion": "restrained",
    "intensity": 0.35,
    "prosody_hint": "normal_pause"
  },
  "enhancements": [],
  "format": "wav"
}
```

`BackendSpeechRequest` 不携带内部 `source_artifacts`。输入 artifact 版本属于 `JobState.input_artifact_versions`、`ProvenanceEntry` 和 `artifact_dependencies`，不应透传给语音后端。

`Speech Gateway` 不做角色到音色的决策。`Voice Casting` 决定稳定 `voice_id`；`Speech Gateway` 只负责根据 `voice_id`、engine、provider 状态、限流和失败策略调用正确后端。

每个后端登记能力：

```json
{
  "engine": "cosyvoice",
  "supports_voice_clone": true,
  "supports_emotion": true,
  "max_chars": 500,
  "cost_type": "local_gpu",
  "quality_tier": "high",
  "commercial_safe": true
}
```

Koodo voice plugin 应作为第一阶段阅读器接入探针，而不是直接等同于完整 Reader Package 播放。Koodo 公开语音插件示例的基本模式是：插件脚本接收当前 TTS 文本，调用本地或局域网 HTTP TTS 服务，写入临时音频文件并返回音频路径；部分插件还可返回 voice list。VoiceNovel 应提供一个薄适配层，让 Koodo 插件调用 Core Server，而不是让插件直连 CosyVoice、GPT-SoVITS、ChatTTS 等后端。

推荐适配路径：

```text
Koodo voice plugin
-> Core Server Koodo-compatible TTS endpoint
-> Speech Gateway
-> provider adapter
-> audio bytes / cached audio file
-> plugin writes local file and returns path to Koodo
```

该路径只承载“当前文本 -> 音频”的能力，适合验证部署、音色选择、延迟和 fallback。它不负责 cleaned HTML、Reader Package、章节级 timing、句子/半句高亮、预缓存状态或离线包；这些仍属于 Reader Package Adapter / thin fork 的责任边界。

第一版优先接：

- CosyVoice Docker：自定义音色、`voice_id`、OpenAI-compatible API。
- Edge-TTS：旁白和低成本兜底。
- Mock TTS：开发和测试用。
- Koodo voice plugin compatibility endpoint：让 Koodo 以现有语音插件方式调用 VoiceNovel Core Server。

ChatTTS、GPT-SoVITS、FishSpeech 放到第二阶段 adapter。
