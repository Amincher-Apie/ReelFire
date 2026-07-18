# ReelFire

ReelFire 是一个面向游戏录屏、场景演示和宣传素材的智能视频精彩片段提取工作台。系统使用 OpenCV 采样视频帧，使用 Ultralytics YOLO 检测画面目标，并结合目标密度、场景变化和运动强度生成可解释的精彩分数；用户可以复核关键帧、调整候选片段，再由 FFmpeg 输出粗剪视频。

仓库地址：[Amincher-Apie/ReelFire](https://github.com/Amincher-Apie/ReelFire)

## Quick Initialize（快速初始化）

已安装 Miniconda 或 Anaconda 的成员，可以直接执行：

```powershell
git clone https://github.com/Amincher-Apie/ReelFire.git
cd ReelFire
python setup_environment.py
```

脚本会复用当前非 `base` Conda 环境；如果当前没有可复用环境，则自动创建并配置名为 `ReelFire` 的环境。完成后按照脚本最后给出的提示激活环境即可。

## 项目方向

本项目选择课程任务书中的 **方向 B：智能视频精彩片段提取系统**。

```text
上传视频
  -> 创建异步任务
  -> OpenCV 采样
  -> YOLO 检测
  -> 三项指标评分
  -> 关键帧去重与候选片段生成
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

| 角色 | 主要职责 |
|---|---|
| 组长、产品负责人 | 需求与验收、进度协调、接口变更确认、项目集成、演示组织 |
| CV 算法工程师 | OpenCV 采样、YOLO 推理与训练、三项评分、关键帧去重、片段边界及 FFmpeg 算法 |
| 后端工程师 | Flask API、异步任务、任务状态、JSON 持久化、历史任务和错误处理 |
| 前端工程师 | 上传与状态轮询、结果展示、关键帧审核、片段调整和页面状态 |
| 测试工程师 | 正常与异常测试、FFmpeg 边界协测、Bug 记录、交付检查和测试报告 |


更完整的模块契约、单日时间表、联调顺序、测试要求和演示流程见 [`docs/TEAM_GUIDE.md`](docs/TEAM_GUIDE.md)。

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
10. 最后验证所有关键模块和计算后端。

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
├─ cv_core/
├─ templates/
├─ static/
├─ tests/
├─ docs/
├─ assets/
└─ outputs/
```

模块归属：

- `routes/`、`services/job_service.py`：后端工程师；
- `cv_core/`、`services/analysis_service.py`、`services/ffmpeg_service.py`：CV 算法工程师；
- `templates/`、`static/`：前端工程师；
- `tests/`、`docs/TEST_REPORT.md`、`docs/BUG_RECORD.md`：测试工程师；
- `README.md`、PRD、验收清单、整体集成：组长组织，全员共同维护。

## Git 协作

建议分支：

```text
main
├─ feature/cv-analysis       # CV 算法工程师
├─ feature/backend-api       # 后端工程师
├─ feature/frontend          # 前端工程师
├─ test/qa-delivery          # 测试工程师
└─ docs/project-management   # 组长、产品负责人
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

待后端入口 `app.py` 合并后，统一使用：

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

## 基础检查

```powershell
python -m py_compile app.py
python -m unittest discover -s tests -v
node --check static/app.js
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

完成最小闭环后，再实现多片段合并、三种发布规格、AI 封面 Prompt、交付 ZIP 等加分功能。

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
