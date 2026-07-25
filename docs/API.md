# ReelFire API 文档

> 更新日期：2026-07-25
> 适用范围：当前可运行代码、当前自动化测试、剪辑预览 1.0 契约，以及明确标注的后续规划。

## 1. 文档口径与优先级

本文件用于统一 ReelFire 当前接口事实、前端消费方式和后续兼容边界。

发生表述不一致时，按以下顺序判断：

1. **当前可运行代码与自动化测试**：决定接口是否已经实现、当前实际状态码和当前可用字段。
2. **`docs/EDITOR_API_CONTRACT.md`**：决定 `GET /api/jobs/{job_id}/editor` 的 1.0 成功响应字段、类型和兼容规则。
3. **`docs/EDITOR_UI_STRUCTURE.md`**：决定剪辑预览页的页面职责、数据绑定、状态和交互。
4. **本文件**：汇总通用接口、认证、任务接口、编辑页入口和后续规划。

公共字段发生变化时，必须同时更新：

- 生产接口；
- 后端测试；
- 前端消费代码或前端契约测试；
- `docs/API.md`；
- 涉及剪辑预览时，还必须同步更新 `docs/EDITOR_API_CONTRACT.md`。

本文使用两种状态：

- **已实现**：当前代码和测试已经存在，可作为验收事实。
- **规划中**：尚未完整接入或测试，不得写成已经完成。

---

## 2. 通用约定

### 2.1 数据格式

除文件上传外，请求与响应使用：

```http
Content-Type: application/json; charset=utf-8
```

视频上传使用：

```http
multipart/form-data
```

### 2.2 成功响应

成功响应保留：

```json
{
  "ok": true
}
```

业务数据使用语义字段，例如：

```json
{
  "ok": true,
  "job": {}
}
```

### 2.3 失败响应

失败响应至少包含：

```json
{
  "ok": false,
  "error": "用户可读错误信息"
}
```

已接入稳定错误码的接口同时返回：

```json
{
  "ok": false,
  "error": "请先登录",
  "error_code": "AUTH_REQUIRED"
}
```

兼容原则：

- 前端可显示 `error`；
- 新逻辑应优先依据 `error_code`；
- 不得要求前端通过匹配中文错误文本判断业务状态；
- 旧接口尚未统一 `error_code` 时，不得仅为格式统一破坏现有前端。

### 2.4 时间格式

新增 SQLite 记录使用 ISO 8601 UTC 时间，例如：

```text
2026-07-25T06:30:00+00:00
```

现有文件任务可能仍使用无时区 ISO 字符串。兼容期间不得仅为统一时间格式破坏旧任务读取。

### 2.5 存储边界

当前系统采用混合存储：

- SQLite：用户、项目归属，以及携带 `project_id` 创建的素材和任务索引；审核记录和 Agent 调用日志仍属于后续阶段；
- 文件系统：源视频、`job.json`、`analysis_report.json`、`agent_report.json`、关键帧和导出文件。

任务运行链仍以 `JobService` 和任务目录中的 JSON 文件为事实来源；项目型上传同时在 SQLite 建立归属索引。

---

## 3. 已实现：健康检查

### `GET /api/health`

无需登录。

成功返回 `200`，包含服务状态、版本、模型就绪状态和 FFmpeg 就绪状态。模型不存在时，服务仍可启动并返回健康信息。

---

## 4. 已实现：SQLite 认证

认证使用 Flask Session Cookie。

当前实现：

- 用户写入 SQLite `users` 表；
- 新密码使用 Werkzeug 密码哈希；
- Session 只保存 `user_id`；
- `/me` 根据 `user_id` 重新查询 SQLite；
- 原 `users.db` JSON 用户可在启动时幂等导入；
- 旧 SHA-256 密码使用 `legacy_sha256$` 前缀保存；
- 旧用户首次成功登录后升级为 Werkzeug 哈希；
- 正式运行应配置 `REELFIRE_SECRET_KEY`。

接口不得返回：

```text
password
password_hash
session_secret
```

### 4.1 `POST /api/auth/register`

请求：

```json
{
  "username": "demo_user",
  "password": "example-password"
}
```

约束：

| 字段 | 必填 | 约束 |
| --- | --- | --- |
| `username` | 是 | 去除首尾空白后 2～32 个字符；大小写不敏感唯一 |
| `password` | 是 | 至少 6 个字符 |

成功返回 `201`：

```json
{
  "ok": true,
  "user": {
    "id": 1,
    "username": "demo_user",
    "display_name": null,
    "role": "user"
  }
}
```

允许后端在不删除上述字段的前提下新增 `created_at` 等兼容字段。

错误：

| 状态 | `error_code` | 场景 |
| ---: | --- | --- |
| 400 | `AUTH_INPUT_REQUIRED` | 缺少用户名或密码 |
| 400 | `AUTH_USERNAME_INVALID` | 用户名长度不合法 |
| 400 | `AUTH_PASSWORD_WEAK` | 密码过短 |
| 409 | `AUTH_USERNAME_EXISTS` | 用户名已存在 |

注册成功后建立登录会话。

### 4.2 `POST /api/auth/login`

请求：

```json
{
  "username": "demo_user",
  "password": "example-password"
}
```

成功返回 `200`：

```json
{
  "ok": true,
  "user": {
    "id": 1,
    "username": "demo_user",
    "display_name": null,
    "role": "user"
  }
}
```

用户不存在、密码错误或账号停用统一返回：

```text
401 AUTH_INVALID_CREDENTIALS
```

登录成功后更新 `last_login_at`，并将 `user_id` 写入 Session。

### 4.3 `POST /api/auth/logout`

清除当前和遗留认证 Session 字段。

成功返回 `200`：

```json
{
  "ok": true,
  "message": "已退出登录"
}
```

重复退出保持幂等。

### 4.4 `GET /api/auth/me`

从 Session 读取 `user_id`，再查询 SQLite。

成功返回 `200`：

```json
{
  "ok": true,
  "user": {
    "id": 1,
    "username": "demo_user",
    "display_name": null,
    "role": "user"
  }
}
```

未登录、用户已删除或账号已停用时清除无效 Session，并返回：

```text
401 AUTH_REQUIRED
```

---

## 5. 已实现：任务与视频分析接口

> 上传接口同时支持项目型和旧文件型流程。API、URL 和 JSON 对外仍使用公开字段名 `job_id`。

### 5.1 `POST /api/jobs`

使用 `multipart/form-data`。

必填字段：

| 字段 | 说明 |
| --- | --- |
| `file` | 视频文件；支持 `.mp4`、`.avi`、`.mov`、`.mkv` |

当前可选字段：

```text
project_id
project_name
sample_interval
target_duration
max_keyframes
min_keyframe_gap
object_weight
scene_change_weight
motion_weight
output_ratio
```

约束：

- 空文件、扩展名不支持或文件内容伪装返回 `400`；
- 三个权重范围为 `0..1`，且总和必须为 `1`；
- `output_ratio` 支持 `16:9`、`9:16`、`1:1`；
- 超过 `MAX_CONTENT_LENGTH` 返回 `413`。

兼容流程：

- 表单中没有 `project_id` 时，不要求登录，继续按 `project_name` 创建仅由文件系统管理的任务，不写入 SQLite `assets` 和 `jobs`；
- 表单中存在 `project_id` 时（包括空值），必须登录且该项目必须属于当前用户；空值或非正整数返回 `400 PROJECT_INPUT_INVALID`；
- 项目型上传以 SQLite 项目的 `name` 作为 `job.json` 中可信的 `project_name`，请求中的冲突值不能改变项目归属；
- 项目型上传在同一事务中先写入 `assets`、再写入 `jobs`，数据库失败时回滚并清理本次尚未成功返回的任务目录；
- `jobs.public_job_id` 与响应中的字符串 `job_id` 完全相同。

成功返回 `201`：

```json
{
  "ok": true,
  "job_id": "20260725_120000_1a2b3c4d",
  "status": "created"
}
```

当前前端会先创建任务，再显式调用 `/analyze`。

### 5.2 `GET /api/jobs`

返回 `200` 和按 `created_at` 倒序排列的任务列表。

损坏的单个 `job.json` 会被跳过，不阻塞其他任务列表。

### 5.3 `GET /api/jobs/<job_id>`

返回 `200` 和完整任务：

```json
{
  "ok": true,
  "job": {},
  "report_available": false,
  "result_files": []
}
```

错误：

- 非法 `job_id`：`400`；
- 任务不存在：`404`；
- 任务 JSON 损坏：`500`。

### 5.4 `DELETE /api/jobs/<job_id>`

成功返回 `200` 和 `deleted_job_id`。

错误：

- 任务不存在：`404`；
- `queued` 或 `running` 状态不允许删除：`409`；
- 非法 `job_id`：`400`。

### 5.5 `POST /api/jobs/<job_id>/analyze`

将 `created` 或 `failed` 任务加入后台队列。

成功返回 `202`：

```json
{
  "ok": true,
  "job_id": "20260725_120000_1a2b3c4d",
  "status": "queued"
}
```

不存在返回 `404`；重复排队、运行中或已完成返回 `409`。

后台执行 OpenCV 采样、YOLO 推理、评分和关键帧生成。解码、模型或推理异常会将任务标记为 `failed`，并保存可读错误。

### 5.6 `PATCH /api/jobs/<job_id>/review`

当前接口可更新分析报告中的：

```text
keyframes
segments
recommended_clip
```

片段约束：

```text
0 <= start < end <= duration
```

`recommended_clip` 使用：

```text
start_time
end_time
output_ratio
```

`segments[]` 使用：

```text
id
start
end
order
score
source_keyframes
```

成功返回 `200` 和更新后的 `report`。

错误：

- 任务不存在：`404`；
- 报告尚未生成：`409`；
- 字段或片段边界错误：`400`。

当前该接口主要完成文件报告写回；内容级三态审核历史落入 SQLite 属于后续规划。

### 5.7 `POST /api/jobs/<job_id>/rough-cut`

当前实现为单片段粗剪兼容接口。

请求体可省略，也可覆盖：

```text
start_time
end_time
output_ratio
```

只接受 `completed` 且已有报告的任务。

成功生成 MP4 后返回 `200`，并把输出路径写回任务与报告。

错误：

- 状态或报告冲突：`409`；
- 参数错误：`400`；
- FFmpeg 不可用：`501`。

多片段按审核顺序拼接属于后续规划。

### 5.8 `GET /api/jobs/<job_id>/report`

成功返回：

```json
{
  "ok": true,
  "report": {}
}
```

报告可能包含：

```text
duration
samples
keyframes
recommended_clip
segments
segment_tags
ai_cover_prompt
output
```

事实边界：

- `segment_tags` 来自真实 YOLO 检测结果；
- `ai_cover_prompt` 只能依据真实检测内容生成；
- 不得把规则文案冒充 Agent 最终结论。

错误：

- 任务或报告不存在：`404`；
- 报告 JSON 损坏：`500`。

---

## 6. 已实现：剪辑预览 1.0

### 6.1 页面入口

```text
/jobs/{job_id}/editor
```

页面唯一数据源：

```http
GET /api/jobs/{job_id}/editor
```

页面负责播放、时间轴定位、精彩片段列表和 Agent 评论状态展示，不运行 YOLO，不在浏览器中生成 Agent 评论。

页面结构、DOM 身份和交互规则以：

```text
docs/EDITOR_UI_STRUCTURE.md
```

为准。

### 6.2 聚合接口

```http
GET /api/jobs/{job_id}/editor
Accept: application/json
```

成功响应字段与类型以：

```text
docs/EDITOR_API_CONTRACT.md
```

的 `1.0` 契约为准。

核心结构：

```json
{
  "ok": true,
  "contract_version": "1.0",
  "job": {
    "job_id": "20260725_120000_1a2b3c4d",
    "project_name": "FPS 视频内容理解",
    "status": "completed",
    "created_at": "2026-07-25T12:00:00",
    "completed_at": "2026-07-25T12:03:10"
  },
  "video": {
    "url": "/outputs/20260725_120000_1a2b3c4d/input/demo.mp4",
    "filename": "demo.mp4",
    "duration": 687.4
  },
  "highlights": [
    {
      "id": "seg_001",
      "order": 1,
      "start": 14.2,
      "end": 21.8,
      "duration": 7.6,
      "score": 0.86,
      "source_keyframes": ["kf_001"],
      "agent_comment": null,
      "agent_comment_status": "pending",
      "agent_evidence_refs": []
    }
  ],
  "output": {
    "rough_cut_url": null,
    "contact_sheet_url": null,
    "ratio": "16:9"
  }
}
```

片段必须满足：

```text
0 <= start < end <= video.duration
duration = end - start
id 唯一
order 唯一
```

Agent 评论状态：

| 状态 | `agent_comment` | 页面行为 |
| --- | --- | --- |
| `ready` | 非空字符串 | 显示最终评论 |
| `pending` | `null` | 显示“Agent 评论尚未生成” |
| `unavailable` | `null` | 显示“Agent 评论不可用” |

评论读取优先级：

1. `agent_report.json.segment_comments[]` 中相同 `segment_id`；
2. 带有 `ev:segment:{segment_id}` 证据引用的建议；
3. 没有可验证结果时返回 `pending`。

后端不得把前端拼接文案或未经 Agent 验证的规则文案标记为 `ready`。

### 6.3 当前错误

当前编辑契约定义：

| 状态 | 场景 |
| ---: | --- |
| 400 | `job_id` 或报告字段不合法 |
| 404 | 任务或源视频不存在 |
| 409 | 任务未完成或报告尚未生成 |
| 500 | 持久化数据损坏或内部错误 |

任务权限接入后的 `401 AUTH_REQUIRED` 和 `403 JOB_ACCESS_DENIED` 属于后续规划；在实现和测试完成前，不写成当前已具备能力。

### 6.4 兼容要求

编辑页 1.0 允许新增字段，但不允许：

- 删除已有字段；
- 改变已有字段类型；
- 改变 `contract_version` 含义；
- 让前端根据 `samples` 自行生成评论；
- 让前端根据 `score` 伪造自然语言结论。

前端必须忽略未知新增字段。

---

## 7. 当前报告字段兼容关系

当前系统同时保留两种片段结构：

### 7.1 `recommended_clip`

用途：

- 兼容旧版单片段粗剪；
- 保存单个推荐区间；
- 当前 `/rough-cut` 可直接使用。

字段：

```text
start_time
end_time
output_ratio
```

### 7.2 `segments[]`

用途：

- 保存多个精彩片段；
- 作为剪辑预览聚合接口的主要片段来源；
- 后续与 Agent `segment_comments[]` 按稳定 ID 关联；
- 后续用于多片段审核、排序和导出。

字段至少包含：

```text
id
order
start
end
score
source_keyframes
```

两者在兼容期可以同时存在。不得把 `recommended_clip` 误写成当前唯一片段格式，也不得在多片段链路稳定前删除它。

---

## 8. 当前前端消费约束

### 8.1 认证页面

当前前端只发送：

```json
{
  "username": "...",
  "password": "..."
}
```

当前前端只依赖成功响应中的：

```text
user.username
```

后端新增 `id`、`display_name`、`role`、`created_at` 等字段不会破坏前端，但不得删除 `username`。

### 8.2 上传工作台

当前前端上传仍发送：

```text
file
project_name
game_type
sample_interval
target_duration
output_ratio
```

其中当前后端契约仍以 `project_name` 为兼容字段。

在前端完成项目创建和项目选择之前，后端不得突然强制要求 `project_id`，否则当前可运行上传流程会失效。

### 8.3 剪辑预览页

当前前端只请求：

```text
GET /api/jobs/{job_id}/editor
```

并依赖：

```text
contract_version
job.project_name
video.url
video.duration
highlights[]
output.rough_cut_url
```

前端对未知新增字段应保持容忍。

---

## 9. 已实现：SQLite 项目与上传任务归属

已实现接口：

```http
POST /api/projects
GET  /api/projects
```

两个接口均要求登录。`owner_id` 只来自当前 Session，客户端不得指定。

`POST /api/projects` 接收：

```json
{
  "name": "CS2 教学素材",
  "description": "课程演示项目",
  "game_type": "cs2"
}
```

成功返回 `201`，其中 `status` 固定为 `active`。`GET /api/projects`
仅返回当前登录用户自己的项目。

当前数据关系：

```text
当前用户
→ projects.owner_id
→ assets.project_id
→ jobs.project_id
```

项目型上传会校验项目归属、创建文件任务，再在同一事务中创建素材和任务
索引，同时保留任务目录中的 `job.json`。数据库写入失败时清理本次尚未
成功返回的任务目录。

稳定错误：

| HTTP | `error_code` | 场景 |
| ---: | --- | --- |
| 400 | `PROJECT_INPUT_INVALID` | 项目输入或 `project_id` 非法 |
| 400 | `PROJECT_OWNER_FORBIDDEN` | 请求体尝试指定 `owner_id` |
| 401 | `AUTH_REQUIRED` | 项目接口或项目型上传未登录 |
| 403 | `PROJECT_ACCESS_DENIED` | 项目属于其他用户 |
| 404 | `PROJECT_NOT_FOUND` | 项目不存在 |

旧文件型任务可能没有 SQLite `jobs` 索引。现有 editor、review、
analyze、delete 等任务接口的归属保护仍属于下一阶段。

---

## 10. 规划中：任务权限

> 当前认证已实现，但任务和编辑页归属校验尚未完整接入。

目标规则：

```text
当前用户
→ SQLite jobs 记录
→ 所属 project
→ project.owner_id
```

不能只根据公开 `job_id` 判断权限。

目标错误：

| 状态 | `error_code` | 场景 |
| ---: | --- | --- |
| 401 | `AUTH_REQUIRED` | 未登录 |
| 403 | `PROJECT_ACCESS_DENIED` | 无权访问项目 |
| 403 | `JOB_ACCESS_DENIED` | 无权访问任务 |
| 404 | `PROJECT_NOT_FOUND` | 项目不存在 |
| 404 | `JOB_NOT_FOUND` | 任务不存在 |

目标受保护接口包括：

```text
POST   /api/jobs
GET    /api/jobs
GET    /api/jobs/<job_id>
DELETE /api/jobs/<job_id>
POST   /api/jobs/<job_id>/analyze
PATCH  /api/jobs/<job_id>/review
POST   /api/jobs/<job_id>/rough-cut
GET    /api/jobs/<job_id>/report
GET    /api/jobs/<job_id>/editor
```

---

## 11. 规划中：内容级三态审核

目标三态：

```text
approved
pending
rejected
```

对应：

| API 值 | 中文 |
| --- | --- |
| `approved` | 通过 |
| `pending` | 待复核 |
| `rejected` | 不通过 |

说明：

- `keep/skip` 仍表示单个关键帧决策；
- 内容级三态保存到 SQLite `reviews`；
- 片段、关键帧和备注仍同步写入文件报告；
- 每次审核应保留历史，不静默覆盖上一条记录。

计划接口：

```http
GET /api/jobs/<job_id>/reviews
```

写回可以继续复用：

```http
PATCH /api/jobs/<job_id>/review
```

---

## 12. 规划中：Agent 调用日志

Agent 业务由 Agent 模块实现；后端负责权限、状态和日志持久化。

计划接口：

```http
POST /api/jobs/<job_id>/agent-calls
GET  /api/jobs/<job_id>/agent-calls
GET  /api/agent-calls/<agent_call_id>
```

状态：

```text
queued
running
completed
failed
needs_review
```

后端至少记录：

```text
job_id
requested_by
status
model_name
prompt_version
input_summary
output_summary
tool_trace_json
references_json
result_path
duration_ms
error_code
error_message
created_at
completed_at
```

Agent 失败不得破坏已有 CV 报告；缺失或损坏的 Agent 结果应在编辑聚合接口中表现为 `pending` 或 `unavailable`。

---

## 13. 规划中：编辑结果写回与多片段导出

后续能力包括：

- 修改片段边界；
- 修改片段顺序；
- 内容级三态审核；
- 刷新和历史重开后恢复编辑结果；
- 按已审核片段生成多片段粗剪；
- 输出统计 JSON；
- 导出审核包和 HTML/PDF 报告。

这些能力未完成代码和测试前，不得写成当前接口已经可用。

---

## 14. 全局错误处理

当前全局行为：

| 状态 | 场景 |
| ---: | --- |
| 404 | 未知路由或资源不存在 |
| 405 | HTTP 方法不支持 |
| 413 | 请求体超过 `MAX_CONTENT_LENGTH` |
| 500 | 服务内部错误或持久化数据损坏 |

要求：

- JSON 响应不泄露绝对路径；
- JSON 响应不返回堆栈；
- 详细异常只写服务日志；
- 文件损坏不得导致无关任务全部不可用；
- Agent 不可用不得破坏已有 CV 报告。

---

## 15. 兼容与实施规则

1. 不删除或改名当前任务接口。
2. 不把 Flask 迁移为第二套 API 服务。
3. 不删除 `job.json`、`analysis_report.json` 或任务目录。
4. SQLite 用于认证、归属、审核和调用日志，不用于保存视频二进制内容。
5. 当前上传继续兼容 `project_name`，直到前端完成 `project_id` 切换。
6. 当前单片段粗剪继续兼容 `recommended_clip`。
7. 多片段链路以 `segments[].id` 和 Agent `segment_id` 精确匹配。
8. 编辑页成功响应以 `EDITOR_API_CONTRACT` 1.0 为准。
9. 编辑页结构与交互以 `EDITOR_UI_STRUCTURE` 为准。
10. 新增 `error_code` 时继续保留 `error`。
11. 公共字段变化必须同步代码、测试、前端和文档。
12. 尚未实现或未测试的接口必须明确标注“规划中”。
13. 不得把规则回退、前端拼接或 Mock 数据写成真实 Agent 结果。
14. 不得把通用 YOLO 检测结果写成未被模型真实检测到的 FPS 专用事件。
