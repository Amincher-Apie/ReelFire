# 题目 1：基于 YOLO+Agent 的智能数字媒体内容理解系统——团队开发指导书

> 适用范围：ReelFire 五人小组、4 天并行开发周期、Flask + OpenCV + Ultralytics YOLO + Agent + 知识库 + FFmpeg。
>
> 本指导书用于统一开发环境、模块边界、接口格式、协作流程和验收标准。所有成员开始编码前应完整阅读。

---

## 1. 项目目标

系统需要完成以下最小业务闭环：

```text
上传游戏视频
  -> 创建任务并立即返回 job_id
  -> 后台采样、检测和评分
  -> 生成关键帧与候选片段
  -> Agent 读取真实视觉报告并检索知识库
  -> 生成摘要、标签、审核建议和证据引用
  -> 人工保留、忽略、排序和调整边界
  -> FFmpeg 输出粗剪视频
  -> 保存报告并可从历史任务重新打开
```

核心评分公式统一为：

```text
highlight_score =
    object_score * 0.45
  + scene_change_score * 0.35
  + motion_score * 0.20
```

现有仓库已经完成视频上传、异步 CV、人工审核和粗剪基线。四天开发的首要目标是在不破坏该闭环的前提下，补齐课程要求的独立 Agent、知识库、至少三个工具节点、调用日志、自定义模型、统计图和报告交付。

---

## 2. 统一开发环境

### 2.1 获取项目并配置环境

每名成员将 Git 仓库克隆到自己的任意工作位置，然后进入 `ReelFire` 项目根目录：

```powershell
git clone https://github.com/Amincher-Apie/ReelFire.git
cd ReelFire
python setup_environment.py
```

脚本会复用当前已激活的非 `base` Conda 环境；没有可复用环境时，自动创建 Python 3.11 的 `ReelFire` 环境。它还会根据本机 NVIDIA GPU、Apple MPS 或 CPU 自动选择 PyTorch 构建，并检查 FFmpeg。

组长机器上已经验证的参考环境：

| 项目 | 版本或状态 |
|---|---|
| Python | 3.11.15 |
| PyTorch | 2.11.0 + CUDA 12.8 |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU，可用 |
| Flask | 3.1.3 |
| OpenCV | 4.13.0 |
| FFmpeg / ffprobe | 已在系统 `PATH` 中 |

任何成员不得只在自己的环境中临时安装未记录的依赖。确实需要新增包时，必须同步修改 `requirements.txt` 或 `setup_environment.py` 并通知全组。

### 2.2 环境自检

```powershell
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
python -c "import flask, cv2; from ultralytics import YOLO; print('Python dependencies OK')"
ffmpeg -version
ffprobe -version
```

预期结果：

- NVIDIA 机器的 `torch.cuda.is_available()` 返回 `True`，无 NVIDIA GPU 的机器允许使用 MPS 或 CPU；
- Ultralytics、Flask 和 OpenCV 可以导入；
- `ffmpeg` 与 `ffprobe` 均可执行。

### 2.3 模型约定

- Day 1～Day 2 联调使用 `models/yolo11n.pt` 作为稳定回退基线；
- Day 1 建立自定义类别、标注和数据划分，Day 2 启动训练，Day 3 接入最佳权重并保留模型版本字段；
- 最终验收同时保留“官方基线结果”和“自定义模型/多阈值评估结果”，不能只提交训练日志；
- 权重由 `setup_environment.py` 从 Ultralytics 官方 Release 自动下载并校验，不提交到 Git；
- 模型路径必须来自配置，不允许散落在多个源文件中；
- 模型缺失时，任务进入 `failed`，并把可读错误写入 `job.json`；
- 自定义大型权重不反复提交；由组长统一确认交付位置并提供 SHA-256 或下载说明。

---

## 3. 固定角色分工

### 3.1 ReelFire 五人分工

| 固定角色 | 主要负责模块 | 四天核心产出 |
|---|---|---|
| 产品与项目负责人、集成测试 | 需求、验收、进度、接口变更、集成和演示 | PRD、看板、验收、回归、发布包 |
| CV/数据工程师 | 采样、YOLO、训练、评估、跟踪、评分和 FFmpeg 协作 | 自定义权重、视觉报告、对比指标、轨迹 |
| 后端工程师 | Flask API、任务状态、认证、数据库、统计和导出 | API、数据层、日志、审核包/报告 |
| 前端工程师 | 上传、轮询、Agent 结果、三态审核、图表和报告 | 完整页面、统计图、浏览器证据 |
| Agent/工作流工程师 | Agent、知识库、Prompt、三工具节点和调用日志 | Agent 工作流、知识库、结构化建议、失败测试 |

### 3.2 视频模块协作

本组不单设视频或专职测试角色。CV/数据工程师负责视频片段和 FFmpeg 核心实现，后端工程师负责封装接口，前端工程师负责交互，产品与项目负责人组织片段边界、有/无音频和输出规格验收。每名成员为自己的模块提供测试。

### 3.3 Agent 协作边界

- Agent/工作流工程师只消费真实 `analysis_report.json` 和知识库内容，不直接修改 CV 原始结果；
- CV/数据工程师保证类别、置信度、框、时间戳、轨迹和模型版本字段稳定；
- 后端工程师负责 Agent 调用入口、状态、日志持久化和失败隔离；
- 前端工程师展示摘要、标签、建议、三态与引用，并保留人工最终决定权；
- 现有 `segment_tags`、`ai_cover_prompt` 是规则回退，不等同于课程要求的完整 Agent。

### 3.4 公共责任

每名成员都必须：

1. 有可检查的代码、文档、测试或演示产出；
2. 在提交信息中说明完成内容；
3. 不擅自修改其他成员负责模块的接口；
4. 接口确需调整时，先更新 `docs/API.md`，再通知前后端成员；
5. 每天参加 09:00 站会、12:00 契约检查、16:30 集成检查和 18:00 日终门禁；
6. 至少参与一次跨模块联调和一次最终验收检查。

---

## 4. 项目目录与文件归属

建议使用以下结构：

```text
ReelFire/
├─ app.py                         # 程序入口，只做初始化和启动
├─ config.py                      # 路径、模型、阈值、输出规格
├─ requirements.txt
├─ models/
│  └─ yolo11n.pt                  # 初始化脚本下载的联调基线模型
├─ services/
│  ├─ job_service.py              # 任务创建、查询、状态变更
│  ├─ analysis_service.py         # 分析流程编排
│  ├─ agent_service.py            # 计划新增：Agent 三工具编排
│  └─ ffmpeg_service.py           # 探测、剪辑、转码和合成
├─ knowledge_base/                # 计划新增：媒体分类/审核规范
├─ cv_engine/
│  ├─ video_processor.py          # OpenCV 视频采样与画面指标
│  ├─ yolo_detector.py            # YOLO 推理封装
│  └─ highlight_scorer.py         # 三项指标、综合评分和片段选择
├─ routes/
│  ├─ health.py
│  └─ jobs.py
├─ templates/
│  └─ index.html
├─ static/
│  ├─ app.js
│  └─ style.css
├─ outputs/
│  └─ <job_id>/
│     ├─ input/
│     ├─ keyframes/
│     ├─ result/
│     ├─ job.json
│     └─ analysis_report.json
├─ tests/
│  ├─ test_api.py
│  ├─ test_scoring.py
│  └─ test_clip_boundaries.py
└─ docs/
   ├─ PRD.md
   ├─ SYSTEM_DESIGN.md
   ├─ API.md
   ├─ TEST_REPORT.md
   └─ BUG_RECORD.md
```

文件归属原则：

- `routes/`、`services/job_service.py`：后端工程师主责；
- `cv_engine/`、`services/analysis_service.py` 的视觉流程：CV/数据工程师主责；
- `services/agent_service.py`、`knowledge_base/`、Agent Prompt：Agent/工作流工程师主责；
- `services/ffmpeg_service.py`：CV/数据工程师主责，项目负责人组织边界和音轨验证；
- `templates/`、`static/`：前端工程师主责；
- `tests/` 按模块由对应角色主责，集成与浏览器验收由项目负责人组织；
- 接口和 JSON 契约属于全组公共约定，不能单方改变。

---

## 5. 系统架构和处理流程

```text
浏览器工作台
   |
   | HTTP 上传、轮询、审核、粗剪
   v
Flask API
   |
   +--> JobService：job_id、状态、JSON 持久化
   |
   +--> 后台工作线程
           |
           +--> OpenCV 采样
           +--> YOLO 检测
           +--> 画面变化与运动强度
           +--> 综合评分与时间去重
           +--> 保存关键帧和分析报告
   |
   +--> AgentService
           +--> 解析真实视觉报告
           +--> 检索媒体分类/审核知识库
           +--> 生成摘要、标签、建议和三态
           +--> 规则校验并保存工具调用日志
   |
   +--> FFmpegService：探测音轨、裁剪、缩放、合并
           |
           v
       输出粗剪视频
```

现有 CV 后台任务继续使用 Python `ThreadPoolExecutor`，避免四天课程项目引入 Redis/Celery。现有 `job.json` 和 `analysis_report.json` 保留为可移植分析证据；另用 SQLite 保存用户、项目、素材元数据、三态审核和 Agent 调用日志，以满足统一工程要求。

任务状态只允许按以下路径变化：

```text
created -> queued -> running -> completed
                              -> failed
```

上传接口不能等待完整推理结束。它应保存输入、建立 `job.json`、提交后台任务，然后立即返回 `job_id`。

---

## 6. 固定数据契约

### 6.1 `job.json`

```json
{
  "job_id": "20260718_101530_a1b2c3d4",
  "project_name": "游戏录屏精彩片段提取",
  "asset_name": "gameplay.mp4",
  "status": "completed",
  "created_at": "2026-07-18T10:15:30+08:00",
  "started_at": "2026-07-18T10:15:31+08:00",
  "completed_at": "2026-07-18T10:16:08+08:00",
  "settings": {
    "sample_interval": 0.5,
    "target_duration": 30.0,
    "output_aspect": "16:9"
  },
  "result_file": "analysis_report.json",
  "error": null
}
```

要求：

- 时间统一使用带时区的 ISO 8601 字符串；
- 失败任务也必须保存该文件；
- 写 JSON 时先写临时文件，再用原子替换更新正式文件，避免轮询读到半截内容；
- `error` 面向用户书写，详细堆栈只写日志。

### 6.2 `analysis_report.json`

```json
{
  "job_id": "20260718_101530_a1b2c3d4",
  "video": {
    "duration": 120.5,
    "width": 1920,
    "height": 1080,
    "fps": 30.0,
    "has_audio": true
  },
  "score_weights": {
    "object": 0.45,
    "scene_change": 0.35,
    "motion": 0.20
  },
  "keyframes": [
    {
      "id": "kf_001",
      "timestamp": 42.5,
      "image": "keyframes/kf_001.jpg",
      "object_count": 4,
      "object_score": 0.8,
      "scene_change_score": 0.7,
      "motion_score": 0.6,
      "highlight_score": 0.725,
      "decision": "keep",
      "label": "battle",
      "note": "多人战斗场景",
      "order": 1
    }
  ],
  "segments": [
    {
      "id": "seg_001",
      "start": 32.5,
      "end": 52.5,
      "source_keyframes": ["kf_001"],
      "order": 1
    }
  ],
  "output": {
    "video": "result/highlight_16x9.mp4",
    "contact_sheet": "result/contact_sheet.jpg"
  }
}
```

前端、后端、算法和测试必须共同遵守字段命名。新增字段可以向后兼容，删除或改名必须经过全组确认。

---

## 7. API 联调契约

所有成功响应必须包含：

```json
{ "ok": true }
```

所有失败响应必须包含：

```json
{ "ok": false, "error": "可直接展示给用户的错误信息" }
```

### 7.1 公共接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/health` | 服务、模型、FFmpeg 和 GPU 状态 |
| `POST` | `/api/jobs` | 上传视频、创建任务、立即返回 `job_id` |
| `GET` | `/api/jobs` | 获取历史任务列表 |
| `GET` | `/api/jobs/<job_id>` | 获取任务状态和结果摘要 |
| `DELETE` | `/api/jobs/<job_id>` | 删除非运行状态的合法任务 |

### 7.2 题目 1 内容理解接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/jobs/<job_id>/analyze` | 将任务提交到后台分析 |
| `PATCH` | `/api/jobs/<job_id>/review` | 保存关键帧审核、排序、标签、备注和边界 |
| `POST` | `/api/jobs/<job_id>/rough-cut` | 按审核后的片段生成粗剪视频 |
| `GET` | `/api/jobs/<job_id>/report` | 获取完整分析报告 |

### 7.3 创建任务响应示例

建议创建后直接进入 `queued`，避免前端再发一次重复分析请求：

```json
{
  "ok": true,
  "job_id": "20260718_101530_a1b2c3d4",
  "status": "queued"
}
```

### 7.4 审核更新请求示例

```json
{
  "keyframes": [
    {
      "id": "kf_001",
      "decision": "keep",
      "label": "battle",
      "note": "保留为开场高潮",
      "order": 1
    }
  ],
  "segments": [
    {
      "id": "seg_001",
      "start": 32.5,
      "end": 52.5,
      "order": 1
    }
  ]
}
```

后端必须重新验证：

```text
0 <= start < end <= video_duration
```

不能只相信浏览器端校验。

---

## 8. 算法实现约定

### 8.1 视频采样

- 默认按时间采样，每 `0.5s` 一帧，不依赖固定帧号间隔；
- 必须处理 FPS 为 0、无法解码、空视频和时长异常；
- 保存原始时间戳，所有片段边界均以秒为单位；
- 长视频可以限制最大分析帧数，并在报告中记录真实参数。

### 8.2 三项分数

1. `object_score`：目标数量或加权目标数量归一化到 `[0, 1]`；
2. `scene_change_score`：相邻采样帧的灰度直方图差异或像素差异归一化；
3. `motion_score`：光流强度或连续帧差异归一化；
4. `highlight_score`：按照固定权重求和，结果限制到 `[0, 1]`。

归一化方法和阈值必须写入 `docs/SYSTEM_DESIGN.md`，不能只在代码中体现。

### 8.3 关键帧去重

推荐按分数从高到低选择，并设置最小时间间隔，例如 `5s`。当候选帧与已选帧距离过近时，只保留分数更高者，避免同一镜头反复入选。

### 8.4 片段边界

给定中心时间 `center` 和目标时长 `duration`：

1. 初始边界为中心点左右各一半；
2. 开头越界时整体向后平移；
3. 结尾越界时整体向前平移；
4. 目标时长大于原视频时，使用完整视频；
5. 最后强制验证 `0 <= start < end <= video_duration`。

必须测试：靠近开头、靠近结尾、目标时长过长、关键帧不足和多个高分帧来自同一镜头。

### 8.5 FFmpeg 输出规格

最低支持：

- 横屏：`1920x1080`，比例 `16:9`；
- 竖屏：`1080x1920`，比例 `9:16`。

建议使用“等比缩放 + 补边”保证画面不被意外裁掉。源视频无音轨时，不得因为映射不存在的音频流而失败；可使用可选音轨映射或先通过 `ffprobe` 检测。

---

## 9. Git 协作规范

### 9.1 分支建议

```text
main
├─ feature/cv-analysis       # CV 算法工程师
├─ feature/backend-api       # 后端工程师
├─ feature/frontend          # 前端工程师
├─ test/qa-delivery          # 项目负责人组织、全员参与
└─ docs/project-management   # 组长、产品负责人
```

如果没有远程仓库，也应在本地使用分支和清晰提交记录。禁止在共享主分支上同时直接修改同一文件。

### 9.2 提交信息

推荐格式：

```text
feat(api): add asynchronous job creation
feat(cv): implement normalized highlight scoring
fix(video): keep target duration near video end
test(api): cover empty upload and failed job
docs(prd): define acceptance criteria
```

常用类型：`feat`、`fix`、`test`、`docs`、`refactor`、`chore`。

### 9.3 合并前检查

每次合并前至少执行与本模块相关的检查：

```powershell
python -m py_compile app.py
python -m unittest discover -s tests -v
node --check static/app.js
```

合并者还要确认：

- 没有提交 API Key、密码或个人隐私；
- 没有提交 Conda 环境、缓存、临时视频和无关大文件；
- 没有覆盖其他成员尚未合并的功能；
- 接口修改已经同步到 `docs/API.md`。

---

## 10. 四天执行计划与进度检查点

### 10.1 每日固定节奏

| 时间 | 检查点 | 必须提交的证据 |
|---|---|---|
| 09:00 | 站会与领取任务 | 当日任务、依赖、分支、预计完成时间 |
| 12:00 | 契约检查 | 可运行中间产物、接口/Schema 变化、测试结果 |
| 16:30 | 集成检查 | 当日功能演示、Bug、阻塞和回退方案 |
| 18:00 | 日终门禁 | 提交哈希、日报、完成比例、次日计划 |

### 10.2 Day 1：基线、范围与契约

| 成员/角色 | 工作内容 | 日终门禁 |
|---|---|---|
| 产品与项目负责人 | 课程差距矩阵、PRD、看板、验收与分支冻结；复跑基线测试 | 37 项基线测试不回退；18 项要求均有负责人 |
| CV/数据工程师 | 复核 CV 主链；数据、类别、标注、训练和基线模型方案 | 数据样例可用；官方模型真实推理可复现 |
| 后端工程师 | 复核 API/状态/JSON；设计认证、数据库、审核和 Agent 日志 | API 与数据 Schema 通过评审 |
| 前端工程师 | 复核现有页面；完成登录、Agent、三态、图表和报告原型 | 页面字段与 API 一一对应 |
| Agent/工作流工程师 | 定义规则基线；建立知识库；设计 Agent 状态、Prompt 和输出 | 知识库可检索；结构化输出 Schema 冻结 |

### 10.3 Day 2：模块纵向切片

| 成员/角色 | 工作内容 | 日终门禁 |
|---|---|---|
| 产品与项目负责人 | 组织契约评审、风险登记和第一轮跨模块验证 | 各角色至少一项可运行产出 |
| CV/数据工程师 | 自定义 YOLO 训练、阈值/模型对比、轨迹与统计输出 | 候选权重和评估结果可检查 |
| 后端工程师 | 注册登录、SQLite、三态审核、素材元数据和调用日志接口 | 新接口有正常和异常测试 |
| 前端工程师 | 认证/素材页、Agent Mock、图表骨架和状态页 | Mock 严格符合冻结 Schema |
| Agent/工作流工程师 | 实现视觉解析、知识库检索、建议生成/校验至少三工具 | 模拟报告可返回合法结果并保存日志 |

### 10.4 Day 3：真实数据集成

| 成员/角色 | 工作内容 | 日终门禁 |
|---|---|---|
| 产品与项目负责人 | 管理集成分支，执行真实链路，跟踪和分派 Bug | 主链路至少成功一次，阻塞有时限 |
| CV/数据工程师 | 接入最佳权重、轨迹、模型版本和 Agent 所需视觉摘要 | 官方/自定义模型可切换，报告符合 Schema |
| 后端工程师 | 串联 CV/Agent，完成统计、审核包和 HTML/PDF 接口 | 刷新/重启可恢复，Agent 失败被隔离 |
| 前端工程师 | 接入真实 CV/Agent/统计，完成三态、轨迹、图表和下载 | 页面数值与 JSON 一致，状态可恢复 |
| Agent/工作流工程师 | 接入真实报告，完成引用、三态建议、日志查询与防幻觉约束 | 不虚构事件；调用链可按 job_id 追踪 |

### 10.5 Day 4：冻结、回归与交付

| 成员/角色 | 工作内容 | 日终门禁 |
|---|---|---|
| 产品与项目负责人 | 全量回归、浏览器验收、截图、录屏、PPT、Git 证据和发布 | 硬性项逐项签署；交付包可复现 |
| CV/数据工程师 | 成功/失败/低置信度复测，模型卡、权重和评估材料 | 结果与限制可追溯 |
| 后端工程师 | 安全、并发、重复提交、重启回归和部署文档 | 后端测试全绿，无敏感信息泄漏 |
| 前端工程师 | 浏览器、响应式、可访问性回归和演示截图 | 无控制台错误，完整流程可演示 |
| Agent/工作流工程师 | Agent 正常/异常/无命中/超时测试和工作流材料 | 三工具、知识库、日志和失败案例齐全 |

如果 Day 2 联调时算法或 Agent 尚未完成，使用冻结 Schema 的模拟 `analysis_report.json` 或 Agent 响应继续开发；Day 3 必须替换为真实输出，并保留模拟与真实数据的清晰标记。

---

## 11. 联调顺序

严格按以下顺序联调，避免所有问题同时出现：

1. `/api/health` 能返回模型、GPU 和 FFmpeg 状态；
2. 上传一个小视频并获得 `job_id`；
3. 任务状态能从 `queued` 变为 `running`；
4. 用模拟报告验证前端轮询和结果页面；
5. 接入真实 OpenCV 采样；
6. 接入 YOLO 检测和三项评分；
7. 保存关键帧和真实报告；
8. 验证人工审核写回；
9. 接入 FFmpeg 粗剪；
10. 验证历史任务重新打开；
11. 最后处理删除、格式错误、空文件和模型缺失。

联调出现问题时，先定位属于“请求格式、任务状态、报告字段、算法结果、文件路径、浏览器展示”中的哪一层，再由对应负责人处理。

---

## 12. 测试最低要求

### 12.1 正常测试至少 5 条

1. 普通横屏 MP4 上传、分析和输出；
2. 有音频视频的粗剪与音频保留；
3. 无音频视频的正常粗剪；
4. 最高分关键帧靠近开头或结尾；
5. 历史任务重新打开、审核并再次导出。

### 12.2 异常测试至少 5 条

1. 不支持的文件扩展名；
2. 0 字节空文件；
3. 文件扩展名合法但内容损坏；
4. 模型文件不存在；
5. 非法片段边界或删除运行中的任务。

### 12.3 必须记录的真实 Bug

至少记录 2 个开发中真实出现的问题，包含：现象、复现步骤、原因、修复方案和回归结果。禁止事后虚构只有一句“已修复”的记录。

---

## 13. 完成定义（Definition of Done）

只有同时满足以下条件，功能才算完成：

- 正常路径可以操作；
- 关键异常有可读提示；
- 数据写入约定的 JSON 文件；
- 页面刷新或重启服务后仍能重新读取；
- 有至少一个自动化测试或明确的手工测试记录；
- 相关文档已同步；
- 代码已经合并，并由另一名成员验证。

项目最终必须满足：

- [ ] 按 README 命令可以启动；
- [ ] 上传后立即获得任务编号；
- [ ] 任务状态真实变化；
- [ ] 至少一次真实 YOLO 推理；
- [ ] 三项评分及综合评分可解释；
- [ ] 关键帧经过时间去重；
- [ ] 自定义 YOLO、模型/阈值对比和运动轨迹有可复现证据；
- [ ] 至少 30 条素材元数据可查询或导出；
- [ ] Agent 使用真实视觉结果、知识库和至少三个工具节点；
- [ ] Agent 摘要、标签、建议、三态、引用和调用日志可追踪；
- [ ] 可以人工保留、忽略、排序、加标签和备注；
- [ ] 通过、待复核、不通过三态可保存并刷新恢复；
- [ ] 可以调整片段开始和结束时间；
- [ ] FFmpeg 能输出 16:9 和 9:16 视频；
- [ ] 有音频和无音频视频均测试通过；
- [ ] 有联系表、分析报告和输出视频；
- [ ] 类别、置信度、关键帧时间、审核状态统计图可核对；
- [ ] 审核包或 HTML/PDF 报告可下载；
- [ ] 历史任务可以重新打开；
- [ ] 5 条正常、5 条异常测试已记录；
- [ ] 2 个真实 Bug 已记录并回归；
- [ ] 文档、截图、分工表和演示稿完整。

---

## 14. 演示建议（8 分钟）

| 时间 | 演示内容 |
|---|---|
| 0:00–0:45 | 项目背景、用户痛点、成员分工 |
| 0:45–1:30 | 架构、四天分工和算法公式 |
| 1:30–2:15 | 登录、上传视频、任务编号和状态轮询 |
| 2:15–3:15 | YOLO、自定义模型、三项指标和轨迹 |
| 3:15–4:30 | Agent 三工具、知识库、摘要/标签/建议和调用日志 |
| 4:30–5:30 | 三态审核、统计图、人工修正和边界调整 |
| 5:30–6:15 | 两种粗剪规格与 HTML/PDF 报告 |
| 6:15–7:15 | 历史重开、异常/低置信度和 Bug 修复 |
| 7:15–8:00 | 测试、Git/日报证据、限制和小组总结 |

现场演示前准备一个较短且已经验证的视频，同时保留一份已完成的历史任务，防止临时推理或编码耗时影响展示。

---

## 15. 开工前 10 分钟检查

组长逐项确认：

- [ ] 全员已在各自克隆目录运行 `setup_environment.py`；
- [ ] 全员业务依赖版本一致，PyTorch 后端已按各自机器正确适配；
- [ ] GPU、FFmpeg 和 ffprobe 自检通过；
- [x] 官方 `yolo11n.pt` 基线可自动下载和验证；
- [ ] 自定义数据、训练配置、最佳权重和评估证据已准备；
- [ ] 测试视频包含有音频和无音频样本；
- [ ] 分支、文件归属和接口字段已经确认；
- [ ] Agent 知识库来源、模型/平台配置和密钥管理方式已确认；
- [ ] 每人知道自己的上午产出和下午验收项；
- [ ] Day 1 12:00 契约检查与 18:00 日终门禁已经明确。

完成以上检查后再进入并行编码。
