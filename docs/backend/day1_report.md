# 后端工程师 Day 1 工作日报

* 日期：2026-07-24
* 项目：ReelFire
* 开发分支：`feature/backend-auth-report`
* 今日主题：后端基线复核、数据库设计与接口契约冻结

## 1. 今日目标

根据四天开发规划，后端 Day 1 主要完成：

1. 复核现有 Flask 路由和服务初始化流程；
2. 复核 `JobService` 的原子写入、状态流转和服务重启恢复；
3. 设计用户、项目、素材、任务、审核、Agent 调用和知识文档表；
4. 冻结认证、项目归属、三态审核和 Agent 日志 API 草案；
5. 建立统一错误码规范；
6. 建立 SQLite 初始化和迁移方案；
7. 保持现有 Flask、文件任务、CV 和前端接口兼容。

## 2. 已完成工作

### 2.1 Git 与开发环境基线

已确认：

* 仓库远程地址为 `Amincher-Apie/ReelFire`；
* 基线分支为 `main`；
* 基线提交为 `4c6faf1 ReelFirePro-Final`；
* 创建后端功能分支 `feature/backend-auth-report`；
* 分支创建前工作区干净；
* 使用工作区共享 uv 虚拟环境；
* Python 版本为 `3.11.15`；
* 虚拟环境位于 ReelFire 仓库外，不进入 Git。

### 2.2 环境依赖检查

检查结果：

* NVIDIA RTX 4060 Laptop GPU 可被系统识别；
* `nvidia-smi` 可运行；
* 当前虚拟环境没有安装 PyTorch；
* PyTorch CUDA wheel 下载过程中发生 TLS 连接中断；
* 下载失败后检查未发现 PyTorch 半安装状态；
* 当前 PATH 中未检测到 `ffmpeg` 和 `ffprobe`；
* 完整 CV、粗剪和本机验收环境尚未建立。

以上问题不阻塞 Day 1 的数据库、API 和错误码设计，但会阻塞完整 Flask/CV 测试和真实粗剪测试。

### 2.3 Flask 与 CV 导入链复核

确认当前模块链路为：

```text
app.py
→ routes/api_routes.py
→ services/analysis_service.py
→ cv2 / numpy / YoloDetector
→ ultralytics
→ PyTorch
```

当前 Flask 应用在导入时会加载 `AnalysisService` 模块，因此即使只运行 API 测试，也可能需要 OpenCV、Ultralytics和 PyTorch。

模型文件不会在 `create_app()` 时立即加载，而是在真正执行视频分析时创建 `YoloDetector`。

Day 1 不进行大范围依赖解耦重构，后续可以考虑依赖注入、延迟导入或测试替身。

### 2.4 JobService 复核

确认现有 `JobService` 具备：

* 严格的 `job_id` 格式验证；
* 任务目录边界验证；
* 任务工作区创建和失败清理；
* 使用 `threading.RLock` 保护单进程内读写；
* 使用临时文件、`flush`、`fsync` 和 `os.replace` 原子写入 JSON；
* `created/queued/running/completed/failed` 状态；
* 排队中或运行中任务禁止重复分析；
* 排队中或运行中任务禁止删除；
* 服务重启后将遗留的忙碌任务标记为失败；
* 损坏 JSON 转换为可处理异常。

已识别但暂不阻塞的局限：

* 状态机没有完全封装；
* `mark_completed()` 未强制要求当前状态为 `running`；
* 文件锁不能支持多 Flask 进程并发写入；
* 损坏任务可能在列表中被跳过；
* 时间字符串暂未统一时区；
* 未来需要处理数据库与文件任务之间的同步一致性。

### 2.5 数据库设计

新增数据库设计文档：

```text
docs/DATABASE_DESIGN.md
```

数据库确定使用 SQLite，运行文件计划位于：

```text
instance/reelfire.db
```

设计表包括：

```text
users
projects
assets
jobs
reviews
agent_calls
knowledge_documents
schema_version
```

SQLite 保存用户、归属、审核、调用日志和查询索引。

以下数据继续保存在文件系统中：

```text
原始视频
关键帧
检测结果图
job.json
analysis_report.json
粗剪视频
HTML/PDF 报告
模型文件
```

数据库不保存视频或图片 BLOB。

### 2.6 API 契约

在现有 `docs/API.md` 末尾追加 Day 1 新增接口草案，保留原有任务接口。

新增草案包括：

* 注册、登录、退出和当前用户接口；
* 项目创建、查询和修改接口；
* 上传任务的 `project_id` 归属；
* 任务级用户权限校验；
* 内容级三态审核；
* 审核历史查询；
* Agent 调用创建、列表和详情接口；
* Agent 调用状态和工具轨迹；
* 知识文档查询草案；
* 未登录、越权和所属用户权限矩阵。

内容级审核状态统一为：

```text
approved
pending
rejected
```

关键帧决策继续使用：

```text
keep
skip
```

二者不混用。

### 2.7 错误码设计

新增：

```text
docs/ERROR_CODES.md
```

失败响应计划从：

```json
{
  "ok": false,
  "error": "任务不存在"
}
```

扩展为：

```json
{
  "ok": false,
  "error": "任务不存在",
  "error_code": "JOB_NOT_FOUND"
}
```

保留原有 `error` 字符串以兼容前端，新增稳定 `error_code` 供程序判断。

错误码覆盖：

* 通用请求错误；
* 登录和权限；
* 项目和素材；
* 任务状态；
* 视频分析和模型；
* 报告与三态审核；
* FFmpeg 和粗剪；
* Agent 调用；
* 知识库；
* SQLite 初始化和读写。

### 2.8 SQLite 迁移骨架

新增初始迁移：

```text
database/migrations/001_initial.sql
```

迁移内容包括：

* 八张业务与版本表；
* 主键、唯一约束和外键；
* 状态值 `CHECK` 约束；
* 查询索引；
* `schema_version` 初始版本记录；
* 显式事务。

设计的运行设置包括：

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
```

真实数据库文件尚未提交，也不应提交。

`.gitignore` 增加或计划增加：

```gitignore
instance/
*.db
*.sqlite
*.sqlite3
```

## 3. 今日新增或修改文件

```text
M  .gitignore
M  docs/API.md
A  docs/DATABASE_DESIGN.md
A  docs/ERROR_CODES.md
A  docs/backend/day1_baseline.md
A  docs/backend/day1_report.md
A  database/migrations/001_initial.sql
```

以上状态以最终 `git status` 输出为准。

## 4. 今日验证情况

### 已验证

* Git 基线和后端功能分支；
* Python 3.11 共享虚拟环境；
* PyTorch 当前未安装；
* PyTorch 下载失败后没有半安装状态；
* Flask、AnalysisService 和 YOLO 的导入链；
* `JobService` 原子写入和重启恢复实现；
* 数据库设计与现有文件持久化边界；
* API 和错误码文档之间的主要字段一致性；
* `001_initial.sql` 已在 SQLite 内存数据库中执行通过；
* 已创建并核对 8 张业务及版本表；
* `schema_version` 初始版本为 `(1, 'initial')`；
* `git diff --check` 已通过；
* 当前仓库本地 Git 身份已配置为 `tony1155`。

### Git 提交记录

* 第一笔有效提交已完成；
* 提交哈希：`ed30710`；
* 提交说明：`docs(backend): define day1 database and API contracts`；
* 提交内容包括数据库迁移、数据库设计、API 契约、错误码、后端基线和 SQLite 忽略规则；
* 提交后工作区仅剩本日报未跟踪。

### 尚未验证

* 完整 Flask API 测试；
* CV 测试；
* YOLO 模型加载；
* CUDA 推理；
* FFmpeg 和 FFprobe；
* 真实视频分析；
* 粗剪输出；
* Day 2 认证和数据库代码。

不得将以上尚未验证内容写成已经通过。

## 5. 今日问题与处理

### 问题一：PyTorch 下载失败

现象：

```text
Failed to download torch==2.11.0+cu128
peer closed connection without sending TLS close_notify
```

原因判断：

* 安装包体积较大；
* 下载连接在传输过程中异常关闭；
* 不是 Python 代码错误；
* 当前没有证据表明 GPU 或驱动不可用。

处理：

* 停止重复下载；
* 检查是否存在半安装状态；
* 确认 `torch installed = False`；
* Day 1 先继续不依赖 PyTorch 的后端设计任务；
* 完整联调前再单独处理 CV 环境。

### 问题二：Flask API 测试间接依赖 CV

原因：

* `app.py` 顶层导入 `AnalysisService`；
* `AnalysisService` 顶层导入 OpenCV 和 `YoloDetector`；
* `YoloDetector` 顶层导入 Ultralytics。

处理：

* Day 1 记录依赖边界；
* 不为此进行无关大重构；
* 后续评估延迟导入、依赖注入或测试替身。

### 问题三：FFmpeg 未安装

影响：

* 无法执行真实粗剪；
* 无法执行依赖 FFprobe 的完整验收。

处理：

* Day 1 明确记录；
* 不创建假视频或假通过记录；
* 在完整环境配置阶段单独解决。

## 6. 今日检查点

| 检查项                | 状态  |
| ------------------ | --- |
| 后端功能分支已建立          | 已完成 |
| Flask 路由和服务链已复核    | 已完成 |
| JobService 原子写入已复核 | 已完成 |
| 重启恢复逻辑已复核          | 已完成 |
| 数据库表设计             | 已完成 |
| API 草案             | 已完成 |
| 错误码表               | 已完成 |
| SQLite 迁移骨架        | 已完成 |
| 现有接口未被删除或改名        | 已保持 |
| SQLite 路径未写死本机绝对路径 | 已保持 |
| 敏感信息未写入公开文档        | 已保持 |
| 完整自动化测试            | 未执行 |
| Day 1 有效提交         | 待完成 |

## 7. 次日计划

Day 2 计划：

1. 实现 SQLite 连接和初始化模块；
2. 增加 Flask 数据库配置；
3. 实现注册、登录、退出和当前用户接口；
4. 使用 Werkzeug 安全保存密码哈希；
5. 实现项目创建和项目归属；
6. 为任务接口增加登录与所属项目校验；
7. 实现三态审核和 Agent 调用日志存取；
8. 为新增接口补充最小测试；
9. 不破坏现有文件任务和 CV 报告流程。

## 8. 今日结论

Day 1 已完成后端基线复核、SQLite Schema、初始迁移、API 草案和错误码设计。

当前成果属于可检查的工程设计和迁移骨架，不代表认证、权限、数据库业务接口和 Agent 服务已经实现。

Day 2 应严格按照已冻结契约实现最小功能闭环，避免边编码边修改字段。
