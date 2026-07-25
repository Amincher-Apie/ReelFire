# API 文档

所有成功响应包含 `ok: true`；所有失败响应包含 `ok: false` 与 `error`。请求和响应均使用 UTF-8。

## 与团队指导书的阶段性字段差异

本文件记录当前第一阶段后端的实际契约，并以 Day08 任务书为基础。`docs/TEAM_GUIDE.md` 中有三处面向最终联调的建议字段与当前实现不同，整合时未删除或改写团队指导书：

- 创建任务当前返回 `status: created`，调用方再显式请求 `/analyze`；指导书建议创建后直接返回 `queued`；
- 当前任务设置使用 `output_ratio`；指导书示例使用 `output_aspect`；
- 当前人工片段字段为 `recommended_clip.start_time/end_time`；指导书示例使用 `segments[].start/end`。

前端和算法在本阶段应以本 API 文档为准。若团队决定改用最终指导书字段，应通过一次兼容性变更同时更新路由、测试和本文档，不能只改单方字段。当前时间使用任务书要求的 ISO 8601 秒级字符串，尚未强制附加时区偏移。

## 公共接口

### `GET /api/health`

无需参数。返回 `200`，包含 `status`、`model_ready`、`ffmpeg_ready`、服务名和版本。模型不存在时服务仍正常运行。

### `POST /api/jobs`

使用 `multipart/form-data`。`file` 必填，仅支持 `.mp4/.avi/.mov/.mkv`。可选字段：`project_name`、`sample_interval`、`target_duration`、`max_keyframes`、`min_keyframe_gap`、`object_weight`、`scene_change_weight`、`motion_weight`、`output_ratio`。三个权重范围为 0～1 且总和必须为 1；画幅支持 `16:9/9:16/1:1`。

成功返回 `201`：

```json
{"ok": true, "job_id": "20260718_103015_a1b2c3d4", "status": "created"}
```

缺字段、空文件、格式或参数错误返回 `400`，超出大小上限返回 `413`。

### `GET /api/jobs`

返回 `200` 与按 `created_at` 倒序排列的 `jobs`。损坏的 `job.json` 被跳过，不影响其他任务。

### `GET /api/jobs/<job_id>`

返回 `200` 与完整 `job`，附带 `report_available` 和相对 `result_files`。非法编号返回 `400`，不存在返回 `404`，损坏 JSON 返回 `500`。

### `DELETE /api/jobs/<job_id>`

成功返回 `200` 和 `deleted_job_id`。不存在返回 `404`；`queued/running` 返回 `409`；非法编号返回 `400`。

## 题目 1 现有内容理解接口

### `POST /api/jobs/<job_id>/analyze`

把 `created` 或 `failed` 任务放入后台队列并立即返回 `202`：

```json
{"ok": true, "job_id": "...", "status": "queued"}
```

不存在返回 `404`；已在队列/运行中或已完成返回 `409`。后台执行真实 OpenCV 采样、YOLO11n 推理、评分和关键帧生成；解码、模型或推理异常会进入 `failed` 并写入可读 `error`。

### `PATCH /api/jobs/<job_id>/review`

请求为 JSON 对象，可包含 `keyframes`、`segments` 和/或 `recommended_clip`。推荐片段至少包含 `start_time/end_time`，并满足 `0 <= start < end <= duration`（报告存在 duration 时）。片段使用 `start/end/order`；关键帧支持校验 `timestamp/keep/decision/order/label/note`。

成功返回 `200` 与更新后的 `report`。任务不存在返回 `404`；报告尚未生成返回 `409`；字段或边界错误返回 `400`。

### `POST /api/jobs/<job_id>/rough-cut`

只接受 `completed` 且已有报告的任务。请求体可省略，也可用 JSON 覆盖报告中的 `start_time/end_time/output_ratio`。成功调用 FFmpeg 生成 MP4，返回 `200` 与 `rough_cut_file`，并同步写回任务和报告；FFmpeg 不可用时返回 `501`。任务状态/报告冲突返回 `409`，参数错误返回 `400`。

### `GET /api/jobs/<job_id>/report`

成功返回 `200` 与可重读的 `report`。除视频、采样、分数、关键帧、片段和输出字段外，报告还包含：

- `segment_tags`：候选片段内真实 YOLO 类别的次数、最高置信度和所属片段；
- `ai_cover_prompt`：只基于选中关键帧真实检测结果生成的封面描述，不虚构击杀或残局事件。

任务或报告不存在返回 `404`；报告 JSON 损坏返回 `500`。

## 全局错误

- `404`：未知路由也返回 JSON；
- `405`：不支持的 HTTP 方法；
- `413`：请求体超过 `MAX_CONTENT_LENGTH`；
- `500`：隐藏绝对路径和堆栈，仅在服务日志记录详情。

## Day 1 新增 API 契约草案

> 状态：设计已冻结，代码尚未实现。
> 计划实现阶段：Day 2～Day 3。
> 本节不得作为当前接口已经可用的证明。

本节在保留现有 Flask、文件任务、`job.json` 和 `analysis_report.json` 接口的基础上，增加认证、项目归属、内容级三态审核和 Agent 调用日志契约。

新增接口仍使用现有 `/api` 前缀，不迁移到 FastAPI，也不引入第二套 API 服务。

### 1. 通用约定

#### 1.1 数据格式

除文件上传外，请求和响应均使用：

```http
Content-Type: application/json; charset=utf-8
```

上传视频继续使用：

```http
multipart/form-data
```

#### 1.2 成功响应

成功响应继续保留：

```json
{
  "ok": true
}
```

具体业务数据使用语义明确的字段，例如：

```json
{
  "ok": true,
  "project": {}
}
```

或：

```json
{
  "ok": true,
  "jobs": []
}
```

#### 1.3 失败响应

为兼容当前前端，失败响应继续保留字符串形式的 `error`，并新增稳定的 `error_code`：

```json
{
  "ok": false,
  "error": "请先登录",
  "error_code": "AUTH_REQUIRED"
}
```

可选的字段级错误使用：

```json
{
  "ok": false,
  "error": "请求参数不合法",
  "error_code": "VALIDATION_ERROR",
  "details": {
    "username": "用户名长度必须为 3～32 个字符"
  }
}
```

前端应优先根据 `error_code` 判断错误类型，将 `error` 用作用户可读提示。

不得要求前端通过匹配中文错误文本判断业务逻辑。

#### 1.4 时间格式

新增数据库接口统一返回 ISO 8601 字符串。

目标格式为带时区的 UTC 时间：

```text
2026-07-24T08:30:00+00:00
```

现有文件任务暂时使用无时区 ISO 字符串，兼容期间不得仅为统一格式而破坏已有任务。

#### 1.5 身份验证

第一阶段使用 Flask Session Cookie。

登录成功后，浏览器通过会话 Cookie 访问受保护接口。

不在 URL、JSON 响应、日志或前端本地存储中返回密码哈希。

除注册、登录和健康检查外，新增业务接口默认要求登录。

---

### 2. 认证接口

#### `POST /api/auth/register`

注册普通用户。

请求：

```json
{
  "username": "demo_user",
  "password": "example-password",
  "display_name": "演示用户"
}
```

字段要求：

| 字段             | 必填 | 约束          |
| -------------- | -- | ----------- |
| `username`     | 是  | 3～32 个字符，唯一 |
| `password`     | 是  | 8～128 个字符   |
| `display_name` | 否  | 最长 64 个字符   |

成功返回 `201`：

```json
{
  "ok": true,
  "user": {
    "id": 1,
    "username": "demo_user",
    "display_name": "演示用户",
    "role": "user",
    "created_at": "2026-07-24T08:30:00+00:00"
  }
}
```

错误：

* 用户名或密码不符合要求：`400 VALIDATION_ERROR`
* 用户名已存在：`409 USERNAME_EXISTS`

接口不得返回：

```text
password
password_hash
session_secret
```

#### `POST /api/auth/login`

建立登录会话。

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
    "display_name": "演示用户",
    "role": "user"
  }
}
```

错误：

* 用户名或密码错误：`401 INVALID_CREDENTIALS`
* 用户被禁用：`403 USER_DISABLED`

为了避免泄露用户是否存在，用户名不存在和密码错误使用同一错误码。

#### `POST /api/auth/logout`

删除当前登录会话。

成功返回 `200`：

```json
{
  "ok": true
}
```

重复退出也可以返回 `200`，保证接口幂等。

#### `GET /api/auth/me`

返回当前登录用户。

成功返回 `200`：

```json
{
  "ok": true,
  "user": {
    "id": 1,
    "username": "demo_user",
    "display_name": "演示用户",
    "role": "user"
  }
}
```

未登录返回：

```text
401 AUTH_REQUIRED
```

---

### 3. 项目接口

#### `POST /api/projects`

创建项目。

请求：

```json
{
  "name": "Valorant 录屏分析",
  "description": "课程演示项目",
  "game_type": "Valorant"
}
```

成功返回 `201`：

```json
{
  "ok": true,
  "project": {
    "id": 1,
    "name": "Valorant 录屏分析",
    "description": "课程演示项目",
    "game_type": "Valorant",
    "status": "active",
    "created_at": "2026-07-24T08:40:00+00:00",
    "updated_at": "2026-07-24T08:40:00+00:00"
  }
}
```

错误：

* 未登录：`401 AUTH_REQUIRED`
* 字段错误：`400 VALIDATION_ERROR`

#### `GET /api/projects`

返回当前用户拥有的项目。

成功返回 `200`：

```json
{
  "ok": true,
  "projects": [
    {
      "id": 1,
      "name": "Valorant 录屏分析",
      "game_type": "Valorant",
      "status": "active",
      "created_at": "2026-07-24T08:40:00+00:00",
      "updated_at": "2026-07-24T08:40:00+00:00"
    }
  ]
}
```

普通用户不得看到其他用户的项目。

#### `GET /api/projects/<project_id>`

返回项目详情和必要统计。

成功返回 `200`：

```json
{
  "ok": true,
  "project": {
    "id": 1,
    "name": "Valorant 录屏分析",
    "description": "课程演示项目",
    "game_type": "Valorant",
    "status": "active",
    "asset_count": 3,
    "job_count": 5,
    "created_at": "2026-07-24T08:40:00+00:00",
    "updated_at": "2026-07-24T08:40:00+00:00"
  }
}
```

错误：

* 项目不存在：`404 PROJECT_NOT_FOUND`
* 当前用户不拥有该项目：`403 PROJECT_ACCESS_DENIED`

不得为了隐藏越权事实而把所有越权场景都静默返回空列表。

#### `PATCH /api/projects/<project_id>`

修改项目名称、说明、游戏类型或状态。

请求可包含：

```json
{
  "name": "CS2 比赛录屏",
  "description": "修改后的项目说明",
  "game_type": "CS2",
  "status": "active"
}
```

`status` 只允许：

```text
active
archived
```

成功返回 `200` 与更新后的 `project`。

---

### 4. 上传与任务归属

现有：

```http
POST /api/jobs
```

继续保留，不建立第二套上传接口。

Day 2 增加登录和项目归属后，请求新增必填字段：

```text
project_id
```

上传示例：

```text
file=<视频文件>
project_id=1
sample_interval=0.5
target_duration=30
output_ratio=16:9
```

现有 `project_name` 字段进入兼容阶段：

* 尚未实现数据库前继续支持；
* 数据库接口落地后，前端改用 `project_id`；
* 兼容期内不能同时根据 `project_name` 创建隐式项目；
* 删除兼容字段前必须同步修改前端、测试和本文档。

成功响应保持兼容：

```json
{
  "ok": true,
  "job_id": "20260724_164000_a1b2c3d4",
  "status": "created"
}
```

可新增但不强制前端立即使用：

```json
{
  "ok": true,
  "job_id": "20260724_164000_a1b2c3d4",
  "status": "created",
  "project_id": 1,
  "asset_id": 3
}
```

创建任务前必须验证：

```text
当前用户已登录
→ project_id 存在
→ 当前用户拥有该项目
→ 上传文件通过原有安全校验
```

错误：

* 未登录：`401 AUTH_REQUIRED`
* 项目不存在：`404 PROJECT_NOT_FOUND`
* 无权访问项目：`403 PROJECT_ACCESS_DENIED`
* 上传文件不合法：保持现有 `400`
* 文件过大：保持现有 `413`

---

### 5. 任务查询与权限

以下现有接口继续保留：

```http
GET    /api/jobs
GET    /api/jobs/<job_id>
DELETE /api/jobs/<job_id>
POST   /api/jobs/<job_id>/analyze
PATCH  /api/jobs/<job_id>/review
POST   /api/jobs/<job_id>/rough-cut
GET    /api/jobs/<job_id>/report
```

数据库权限接入后，所有任务接口必须执行：

```text
当前用户
→ 数据库 jobs 记录
→ 所属 project
→ project.owner_id
```

不能只验证公开 `job_id` 存在。

#### `GET /api/jobs`

新增可选查询参数：

```text
project_id
status
page
page_size
```

示例：

```http
GET /api/jobs?project_id=1&status=completed&page=1&page_size=20
```

成功返回：

```json
{
  "ok": true,
  "jobs": [],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total": 0
  }
}
```

第一阶段可暂不实现复杂分页，但字段一旦返回，含义必须保持稳定。

普通用户只能看到自己项目的任务。

#### 历史任务重开

现有已完成任务暂不允许直接重复分析。

后续“历史任务重开”采用创建新任务记录的方式，不把原任务状态从 `completed` 改回 `queued`。

计划接口：

```http
POST /api/jobs/<job_id>/reopen
```

成功返回 `201`：

```json
{
  "ok": true,
  "source_job_id": "20260724_164000_a1b2c3d4",
  "job_id": "20260724_170000_b2c3d4e5",
  "status": "created"
}
```

新任务可以复用原素材，但必须拥有新的 `job_id`、状态和分析记录。

本接口为 Day 3 草案，Day 1 不实现。

---

### 6. 内容级三态审核

现有：

```http
PATCH /api/jobs/<job_id>/review
```

继续负责：

* 关键帧 `keep/skip`；
* 人工标签和备注；
* 片段边界；
* 推荐片段；
* 输出比例。

Day 2 在同一接口中增加内容级审核字段，不另建冲突接口。

请求示例：

```json
{
  "review_status": "pending",
  "labels": [
    "高运动强度",
    "多人目标"
  ],
  "note": "模型置信度较低，需要人工再次确认",
  "segments": [
    {
      "id": "seg_001",
      "start": 12.5,
      "end": 35.0,
      "order": 1
    }
  ],
  "keyframes": [
    {
      "id": "kf_001",
      "timestamp": 18.2,
      "decision": "keep",
      "label": "候选精彩帧",
      "note": "保留",
      "order": 1
    }
  ]
}
```

`review_status` 只允许：

```text
approved
pending
rejected
```

对应中文：

| API 值      | 中文  |
| ---------- | --- |
| `approved` | 通过  |
| `pending`  | 待复核 |
| `rejected` | 不通过 |

`keep/skip` 只表示单个关键帧决策，不能代替内容级三态。

成功响应：

```json
{
  "ok": true,
  "review": {
    "id": 15,
    "job_id": "20260724_164000_a1b2c3d4",
    "review_status": "pending",
    "labels": [
      "高运动强度",
      "多人目标"
    ],
    "note": "模型置信度较低，需要人工再次确认",
    "reviewed_by": {
      "id": 1,
      "username": "demo_user"
    },
    "created_at": "2026-07-24T09:10:00+00:00",
    "updated_at": "2026-07-24T09:10:00+00:00"
  },
  "report": {}
}
```

每次内容级审核应保存审核历史，不静默覆盖上一条数据库记录。

更新 `analysis_report.json` 时仍使用现有原子写入机制。

#### `GET /api/jobs/<job_id>/reviews`

返回任务的审核历史。

成功返回：

```json
{
  "ok": true,
  "current_review": {
    "id": 15,
    "review_status": "pending",
    "labels": [
      "高运动强度",
      "多人目标"
    ],
    "note": "模型置信度较低，需要人工再次确认",
    "created_at": "2026-07-24T09:10:00+00:00"
  },
  "reviews": [
    {
      "id": 15,
      "review_status": "pending",
      "labels": [
        "高运动强度",
        "多人目标"
      ],
      "note": "模型置信度较低，需要人工再次确认",
      "created_at": "2026-07-24T09:10:00+00:00"
    }
  ]
}
```

错误：

* 非法三态：`400 INVALID_REVIEW_STATUS`
* 报告尚未生成：`409 REPORT_NOT_READY`
* 越权访问：`403 JOB_ACCESS_DENIED`

---

### 7. Agent 调用接口

Agent 逻辑由 Agent/工作流模块实现，后端负责：

* 接收调用请求；
* 验证任务和用户权限；
* 保存调用状态；
* 保存工具轨迹摘要；
* 返回调用记录；
* 不伪造模型结果。

#### `POST /api/jobs/<job_id>/agent-calls`

为已生成 CV 报告的任务发起 Agent 调用。

请求：

```json
{
  "prompt_version": "v1",
  "force": false
}
```

成功进入队列返回 `202`：

```json
{
  "ok": true,
  "agent_call": {
    "id": 21,
    "job_id": "20260724_164000_a1b2c3d4",
    "status": "queued",
    "prompt_version": "v1",
    "created_at": "2026-07-24T09:20:00+00:00"
  }
}
```

调用前必须验证：

* 当前用户有权访问任务；
* `analysis_report.json` 已存在；
* CV 任务已达到允许调用 Agent 的状态；
* 同一任务没有不允许重复的活动调用。

错误：

* 分析报告不存在：`409 REPORT_NOT_READY`
* Agent 调用已在执行：`409 AGENT_ALREADY_RUNNING`
* Agent 服务不可用：`503 AGENT_SERVICE_UNAVAILABLE`

#### `GET /api/jobs/<job_id>/agent-calls`

返回某任务的 Agent 调用历史。

成功返回：

```json
{
  "ok": true,
  "agent_calls": [
    {
      "id": 21,
      "status": "completed",
      "model_name": "configured-model",
      "prompt_version": "v1",
      "duration_ms": 1820,
      "error_code": null,
      "error_message": null,
      "created_at": "2026-07-24T09:20:00+00:00",
      "completed_at": "2026-07-24T09:20:02+00:00"
    }
  ]
}
```

#### `GET /api/agent-calls/<agent_call_id>`

返回单次调用详情。

成功返回：

```json
{
  "ok": true,
  "agent_call": {
    "id": 21,
    "job_id": "20260724_164000_a1b2c3d4",
    "status": "completed",
    "model_name": "configured-model",
    "prompt_version": "v1",
    "input_summary": "读取真实 CV 报告，共 10 个关键帧",
    "output_summary": "生成摘要、标签、建议和待复核意见",
    "tool_trace": [
      {
        "tool": "visual_report_parser",
        "status": "completed",
        "duration_ms": 12
      },
      {
        "tool": "knowledge_retriever",
        "status": "completed",
        "duration_ms": 43
      },
      {
        "tool": "result_validator",
        "status": "completed",
        "duration_ms": 8
      }
    ],
    "references": [
      {
        "document_id": 3,
        "title": "媒体审核规范",
        "chunk_id": "chunk_012"
      }
    ],
    "result": {
      "summary": "基于真实视觉报告生成的摘要",
      "labels": [
        "高运动强度"
      ],
      "suggestions": [
        "建议人工确认低置信度关键帧"
      ],
      "review_status": "pending",
      "reason": "部分检测置信度低于审核阈值",
      "risk_flags": [
        "low_confidence"
      ]
    },
    "error_code": null,
    "error_message": null,
    "created_at": "2026-07-24T09:20:00+00:00",
    "completed_at": "2026-07-24T09:20:02+00:00"
  }
}
```

Agent 结果约束：

* 只能引用真实 CV 报告中的类别、置信度、时间戳和关键帧；
* 知识性结论必须提供知识文档或条目引用；
* 低置信度、无检索命中或结构化校验失败进入 `needs_review`；
* 模型调用失败必须保存 `failed` 和错误信息；
* 不得用规则生成内容冒充真实大模型调用。

#### Agent 调用状态

统一使用：

```text
queued
running
completed
failed
needs_review
```

含义：

| 状态             | 含义                     |
| -------------- | ---------------------- |
| `queued`       | 已记录，等待执行               |
| `running`      | 正在执行工具或模型调用            |
| `completed`    | 结构化输出和规则校验成功           |
| `failed`       | 调用、解析或服务执行失败           |
| `needs_review` | 有结果，但低置信度、无知识命中或需要人工确认 |

---

### 8. 知识文档查询草案

知识库的上传、切分和向量索引由 Agent/工作流模块负责。

后端第一阶段只冻结查询和日志字段，不在 Day 1 实现完整知识库管理后台。

计划接口：

```http
GET /api/knowledge-documents
GET /api/knowledge-documents/<document_id>
```

列表项至少包含：

```json
{
  "id": 3,
  "project_id": null,
  "title": "媒体审核规范",
  "source": "课程人工整理",
  "status": "ready",
  "chunk_count": 24,
  "embedding_model": "configured-embedding-model"
}
```

公开仓库、日志和响应中不得包含密钥或未授权文档全文。

---

### 9. 权限矩阵

| 接口                                  |    未登录 | 非所属用户 | 所属用户 |
| ----------------------------------- | -----: | ----: | ---: |
| `GET /api/health`                   |     允许 |    允许 |   允许 |
| `POST /api/auth/register`           |     允许 |    允许 |   允许 |
| `POST /api/auth/login`              |     允许 |    允许 |   允许 |
| `POST /api/auth/logout`             | 允许幂等退出 |    允许 |   允许 |
| `GET /api/projects`                 |    401 |   不适用 |   允许 |
| `GET /api/projects/<id>`            |    401 |   403 |   允许 |
| `POST /api/jobs`                    |    401 |   403 |   允许 |
| `GET /api/jobs/<job_id>`            |    401 |   403 |   允许 |
| `POST /api/jobs/<job_id>/analyze`   |    401 |   403 |   允许 |
| `PATCH /api/jobs/<job_id>/review`   |    401 |   403 |   允许 |
| `POST /api/jobs/<job_id>/rough-cut` |    401 |   403 |   允许 |
| `GET /api/jobs/<job_id>/report`     |    401 |   403 |   允许 |
| Agent 调用接口                          |    401 |   403 |   允许 |

管理员权限不作为 Day 2 最小闭环的必需功能。

---

### 10. 兼容与实施规则

Day 2 实现新增接口时必须遵守：

1. 不删除或改名现有任务接口。
2. 不把 Flask 迁移到 FastAPI。
3. 不删除 `job.json` 和 `analysis_report.json`。
4. 数据库仅增加业务归属、审核历史、Agent 日志和统计索引。
5. 内容级三态使用 `approved/pending/rejected`。
6. 关键帧决策继续使用 `keep/skip`。
7. `project_name` 向 `project_id` 的迁移必须保留明确兼容期。
8. 失败响应新增 `error_code` 时继续保留现有字符串 `error`。
9. 所有受保护接口必须验证任务所属项目，不能只验证 `job_id`。
10. API 字段变化必须同步修改测试、前端字段和本文档。
11. 尚未实现或未测试的接口不得在 README、日报或报告中写成已完成。
12. Agent 结果和测试结论不得编造。
