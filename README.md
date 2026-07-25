# ReelFire

ReelFire 是课程题目 1“基于 YOLO+Agent 的智能数字媒体内容理解系统”的 FPS 录屏实现。现有代码使用 OpenCV 采样视频帧，以官方 Ultralytics `yolo11n.pt` 检测画面目标，并结合目标密度、场景变化和运动强度生成可解释的精彩分数；用户可以复核带检测框的关键帧、调整候选片段，再由 FFmpeg 输出粗剪视频。课程四天补齐计划还包括独立 Agent、知识库、三工具调用链、自定义模型、统计图和 HTML/PDF 报告，公开任务安排见 `docs/TEAM_GUIDE.md` 与 `docs/REQUIREMENTS_BOARD.md`。

仓库地址：[Amincher-Apie/ReelFire](https://github.com/Amincher-Apie/ReelFire)

## Quick Initialize（快速初始化）

已安装 Miniconda 或 Anaconda 的成员，可以直接执行：

```powershell
git clone https://github.com/Amincher-Apie/ReelFire.git
cd ReelFire
python setup_environment.py
```

脚本会复用当前非 `base` Conda 环境；如果当前没有可复用环境，则自动创建并配置名为 `ReelFire` 的环境。它会根据本机 GPU/CPU 安装合适的 PyTorch，安装 FFmpeg 和业务依赖，并自动下载、校验 `models/yolo11n.pt`。完成后按照脚本最后给出的提示激活环境即可。

注意命令中不需要加入 `run`；`python run setup_environment.py` 会让 Python 尝试打开名为 `run` 的文件。

## 项目方向

本项目选择课程设计题目 **1. 基于 YOLO+Agent 的智能数字媒体内容理解系统**，以 FPS 游戏录屏内容理解与粗剪为具体场景。

```text
上传视频
  -> 创建异步任务
  -> OpenCV 采样
  -> YOLO 检测
  -> 三项指标评分
  -> 关键帧去重与候选片段生成
  -> Agent 解析视觉报告并检索知识库
  -> 生成摘要、标签、建议与三态审核意见
  -> 人工审核和边界调整
  -> FFmpeg 输出视频
  -> 保存报告并支持历史任务重开
```

综合评分公式：

```text
highlight_score =
    object_score * 0.45
  + scene_change_score * 0.35
  + motion_score * 0.20
```

## 团队职责

| 固定角色 | 主要职责 |
|---|---|
| 产品与项目负责人、集成测试 | 需求、进度门禁、接口变更、项目集成、回归、演示和发布 |
| CV/数据工程师 | OpenCV、YOLO 推理/训练、评分、关键帧、评估、跟踪和 FFmpeg 协作 |
| 后端工程师 | Flask API、异步状态、认证、数据层、统计、导出和错误处理 |
| 前端工程师 | 上传、轮询、Agent 结果、三态审核、图表、报告和页面状态 |
| Agent/工作流工程师 | 知识库、Prompt、三工具编排、结构化建议和调用日志 |


## 项目文档

- [`docs/PRD.md`](docs/PRD.md)：FPS 用户场景、MVP 范围、评分规则和功能需求；
- [`docs/REQUIREMENTS_BOARD.md`](docs/REQUIREMENTS_BOARD.md)：按角色划分的 P0/P1 需求看板；
- [`docs/ACCEPTANCE_CHECKLIST.md`](docs/ACCEPTANCE_CHECKLIST.md)：硬性条件、正常/异常和边界验收；
- [`docs/DEMO_FLOW.md`](docs/DEMO_FLOW.md)：8 分钟演示流程和现场兜底方案；
- [`docs/TEAM_GUIDE.md`](docs/TEAM_GUIDE.md)：模块契约、四天时间表和协作规范。

## 获取项目

每位成员可以把仓库克隆到自己的任意工作目录，不需要使用某个固定的绝对路径：

```powershell
git clone https://github.com/Amincher-Apie/ReelFire.git
cd ReelFire
```

如果克隆时自定义了目录名，应进入包含本 README 和 `setup_environment.py` 的目录。

## 一键配置环境

### 前置条件

1. 已安装 Miniconda 或 Anaconda；
2. `conda` 命令可以在当前终端运行；
3. NVIDIA 机器应先安装正常工作的显卡驱动；不要求单独安装 CUDA Toolkit；
4. 可以访问 PyPI、PyTorch 官方 wheel 源和 conda-forge。

### 推荐方式：自动创建或复用环境

在项目根目录执行：

```powershell
python setup_environment.py
```

脚本会自动执行以下操作：

1. 如果当前已经激活非 `base` 的 Conda 环境，则直接复用；
2. 如果没有合适的活动环境，则创建或复用名为 `ReelFire` 的 Python 3.11 环境；
3. 检测操作系统、NVIDIA GPU、驱动版本和当前 PyTorch；
4. 已有可用 CUDA PyTorch 时不重复安装；
5. NVIDIA 机器按驱动选择官方 CUDA wheel；
6. Apple Silicon/macOS 使用支持 MPS 的官方构建；
7. 无兼容 GPU 时安装或保留 CPU 构建；
8. 安装 `requirements.txt` 中的 Web、CV 和 YOLO 依赖；
9. 检查 `ffmpeg` 与 `ffprobe`，缺失时通过 conda-forge 安装；
10. 下载官方 `yolo11n.pt` 到 `models/` 并校验 SHA-256；
11. 最后验证依赖、模型加载和计算后端。

脚本不会安装或升级显卡驱动。驱动不可用时会给出错误或回退 CPU。

### 复用自己已有的 Conda 环境

例如已有可用环境 `TestAI`：

```powershell
conda activate TestAI
python setup_environment.py
```

脚本将复用 `TestAI`，不会再创建 `ReelFire` 环境。当前环境中若已经存在可用的 GPU PyTorch，也不会重新下载。

### 只查看操作，不安装

```powershell
python setup_environment.py --dry-run
```

### 强制重新适配 PyTorch

仅在 PyTorch 后端异常或更换显卡后使用：

```powershell
python setup_environment.py --force-torch
```

### 自定义新环境名称

```powershell
python setup_environment.py --env-name ReelFireDev
```

配置结束后，按照脚本最后显示的名称激活环境：

```powershell
conda activate ReelFire
```

## 为什么 PyTorch 不固定在 requirements.txt 中

PyTorch 的 CPU、NVIDIA CUDA 和 macOS/MPS 构建不同。把某个 CUDA 版本硬编码到公共依赖文件，会导致其他成员的机器安装失败或错误地使用 CPU。

因此本项目采用两层依赖管理：

- `setup_environment.py`：按本机硬件安装或保留合适的 `torch`、`torchvision`；
- `requirements.txt`：锁定全组一致的 Flask、OpenCV、Ultralytics 等业务依赖。

不要绕过脚本后再手工安装另一套 PyTorch。如确需改变依赖版本，应提交对脚本或 `requirements.txt` 的同步修改。

## 环境验证

安装脚本会自动验证，也可以手工检查：

```powershell
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
python -c "import cv2, flask; from ultralytics import YOLO; print('dependencies ok')"
ffmpeg -version
ffprobe -version
```

NVIDIA 机器的 `torch.cuda.is_available()` 应为 `True`。CPU 机器返回 `False` 属于正常情况，只是 YOLO 推理速度会较慢。

## 模型约定

当前可运行基线统一使用 Ultralytics 官方 `yolo11n.pt`。初始化脚本从 Ultralytics 官方 Release 下载固定版本权重，并使用 SHA-256 校验完整性；模型属于本机运行依赖，因此继续由 `.gitignore` 排除，不直接提交 GitHub。课程四天计划另行增加自定义类别、训练配置、最佳权重和官方模型/多阈值对比证据；在该代码与证据完成前，不得把自定义模型写成现有能力。

`yolo11n.pt` 使用 COCO 类别，能够为通用目标提供真实类别、置信度和边界框，但它不是击杀事件识别模型。ReelFire 的“精彩”推荐由目标分数、场景变化和运动强度共同决定，报告和页面只展示模型真实输出，不虚构 FPS 专用标签。

## 验收证据

- 浏览器完整流程与状态截图：[`docs/Acceptance_screenshot/`](docs/Acceptance_screenshot/)
- 最终 5 条正常、5 条异常记录：[`docs/TEST_REPORT.md`](docs/TEST_REPORT.md)
- 三个真实 Bug 及回归：[`docs/BUG_RECORD.md`](docs/BUG_RECORD.md)
- 8 分钟演示与本机彩排记录：[`docs/DEMO_FLOW.md`](docs/DEMO_FLOW.md)

## 计划目录结构

```text
ReelFire/
├─ README.md
├─ requirements.txt
├─ setup_environment.py
├─ app.py
├─ config.py
├─ models/
├─ routes/
├─ services/
├─ cv_engine/
├─ templates/
├─ static/
├─ tests/
├─ docs/
├─ assets/
└─ outputs/
```

模块归属：

- `routes/`、`services/job_service.py`：后端工程师；
- `cv_engine/`、`services/analysis_service.py`、`services/ffmpeg_service.py`：CV 算法工程师；
- 计划新增的 `services/agent_service.py`、`knowledge_base/` 和 Prompt：Agent/工作流工程师；
- `templates/`、`static/`：前端工程师；
- `tests/` 按模块由对应角色维护；集成测试、测试报告和 Bug 记录由项目负责人组织；
- `README.md`、PRD、验收清单、整体集成：项目负责人组织，全员共同维护。

## Git 协作

建议分支：

```text
main
├─ feature/cv-model-tracking     # CV/数据工程师
├─ feature/backend-auth-report   # 后端工程师
├─ feature/frontend-dashboard    # 前端工程师
├─ feature/agent-workflow        # Agent/工作流工程师
└─ docs/project-management       # 产品与项目负责人
```

提交信息建议采用：

```text
feat(cv): implement highlight scoring
feat(api): add asynchronous job creation
feat(ui): add keyframe review panel
test(video): cover clip boundary cases
docs(prd): define acceptance criteria
```

接口或 JSON 字段需要调整时，应先通知组长，并同步更新 `docs/API.md`，避免前后端和算法各自使用不同格式。

## 启动方式

后端入口 `app.py` 已在 `backend` 分支完成第一阶段整合，统一使用：

```powershell
conda activate ReelFire
python app.py --host 127.0.0.1 --port 7880
```

如果实际复用的是其他 Conda 环境，请替换第一行的环境名。

浏览器访问：

```text
http://127.0.0.1:7880
```

健康检查：

```text
http://127.0.0.1:7880/api/health
```

### 第一阶段后端能力

当前已实现视频上传、任务目录与 `job.json` 持久化、历史任务查询、安全删除、后台状态流转、报告读取和人工审核写回。公共接口及题目 1 的现有内容理解接口为：

```text
GET    /api/health
POST   /api/jobs
GET    /api/jobs
GET    /api/jobs/<job_id>
DELETE /api/jobs/<job_id>
POST   /api/jobs/<job_id>/analyze
PATCH  /api/jobs/<job_id>/review
POST   /api/jobs/<job_id>/rough-cut
GET    /api/jobs/<job_id>/report
```

当前已接入真实 OpenCV 采样、YOLO11n 推理、带检测框关键帧、三项评分、联系表和 FFmpeg 粗剪。分析异常会进入 `failed` 并保存可读错误；FFmpeg 缺失时粗剪接口返回 `501`。系统不会生成假关键帧、假分数、假报告或假视频。完整请求字段和状态码见 [`docs/API.md`](docs/API.md)。

## 基础检查

```powershell
python -m py_compile app.py
python -m unittest discover -s tests -v
node --check static/app.js
python -c "from app import create_app; app=create_app(); print(app.url_map)"
python -m tests.local_acceptance
```

上述文件尚未加入时可以跳过对应命令；合并到 `main` 前必须执行与自己模块相关的检查。

## 最小验收闭环

```text
上传一个合法视频
  -> 立即返回 job_id
  -> 状态 queued/running/completed 或 failed 真实变化
  -> 完成一次真实 YOLO 分析
  -> 展示关键帧和可解释分数
  -> 保存 analysis_report.json
  -> 输出一段粗剪视频
  -> 可以从历史任务重新打开
```

完成最小闭环后，再实现多片段合并、三种发布规格、交付 ZIP 等加分功能。当前报告已额外提供候选片段真实目标统计和基于真实检测的封面描述。

## 常见问题

### Conda 命令找不到

请使用 Anaconda Prompt/Miniconda Prompt，或先运行 Conda 的 shell 初始化。不要把整个 Conda 安装目录复制到仓库。

### 有 NVIDIA 显卡但 CUDA 验证失败

先运行：

```powershell
nvidia-smi
```

如果命令不存在或报错，应先修复 NVIDIA 驱动。驱动正常后执行：

```powershell
python setup_environment.py --force-torch
```

### FFmpeg 安装后仍提示找不到

关闭当前终端，重新打开并激活项目环境：

```powershell
conda activate ReelFire
ffmpeg -version
ffprobe -version
```

### 依赖安装后只有自己能运行

确认新增依赖已经写入 `requirements.txt`，并提交该文件。不要只发送 `pip list` 截图，也不要提交整个 Conda 环境目录。
