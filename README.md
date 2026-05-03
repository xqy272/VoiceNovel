# VoiceNovel

面向中文小说的 AI 原生多人有声书流水线。导入 TXT/EPUB → 文本分句 → 音色分配 → 语音合成 → 时序生成 → 打包导出，配合带句子级高亮的参考 Web 阅读器端到端交付。

```text
TXT/EPUB -> Project Store -> Text Adaptation -> Segmentation
-> Reading Plan -> Voice Casting -> TTS Gateway
-> Chapter audio + timing.json -> Reader Package -> Web Reader
```

## 当前状态 —— MVP 候选

本地 Demo 已就绪，冒烟验证通过。所有关键路径均有自动化测试覆盖。

### 已支持的 MVP 能力

- **导入**：TXT/EPUB 导入 SQLite Project Store（书籍、章节、段落）
- **冷启动**：4 阶段流水线（分句 → 扫描 → 缓冲包 → 后台烘焙作业）
- **完整烘焙**：基于内容缓存的端到端章节渲染
- **Artifact Store**：active/superseded/invalidated 生命周期，依赖追踪与幂等提交
- **Harness Gate**：通过 StageResult 原子事务实现的统一写入控制面
- **调度器**：基于租约的作业队列，P0/P2/P3 优先级，重建与预取
- **Station 控制台**：Web UI 标签页 —— Chapters（作业/异常）、Exceptions、Voices、Adaptation、Export（Xp）、Preflight（Pf）
- **音色分配**：自动分配、锁定/解锁、重新分配、失效级联
- **文本适配**：逐段操作，通过 Harness 实现 replay/diff/rollback
- **导出**：DAW、Audiobookshelf、M4B —— 临时目录原子提交、ZIP 下载、路径范围安全
- **预检**：章节操作检查，包含阻断性错误、警告和成本估算
- **Web Reader**：Svelte 5 参考阅读器，支持章节列表、高亮、音频播放、预取
- **异常队列**：按章节追踪异常，open/resolved 生命周期

### 启动方式

推荐启动器（Windows PowerShell）：

```powershell
./start.ps1
```

此脚本会检查 Python/Node/uv 环境、同步依赖、释放 5000 端口、启动前后端并等待后端就绪。

分步启动：

```powershell
# 后端
uv sync --extra dev
uv run python -m vn_server

# 前端（另开终端）
cd web_reader
npm install
npm run dev
```

浏览器打开 http://localhost:3000。Web Reader 将 /api 代理到 http://localhost:5000。

### 演示流程

1. 打开 http://localhost:3000
2. 点击 **Import Sample** 导入 `tests/golden_books/mountain_inn.txt`
3. 点击章节 —— 阅读器会自动烘焙并加载文本 + 高亮音频
4. 打开 **Station** 面板（底部栏）查看作业、异常、音色和导出
5. 在 Station **Xp** 标签页导出 DAW 格式并下载 ZIP

### API 冒烟测试

```powershell
# 导入
curl -X POST http://localhost:5000/api/projects -H "Content-Type: application/json" -d "{\"source_path\":\"tests/golden_books/mountain_inn.txt\",\"book_id\":\"demo\"}"

# 冷启动
curl -X POST http://localhost:5000/api/projects/demo/chapters/ch001/cold-start

# 完整烘焙
curl -X POST http://localhost:5000/api/bake -H "Content-Type: application/json" -d "{\"book_id\":\"demo\",\"chapter_id\":\"ch001\"}"

# 预检
curl -X POST http://localhost:5000/api/projects/demo/chapters/ch001/preflight -H "Content-Type: application/json" -d "{\"operation\":\"export\",\"format\":\"daw\"}"

# 导出
curl -X POST "http://localhost:5000/api/projects/demo/chapters/ch001/exports?format=daw"

# 下载（使用导出响应中的 artifact_version_id）
curl -o demo.zip "http://localhost:5000/api/projects/demo/exports/{artifact_version_id}/download"
```

### 验证命令

```powershell
# 完整测试套件（约 400 条）
uv run --extra dev pytest tests -q

# 定向冒烟测试
uv run --extra dev pytest tests/test_mvp_smoke.py tests/test_preflight.py -q

# Lint
uv run --extra dev ruff check vn_core vn_server integrations tests

# 前端构建
cd web_reader && npm run build
```

### 工程目录

```text
vn_core/                    核心流水线与服务
vn_core/contracts/          Pydantic 数据契约
vn_core/store/              SQLite Project Store
vn_core/pipeline/           端到端烘焙/冷启动
vn_core/render/             Speech Gateway 与 TTS 适配器
vn_core/timing/             时序构建与章节 WAV 拼装
vn_core/packaging/          Reader Package 构建器
vn_core/harness/            校验与提交门禁
vn_core/orchestration/      基于租约的作业队列
vn_core/export/             DAW / Audiobookshelf / M4B 导出器
vn_core/cost_planner/       Token/音频成本估算
vn_server/api/              FastAPI REST/WebSocket API
web_reader/                 Svelte 参考阅读器
tests/                      约 400 条测试（单元、集成、冒烟）
tests/golden_books/         黄金源文本测试数据
docs/                       设计文档与发布清单
```

### 已知限制

- **TTS**：默认后端为 Mock（静默 WAV）。如需真实语音，请配置 Edge TTS 或 CosyVoice。
- **LLM**：默认后端为 Mock。如需真实适配/扫描，请配置兼容 OpenAI 的 API Key。
- **M4B**：仅生成元数据。FFmpeg 混流需要外部安装 `ffmpeg`。
- **音频格式**：章节音频默认为 WAV。MP3 拼装逻辑已存在但非默认路径。
- **扩展性**：单 Worker 调度器，不支持水平扩展。
- **认证**：无认证机制。设计定位为本地单用户使用。

### Post-MVP 路线

- 真实 TTS 适配器（Edge TTS / CosyVoice）+ 音色质量校验
- 真实 LLM 后端用于文本适配和音色分配
- WebSocket 进度事件（导入/烘焙/渲染/打包）
- ASR 反向校验渲染音频
- LLM Prompt 注册表
- 多章节黄金回归测试数据
- MP3 章节打包作为默认路径
- 生产部署指南（Docker、认证、HTTPS）
