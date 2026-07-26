# 数媒工程实训项目日报

## 基本信息

| 项目 | 内容 |
|---|---|
| 项目名称 | ReelFire — 基于 YOLO+Agent 的智能数字媒体内容理解系统 |
| 日期 | 2026 年 7 月 25 日（Day 2 补充） |
| 姓名 | 唐鹏 |
| 当前阶段 | 开发 / 联调 |

## 一、今天做了什么

1. **审查 feature/frontend 分支后端文件混入情况**：发现 `routes/auth_routes.py` 为旧版草稿（import 写在文件中间、无类型标注、JSON 文件存储），已确认该文件需要重写。其余后端文件（`app.py`、`api_routes.py`、`job_service.py`）为前端功能所需的合法扩展。

2. **从 backend-auth-report 移植数据库层**：创建 `database/` 包（`db.py` + `migrations/001_initial.sql`），包含 7 张业务表（`users`/`projects`/`assets`/`jobs`/`reviews`/`agent_calls`/`knowledge_documents`），WAL 模式 + 外键约束 + 迁移版本管理。在 `config.py` 添加 `DATABASE` 路径配置，`app.py` 集成 `init_db` 初始化流程。

3. **重写认证模块对接 SQLite**：`routes/auth_routes.py` 全面重写，JSON 文件存储 → SQLite `users` 表，PRAGMA NOCASE 索引防重名，登录更新 `last_login_at`，Session 同时存储 `user_id` 和 `username`，支持账号禁用检测。

4. **实现 `/api/projects` 全套端点**：`POST /api/projects`（创建项目，写入 SQLite `projects` 表）、`GET /api/projects`（按用户过滤列表）、`GET /api/projects/<id>`（按 owner 鉴权单条查询）。前端 `resolveProject()` 从之前的永久 404 降级变为真实创建项目返回 `project.id`。

5. **移植 api_routes.py 增强**：从 backend-auth-report cherry-pick `_validate_segments()` 校验函数、关键帧 `decision` 字段 keep/skip 校验、`create_job` 的 `game_type` 校验及写入、`review_job` 的 `segments` 字段支持（含自动派生 recommended_clip）。

6. **移植完整 CV 分析管线**：`services/analysis_service.py` 替换为 backend-auth-report 版本，含 `analyze_video()` 真实实现（OpenCV 采样 + YOLO 检测 + HighlightScorer 评分）、`_bounded_clip` 片段边界算法、`_annotate_frame` 检测框标注、`_save_contact_sheet` 关键帧联系表生成、视频元数据回写。

7. **修复 project_name 与 project_id 混用问题**：`resolveProject()` 增加缓存名称一致性校验（`state.currentProjectName === projectName`），名称变更时清空旧 ID；在 `#project-name` 输入框绑定 `input` 事件即时清理。

8. **修复 POST /api/projects 错误分级处理**：`api.request()` 在 Error 对象附加 `err.status`；`resolveProject()` 的 catch 按 HTTP 状态码分级——401/403/400/500 弹 toast 提示用户，404 及网络错误静默降级。

9. **修复两处 `read_job()` 方法名错误**：`app.py` 编辑器页面路由和 `api_routes.py` 编辑器聚合接口中 `jobs.read_job()` 均修正为 `jobs.get_job()`。

## 二、当前进度

| 功能模块 | 当前状态 | 完成情况 |
|---|---|---|
| 前端页面 | 进行中 | 编辑页框架完成，project_id 上传流完成，错误处理已分级 |
| 后端接口 | 进行中 | 数据库层已落地，`/api/projects` 端点已实现，认证已迁 SQLite |
| Agent/工作流 | 进行中 | 前端三态已对接，后端 agent_calls 表已建 |
| 数据库/知识库 | 进行中 | SQLite 7 表迁移完成，待认证联调 |
| 测试与交付 | 未开始 | Python 语法检查通过，浏览器回归待联调 |

总体进度：`~55%`

## 三、Git 提交记录

| 提交时间 | Commit ID | 提交内容 | 分支 |
|---|---|---|---|
| 2026-07-25 | 1a6f820 | fix(frontend): integrate backend-auth-report database layer and fix project_id/error-handling | feature/frontend |
| 2026-07-25 | a15f0b0 | docs(frontend): add Day 2 daily report for Tang Peng | feature/frontend |
| 2026-07-25 | f874052 | feat(frontend): complete Day 2 editor workbench and project_id integration | feature/frontend |

截图：

```text
1a6f820 fix(frontend): integrate backend-auth-report database layer and fix project_id/error-handling
  - Port database/ package (SQLite + 001_initial migration) from backend-auth-report
  - Rewrite auth_routes.py: JSON file → SQLite users table, clean code style
  - Add POST/GET /api/projects endpoints backed by SQLite projects table
  - Port api_routes.py enhancements: _validate_segments, decision/game_type validation
  - Port full CV analysis pipeline in analysis_service.py
  - Fix app.js: clear currentProjectId on project_name change (input listener)
  - Fix app.js: HTTP status-aware error handling in resolveProject()
  - Fix app.py + api_routes.py: jobs.read_job() → jobs.get_job()
```

## 四、遇到的问题

1. 问题：backend-auth-report 与 feature/frontend 的 `app.js` 为两个完全不同的版本（ES5 `var` vs ES6 `const`/箭头函数），直接 merge 无法工作。
   - 原因：backend-auth-report 基于早期版本迭代数据库层，feature/frontend 进行了前端全面重写。
   - 解决方法：以 feature/frontend 的 ES6 版 `app.js` 为准，只从 backend-auth-report cherry-pick 数据库层和后端增强，不覆盖前端代码。

2. 问题：`backend-auth-report` 完全移除了认证模块（`auth_bp`），但 `feature/frontend` 的登录/注册/编辑器页面依赖认证。
   - 原因：`backend-auth-report` 重点在做数据库 schema 和后端分析服务，尚未接入认证层。
   - 解决方法：保留 `feature/frontend` 的认证体系，将 `auth_routes.py` 从 JSON 文件存储迁移到 SQLite `users` 表，使其与 `database/` 包对接。

3. 问题：`backend-auth-report` 有 `projects` 表但没有 `/api/projects` 端点，前端 `resolveProject()` 永远走 404 降级。
   - 原因：数据库 DDL 先行，API 实现滞后。
   - 解决方法：在 `api_routes.py` 新增全套 `/api/projects` 端点，前后端现已打通。

## 五、下一步计划

1. 与邓一道联调认证 + 权限，测试 SQLite `users` 表与前端登录/注册/登出全流程
2. 测试 `/api/projects` 端点与前端 `resolveProject()` 完整链路（创建→缓存→复用→名称变更清缓存）
3. 测试 CV 分析管线是否可正常启动（需 YOLO 模型文件 `models/yolo11n.pt`）
4. 编辑页接入真实聚合接口替换 Mock 数据
5. 完成浏览器回归测试
