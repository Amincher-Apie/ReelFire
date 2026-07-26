\# ReelFire 后端 Day 1 基线记录



\## 1. 记录目的



本文档记录后端 Day 1 开发开始前的仓库、运行环境、依赖、任务持久化和测试基线。



本文档只记录已实际核实的事实，不将尚未执行的测试、尚未安装的依赖或尚未实现的功能描述为已完成。



\## 2. 仓库基线



\* 仓库目录：由开发者本地工作区变量 `$repo` 指向，不在仓库文档中保存绝对路径。

\* 远程仓库：`Amincher-Apie/ReelFire`

\* 基线分支：`main`

\* 基线提交：`4c6faf1 ReelFirePro-Final`

\* 后端开发分支：`feature/backend-auth-report`

\* 创建分支前，`main` 与 `origin/main` 同步。

\* 创建分支前，Git 工作区干净。

\* 仓库根目录外的共享虚拟环境不纳入 ReelFire Git 管理。



\## 3. Python 与工具环境



\### 3.1 Python



\* 环境管理工具：uv

\* uv 版本：`0.11.32`

\* Python 版本：`3.11.15`

\* 虚拟环境：工作区根目录共享 `.venv`

\* Python 解释器：`.venv/Scripts/python.exe`



虚拟环境位于 ReelFire 仓库外，不应提交到 Git。



\### 3.2 GPU



本机检测到：



\* NVIDIA GeForce RTX 4060 Laptop GPU

\* NVIDIA 驱动版本：`596.36`

\* `nvidia-smi` 可正常执行

\* 显存以 `nvidia-smi` 显示的约 8 GB 为准



`nvidia-smi` 中显示的 CUDA 兼容版本不等于已经安装 CUDA Toolkit，也不等于 PyTorch CUDA 后端已经可用。



\### 3.3 PyTorch



曾尝试从 PyTorch 官方 `cu128` wheel 源安装 `torch` 和 `torchvision`，但下载约 2.56 GiB 的 `torch` 包时发生 TLS 连接意外中断。



错误摘要：



```text

Failed to download torch==2.11.0+cu128

peer closed connection without sending TLS close\_notify

```



检查结果：



```text

torch installed = False

```



当前没有发现 PyTorch 半安装状态。



该问题不阻塞 Day 1 的数据库、API、错误码和 `JobService` 设计工作。完整 CV 联调前仍需完成 PyTorch、OpenCV、Ultralytics、模型和 FFmpeg 环境验证。



\### 3.4 FFmpeg



当前 PowerShell PATH 中未检测到：



\* `ffmpeg`

\* `ffprobe`



因此当前环境不能执行真实粗剪和依赖 FFprobe 的完整本机验收。



现有粗剪接口在 FFmpeg 缺失时应保持明确失败，不得生成假视频。



\## 4. 项目依赖基线



仓库存在：



```text

requirements.txt

```



仓库当前不存在：



```text

pyproject.toml

uv.lock

requirements-dev.txt

```



`requirements.txt` 中的业务依赖包括：



```text

Flask==3.1.3

numpy==2.4.6

opencv-python==4.13.0.92

Pillow==12.3.0

ultralytics==8.4.95

PyYAML==6.0.3

requests==2.34.2

```



`torch` 和 `torchvision` 没有固定在 `requirements.txt` 中，由环境初始化脚本根据机器硬件选择构建。



现有 `setup\_environment.py` 主要面向 Conda 环境。当前项目使用工作区共享 uv `.venv`，因此不能直接运行该脚本创建第二套 Conda 环境。后续需要采用与共享 uv 环境兼容的安装和验证方式。



\## 5. Flask 与 CV 依赖边界



当前 Flask 应用的导入和初始化链路为：



```text

app.py

→ routes/api\_routes.py

→ services/analysis\_service.py

→ cv2 / numpy / YoloDetector

→ ultralytics

→ PyTorch

```



`app.py` 在模块导入阶段直接导入 `AnalysisService`，并在 `create\_app()` 中创建其实例。



`AnalysisService` 在文件顶层导入 OpenCV、NumPy 和 `YoloDetector`。



`YoloDetector` 在文件顶层导入 Ultralytics。



因此，即使 API 测试不真正执行 YOLO 推理，导入 Flask 应用也可能需要完整的 CV Python 依赖。



模型文件不是在 Flask 应用创建时立即加载，而是在真正调用视频分析时创建 `YoloDetector` 并加载。



\### 当前影响



\* 数据库设计和纯文件服务代码阅读不受影响。

\* 当前无法在空 `.venv` 中运行完整 Flask API 测试。

\* 当前无法把未执行的 API、CV 或完整验收测试记录为通过。

\* 后续可考虑通过依赖注入、测试替身或延迟导入降低测试耦合。

\* Day 1 不为解决此问题进行大范围架构重构。



\## 6. JobService 持久化复核



\### 6.1 文件组织



每个任务使用独立目录，主要保存：



```text

input/

keyframes/

result/

job.json

analysis\_report.json

```



SQLite 引入后仍需保留现有文件型分析机制。



\### 6.2 job\_id 与路径安全



`job\_id` 使用固定格式：



```text

YYYYMMDD\_HHMMSS\_8位十六进制字符

```



`JobService` 同时执行：



\* 正则格式验证；

\* 路径解析；

\* 父目录边界验证。



这可以降低非法任务编号和路径穿越风险。



\### 6.3 原子 JSON 写入



`JobService.\_write\_json()` 的写入流程为：



```text

创建同目录临时文件

→ 写入完整 JSON

→ flush

→ os.fsync

→ os.replace 替换目标文件

→ 清理临时文件

```



该实现可以降低进程在写入中断时产生半截 `job.json` 或 `analysis\_report.json` 的风险。



\### 6.4 线程同步



`JobService` 使用 `threading.RLock` 保护当前 Python 进程中的读写和状态变更。



该锁适用于当前单进程课程 Demo，但不等于支持多个 Flask 进程并发写入同一任务目录。



\### 6.5 当前任务状态



现有状态包括：



```text

created

queued

running

completed

failed

```



忙碌状态包括：



```text

queued

running

```



主要流转为：



```text

created

→ queued

→ running

→ completed

```



执行异常时进入：



```text

failed

```



当前已有以下约束：



\* `queued` 或 `running` 任务不能重复进入分析队列；

\* 只有 `queued` 任务能进入 `running`；

\* `queued` 或 `running` 任务不能删除；

\* 已完成任务暂不支持重复分析。



\### 6.6 重启恢复



Flask 应用创建时调用：



```text

jobs.recover\_interrupted\_jobs()

```



该方法扫描历史任务，并把服务重启前遗留的 `queued` 或 `running` 任务改为：



```text

status = failed

error = 服务重启导致后台分析任务中断，请重新发起分析

```



这样可以避免任务在服务重启后永久停留在“排队中”或“分析中”。



\### 6.7 已识别局限



以下问题需要记录，但不作为 Day 1 阻塞项：



1\. `update\_job()` 允许调用方直接写入任意合法状态，状态机没有完全封装。

2\. `mark\_completed()` 没有检查当前状态必须为 `running`。

3\. `mark\_failed()` 没有限制允许失败的来源状态。

4\. `list\_jobs()` 会跳过损坏或缺失的任务 JSON，历史列表可能隐藏损坏任务。

5\. 文件锁仅在当前 Python 进程内有效。

6\. 时间采用本机无时区 ISO 字符串。

7\. 数据库与文件之间未来可能出现双写一致性问题，需要明确数据库只保存索引和业务元数据，分析报告继续以文件为主。



对于当前单机 Flask 课程项目，现有机制可继续作为文件持久化基线，不进行无关重写。



\## 7. 测试基线



仓库现有测试文件包括：



```text

tests/local\_acceptance.py

tests/test\_api.py

tests/test\_cv\_engine.py

tests/test\_integration\_helpers.py

tests/test\_setup\_environment.py

```



当前测试状态：



\* 尚未在本机共享 `.venv` 中执行完整测试套件。

\* 不能记录“全部测试通过”。

\* `test\_api.py` 会导入 Flask 应用，因此间接依赖 CV Python 包。

\* `test\_cv\_engine.py` 依赖 OpenCV、Ultralytics和模型条件。

\* `local\_acceptance.py` 依赖真实模型、FFmpeg、FFprobe 和完整应用。

\* `test\_setup\_environment.py` 主要测试模型下载和校验逻辑，理论上可在轻量环境中独立运行，但尚未记录本机执行结果。



\## 8. SQLite 引入原则



计划数据库文件：



```text

instance/reelfire.db

```



不得在代码中写死开发者本机绝对路径。



SQLite 保存：



```text

users

projects

assets

jobs

reviews

agent\_calls

knowledge\_documents

```



文件系统继续保存：



```text

原始视频

关键帧

检测结果图

job.json

analysis\_report.json

粗剪视频

HTML/PDF 报告

模型文件

```



数据库引入必须遵守：



1\. 不删除现有 `job.json` 和 `analysis\_report.json` 机制。

2\. SQLite 用于用户、归属、审核、调用日志、查询索引和统计。

3\. 原始媒体和大文件不保存到 SQLite BLOB。

4\. 数据库路径通过 Flask instance 目录或配置生成。

5\. 数据库错误不得破坏已生成的 CV 文件报告。

6\. 数据库 Schema 和 API 字段变化必须同步更新测试与文档。

7\. Day 1 先完成设计和初始化方案，不立即实现全部注册登录逻辑。



\## 9. Day 1 后续工作



后续按以下顺序推进：



1\. 完成 SQLite 表结构和关系设计。

2\. 明确数据库初始化与后续迁移方案。

3\. 冻结认证、项目、任务归属、三态审核和 Agent 日志 API 草案。

4\. 建立统一错误响应格式和错误码表。

5\. 与前端、CV 和 Agent 模块确认共享 Schema。

6\. 检查文档差异和 Git 状态。

7\. 完成 Day 1 第一笔有效文档提交。
