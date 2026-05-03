# VoiceNovel 设计文档

设计文档按职责边界拆分，避免把架构决策、数据契约、模块设计、技术栈和 MVP 范围混在同一个文件里。阅读时先看产品与架构，再进入数据契约和具体模块，最后看 MVP 收敛。

## 文档地图

| 文档 | 关注点 |
| --- | --- |
| [产品定位与核心原则](00-product-scope.md) | 定义 VoiceNovel 的产品边界、听书优先原则、阅读器接入形态和核心设计原则。 |
| [系统架构与工程基线](01-system-architecture.md) | 描述整体架构、写入流程、MVP 架构收敛原则、技术栈和建议目录结构。 |
| [Project Store 与共享契约](02-project-store-and-contracts.md) | 定义唯一真值源、artifact 版本语义、存储形态和 contracts-first 边界。 |
| [文本处理与朗读计划流水线](03-processing-pipeline.md) | 覆盖导入、文本适配、中文分句、cleaned package、朗读计划、上下文流水线和长上下文策略。 |
| [Book Model、上下文检索与角色记忆](04-book-model-and-memory.md) | 说明小说理解投影、上下文检索服务、角色记忆和跨章节一致性。 |
| [音色体系与模型网关](05-voice-and-gateways.md) | 定义 Voice Registry、音色生命周期、LLM Gateway 和 Speech/TTS Gateway。 |
| [调度、预缓存、并发与 Take Library](06-orchestration-cache-and-takes.md) | 覆盖 Render Queue、预缓存调度、并发执行、断点续传、缓存键和 take 选优。 |
| [Harness、Timing、Packaging 与 Reader](07-harness-timing-packaging-reader.md) | 定义质量控制平面、timing 构建、Reader Package、Web Reader MVP、Koodo 接入分层和 Exception Console。 |
| [成本、预检、溯源、导出与许可策略](08-cost-policy-export.md) | 描述 Cost Planner、Preflight、Provenance、Export Targets 和 License/Model Policy Gate。 |
| [MVP 范围与暂缓项](09-mvp-roadmap.md) | 收敛第一阶段必须包含的闭环能力、实现顺序和明确暂缓范围。 |

## 拆分原则

- 产品原则、架构决策、数据契约、模块设计和落地范围分开维护。
- Project Store / contracts 是跨模块基础，独立成文，避免被实现细节淹没。
- 处理流水线、模型记忆、网关语音、调度缓存、阅读器包分别按变更频率和责任边界拆分。
- MVP 文档只回答第一阶段做什么、不做什么，以及推荐实现顺序。

[返回仓库入口](../../设计草案.md)
