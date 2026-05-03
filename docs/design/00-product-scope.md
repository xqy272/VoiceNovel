# 产品定位与核心原则

定义 VoiceNovel 的产品边界、听书优先原则、阅读器接入形态和核心设计原则。

[返回设计索引](README.md)

## 项目定位

做一个“阅读器可接入的 AI 多角色有声书系统”。

核心不是单纯 EPUB 转 MP3，而是：

```text
电子书
-> Text Adaptation 文本适配 + 中文句子/半句切分
-> LLM 朗读计划 + 小说记忆积累 + 跨章节角色记忆
-> 音色匹配 + 自定义音色生命周期
-> LLM Gateway + Speech Gateway 统一 API 调度
-> TTS 预缓存渲染
-> Harness Engineering 全链路质检 + 缓存/重试/降级
-> 阅读器句子/半句同步高亮播放
```

系统默认不主动烘焙整本书，而是采用“假实时预缓存”策略：用户打开 AI 听书时，先等待一段短时间，系统预渲染当前章节及后续若干章节；播放过程中后台持续渲染更后面的章节。用户也可以主动选择烘焙当前章节、选定章节或全书。

本项目当前阶段以 AI 听书体验为主线，优先追求稳定、连续、低人工参与的阅读朗听体验。角色音色、朗读情绪、停顿、语气、可选音效等能力都可以作为听书增强逐步引入；只要它们不显著增加人工成本、不破坏预缓存实时性，并且能够关闭、降级、缓存和复现，就不需要被排除。

产品形态上，本项目不做完整阅读器，也不做单纯有声书生成器。推荐形态是：

```text
VoiceNovel Core Server
  LLM Gateway / Speech Gateway / Orchestrator / Project Store / Book Model

VoiceNovel Station
  桌面/开发控制台：验证管线、配置模型、管理项目、检查 Reader Package、处理异常和成本预估

Reader Adapter Protocol
  从阅读器获取 book / chapter / content / position / capabilities
  向阅读器返回 cleaned content / segments / audio / timing / status

Reference Web Reader
  用于验证 Reader Package、timing、高亮、播放和预缓存协议

Koodo Integration
  Koodo Voice Plugin：优先作为低风险接入探针，连接 Core Server / Speech Gateway
  Koodo Reader Package Adapter：若插件能力足够，则消费 Reader Package、timing 和预缓存状态
  Koodo thin fork：当插件无法控制 cleaned content、章节音频、timing、高亮或离线缓存时再进入

Concrete Reader Integrations
  Readium Adapter / Legado Adapter / Electron Reader / mobile reader
```

阅读器相关能力必须被抽象成 `Reader Adapter Protocol`，而不是把 AI pipeline 写进某个阅读器 fork。插件和魔改的区别在于修改边界：插件依赖宿主扩展点，维护成本低但能力受限；薄 fork 能力更强但需要长期跟上游同步。Koodo 已有插件系统，现有公开插件主要覆盖翻译、词典和语音 provider；语音插件适合把 Koodo 当前朗读文本转发给 VoiceNovel Core / Speech Gateway 合成音频，但不应默认它已经能承载完整 Reader Package。无论采用哪种形态，阅读器侧都只放适配层：入口、当前书/章节/位置提取、cleaned content 渲染或 anchor mapping、音频播放、高亮同步、预缓存状态展示和 Core Server 通讯。

参考项目：

- [Alexandria Audiobook](https://github.com/Finrandojin/alexandria-audiobook)：LLM 朗读计划/角色标注、多角色有声书工作流、Voice Design、Web 编辑器、MP3/M4B/Audacity 导出。
- [tts-audiobook-tool](https://github.com/zeropointnine/tts-audiobook-tool)：ASR 反校验、失败重试、最佳 take、同步播放、自动化质量控制。
- [TTS-Story](https://github.com/Xerophayze/TTS-Story)：多引擎、多说话人、speaker memory、任务队列、音色库和 voice prompt 管理。
- [Abogen](https://github.com/denizsafak/abogen)：文档导入、章节处理、同步文本、队列、WebUI、Audiobookshelf 生态输出。
- [CosyVoice Docker](https://github.com/neosun100/cosyvoice-docker)：自定义音色与 `voice_id` 服务化，适合作为第一阶段 TTS API 后端。
- [Koodo Reader](https://github.com/koodo-reader/koodo-reader)：阅读器底座候选，但需注意 AGPL 许可。
- [Koodo 插件市场](https://koodoreader.com/zh/plugin)：已有翻译、词典、语音插件；语音插件可作为 VoiceNovel Core Server 接入 Koodo 的第一阶段验证路径。

## 核心设计原则

1. **显示 AI 校对后的文本**
   - 阅读器显示文本和 TTS 主输入保持一致。
   - 不做“显示原文、朗读纠错文”的割裂体验。
   - 原文只用于回溯、diff、异常排查。

2. **只做句子/半句高亮**
   - 不做逐字/逐词高亮。
   - 每个句子或半句生成稳定 `segment_id`。
   - 阅读器播放时通过 `segment_id` 高亮对应 DOM span。

3. **不维护两套正文**
   - 主字段只保留一个 `text`。
   - `text` 同时用于阅读器显示和默认 TTS。
   - 只有 TTS 控制符、数字读法、情绪 prompt 时才使用 `tts_override`。

4. **API-first 管理 LLM 与语音后端**
   - VoiceNovel 核心不在业务 service 中直连任何模型供应商。
   - 所有 LLM 调用统一走 `LLM Gateway`，所有语音生成/克隆统一走 `Speech Gateway`。
   - 外部商业 API、本地部署模型、自建服务器模型都被抽象成 provider adapter。
   - 阅读器插件、fork adapter、移动端和 Web Reader 不直接持有模型 API key，不直接访问 OpenAI、DeepSeek、CosyVoice、ElevenLabs 等供应商。
   - CosyVoice、GPT-SoVITS、ChatTTS、Edge-TTS、OpenAI TTS、云端 CosyVoice、Fish Audio 等全部通过 adapter 接入。

5. **默认预缓存，不默认全书烘焙**
   - 用户开始听书时只阻塞等待必要的前置章节。
   - 后台按播放位置动态推进后续章节渲染。
   - 主动全书烘焙是高级操作，不是默认路径。

6. **Harness Engineering 是横向控制层**
   - harness 不只是 LLM 输出校验，而是覆盖导入、分句、朗读计划、角色、音色、TTS、音频、timing、阅读器和预缓存调度的工程控制层。
   - 目标不是把问题都交给人工，而是自动发现、自动分类、自动重试、自动降级，只把少量无法自动处理的问题暴露给用户。
   - 每个阶段都必须产出结构化状态、质量分数、异常类型和可复现 provenance。

7. **听书优先，增强渐进**
   - 默认体验优先保证可听、稳定、连续和低人工参与。
   - 允许渐进引入增强：角色音色、朗读情绪、停顿优化、语气控制、少量可选音效。
   - 增强能力不应依赖改写原文；如果需要显著改变文本或制作复杂演出，应进入后续高级模式，而不是 MVP 主路径。
   - 增强失败时必须可降级为纯 TTS，不影响阅读器播放。
   - 增强参数必须进入 `cache_key`、Cost Planner 和 Provenance。

```json
{
  "segment_id": "ch001_p023_s002",
  "segmenter_version": "zh_clause_v1",
  "source_href": "Text/chapter001.xhtml",
  "source_order": 23,
  "source_text": "他竟然在也没有回来。",
  "text": "他竟然再也没有回来。",
  "tts_override": null,
  "speaker_id": "char_narrator",
  "voice_id": "edge_zh_narrator_001",
  "status": "ready"
}
```
