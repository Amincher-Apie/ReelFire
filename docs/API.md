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

- SQLite：用户、项目归属、项目型任务索引、人工审核历史和 Agent 调用日志；
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

- 上传接口要求登录；表单中没有 `project_id` 时，按 `project_name` 自动创建属于
  当前用户的 `active` 项目，并正常写入 SQLite `assets` 和 `jobs`；
- 表单中存在 `project_id` 时（包括空值），必须登录且该项目必须属于当前用户；空值或非正整数返回 `400 PROJECT_INPUT_INVALID`；
- 指定项目已归档时返回 `409 PROJECT_ARCHIVED`，不会创建工作目录、asset 或 job；
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

匿名用户只看到没有 SQLite 索引的旧文件任务。已登录用户看到自己的
SQLite 项目任务和旧文件任务，不会看到其他用户的项目任务。

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
order
start
end
duration（服务端重算）
score
source_keyframes
source
source_segment_ids
review
review_note
```

完整字段规则见“Editor Segment Schema 1.0（冻结）”。同 ID 片段会继承服务端
已有字段；客户端未知字段不会覆盖服务端扩展证据。只有排序后第一个
`review="pass"` 的片段更新 `recommended_clip`。

成功返回 `200` 和更新后的 `report`。

错误：

- 任务不存在：`404`；
- 报告尚未生成：`409`；
- 字段或片段边界错误：`400`。

项目型任务只要提交 `status`，对应 SQLite 审核记录就保存审核完成后的
完整、严格校验且按 `order` 排序的 `segments` 快照。请求提交
`segments` 时使用新值；未提交时快照来自当前分析报告。

### 5.7 `POST /api/jobs/<job_id>/rough-cut`

项目型任务读取最新一条 `approved` 审核记录中的完整 `segments` 快照，
仅筛选 `review="pass"` 的片段并按 `order` 拼接为一个 MP4。不存在审核、
最新审核不是 `approved` 或没有已通过片段时返回 `409`，且不会退回
`recommended_clip`；空字符串、`needs_review`、`reject` 均不导出。

请求体可省略。`output_ratio` 可覆盖输出比例；`start_time` 和
`end_time` 仅为 legacy 单片段兼容字段，项目型任务不会使用它们绕过
审核快照：

```text
start_time
end_time
output_ratio
```

只接受 `completed` 且已有报告的任务。

Legacy 任务优先导出报告中的非空 `segments`；没有片段时继续使用
`recommended_clip` 单片段路径。比例优先级依次为请求、
`recommended_clip`、任务设置和默认 `16:9`。

成功生成 MP4 后返回 `200`，并把输出路径写回任务与报告。响应和报告
输出同时包含 `segment_count`、`segment_ids` 和 `review_id`；legacy
任务的 `review_id` 为 `null`。FFmpeg 先写同目录临时文件，确认非空后
再原子替换，失败不会破坏已有粗剪。

错误：

- 状态、报告或审核门禁冲突：`409`；
- 参数错误：`400`；
- FFmpeg 不可用：`501`。

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

### 5.9 `GET /api/jobs/<job_id>/statistics`

只读聚合当前正式 `analysis_report.json`、SQLite 审核历史和 Agent 调用
历史。要求任务属于当前登录用户、状态为 `completed` 且报告存在。接口不写
统计文件，不修改报告、审核、Agent 正式文件或调用日志，也不会运行 CV、
Provider 或 FFmpeg。

成功响应：

```json
{
  "ok": true,
  "contract_version": "1.0",
  "statistics": {
    "job_id": "job_xxx",
    "timeline": {
      "video_duration_seconds": 120.0,
      "sampled_frame_count": 24,
      "keyframe_count": 10
    },
    "detections": {
      "count_semantics": "sampled_detection_occurrences",
      "total_occurrences": 12,
      "confidence_observation_count": 12,
      "confidence": {
        "minimum": 0.61,
        "maximum": 0.94,
        "average": 0.81
      },
      "categories": [
        {
          "name": "person",
          "count": 8,
          "confidence_observation_count": 8,
          "confidence": {
            "minimum": 0.65,
            "maximum": 0.94,
            "average": 0.84
          }
        }
      ]
    },
    "segments": {
      "count": 3,
      "sum_duration_seconds": 35.0,
      "covered_duration_seconds": 31.5,
      "coverage_ratio": 0.2625
    },
    "reviews": {
      "history_count": 4,
      "status_counts": {
        "pending": 2,
        "approved": 1,
        "rejected": 1
      },
      "latest_status": "approved"
    },
    "agent_calls": {
      "history_count": 3,
      "status_counts": {
        "queued": 0,
        "running": 0,
        "completed": 1,
        "needs_review": 1,
        "failed": 1
      },
      "latest_status": "completed"
    }
  }
}
```

统计口径：

- `sampled_frame_count` 是真实 `samples[]` 长度；检测来自
  `samples[].objects[]`，类别字段为 `class`，置信度字段为
  `confidence`。
- `total_occurrences` 是所有采样帧中检测对象出现次数。同一对象跨五帧出现
  计五次，不能解释为唯一目标数、人数或事件数。
- 非对象检测项不计数；检测对象缺少非空类别时仍计入总出现次数，但不进入
  `categories`。类别按 count 降序、同 count 时按 name 升序。
- confidence 只接受非 bool、有限且位于 `[0, 1]` 的数字。没有合法观察值时
  minimum、maximum、average 均为 `null`，不会用 0 伪造平均值。
- `sum_duration_seconds` 简单累加每个合法片段的 `end-start`，允许重复计算
  重叠；`covered_duration_seconds` 合并重叠和相邻区间后计算真实时间轴
  覆盖。视频时长为 0 或缺失时 `coverage_ratio` 为 `null`。
- 片段统计只读取当前 CV 报告，不使用审核快照。reviews 固定返回三态计数，
  agent_calls 固定返回五态计数；无历史时计数为 0、latest_status 为
  `null`。
- samples、keyframes、segments 或历史为空是正常的 `200` 零值响应。
- 响应不包含绝对路径、数据库内部 Job ID、owner/reviewer/requested_by、
  Agent 完整 result 或审核备注历史。

错误：

- 未登录：`401 AUTH_REQUIRED`；
- 非任务所有者：`403 JOB_ACCESS_DENIED`；
- 任务未 completed 或报告不存在：`409 REPORT_NOT_READY`；
- 报告 JSON 损坏或统计结构包含非法数据：复用现有 `500` 损坏数据响应。

### 5.10 `GET /api/jobs/<job_id>/report-data`

该只读接口为 HTML 报告、PDF 报告和审核包提供统一的 JSON 数据源；接口
本身不生成 HTML、PDF 或 ZIP，也不会运行 CV、Agent 或 FFmpeg。调用者
必须登录且拥有任务，任务必须为 `completed`，并且正式
`analysis_report.json` 必须存在。

成功响应的一级数据块固定如下：

```json
{
  "ok": true,
  "contract_version": "1.0",
  "report_data": {
    "job": {
      "job_id": "20260726_120000_1a2b3c4d",
      "status": "completed",
      "created_at": "2026-07-26T12:00:00",
      "completed_at": "2026-07-26T12:03:10"
    },
    "video": {
      "filename": "demo.mp4",
      "duration_seconds": 120.0
    },
    "statistics": {
      "job_id": "20260726_120000_1a2b3c4d",
      "timeline": {},
      "detections": {},
      "segments": {},
      "reviews": {},
      "agent_calls": {}
    },
    "cv": {
      "summary": {
        "sample_interval_seconds": 0.5,
        "sampled_frame_count": 24,
        "keyframe_count": 10,
        "detection_occurrence_count": 12,
        "segment_count": 3
      },
      "segments": []
    },
    "agent": {
      "availability": "unavailable",
      "status": null,
      "summary": null,
      "segment_comments": [],
      "knowledge_refs": [],
      "calls": {
        "history_count": 0,
        "status_counts": {
          "queued": 0,
          "running": 0,
          "completed": 0,
          "needs_review": 0,
          "failed": 0
        },
        "latest_status": null
      }
    },
    "review": {
      "latest": null,
      "history_count": 0,
      "status_counts": {
        "pending": 0,
        "approved": 0,
        "rejected": 0
      }
    },
    "rough_cut": {
      "available": false,
      "filename": null,
      "download_url": null
    }
  }
}
```

数据来源与边界：

- `job` 只含文件任务的公共编号、状态和时间；`video.filename` 为安全文件
  basename，时长与 statistics 接口使用相同规则。
- `statistics` 直接调用 `build_job_statistics()`，因此同一任务与
  `/statistics` 的结果完全一致，不维护第二套统计口径。
- `cv.segments` 只来自当前正式 CV 报告。最新审核快照不会覆盖原始 CV
  片段；Agent 评论也不会改写 CV 数据。
- `review.latest` 使用 SQLite 审核历史既有的最新优先顺序，仅公开状态、
  标签、备注、片段/关键帧快照和时间。历史只公开总数与固定三态计数。
- `agent.segment_comments` 和知识引用只读取任务根目录中的正式
  `agent_report.json`，绝不从 `agent_calls.result` 构造。正式文件不存在时
  `availability=unavailable` 并返回空数组；文件损坏、Job 不匹配、结构
  无效或公开内容包含私密路径/非法 JSON 值时 `availability=invalid`，但
  整个接口仍返回 `200`，且调用历史摘要继续保留。`calls` 仅为 SQLite
  调用历史的固定五态摘要。
- `rough_cut.available` 只有在相对元数据指向任务目录内真实存在的文件时
  才为 `true`。`download_url` 使用现有受任务权限保护的 `/outputs/...`
  路由；仅有元数据但文件缺失时返回不可用零值。
- 审核、Agent 或粗剪为空属于正常业务状态，接口仍返回 `200`。
- 响应使用公开字段白名单，不返回绝对路径、SQLite 内部 ID、用户 ID、
  Provider 地址、API Key、Authorization、Token 或完整 Agent 调用结果。

错误语义：

- 未登录：`401 AUTH_REQUIRED`；
- 非任务所有者：`403 JOB_ACCESS_DENIED`；
- 任务未完成或正式 CV 报告缺失：`409 REPORT_NOT_READY`；
- CV 报告损坏、统计字段无效或聚合数据无法安全公开：复用现有
  `500` 损坏数据响应，不返回本机路径或堆栈。

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

首个 YOLO 分块完成后页面即可打开。页面负责播放、时间轴定位、增量精彩片段
列表和 Agent 评论状态展示；YOLO 继续在后台运行，页面不在浏览器中运行模型或
生成 Agent 评论。

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
  "segment_schema_version": "1.0",
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
      "source": "cv",
      "source_segment_ids": [],
      "review": "pass",
      "review_note": "",
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

Agent 新版逐片段对象在保留上述兼容字段的基础上增加：

```text
action_recommendation
explanation.highlight_type
explanation.trigger_rule
explanation.time_range
explanation.detections[]
explanation.keyframe_refs[]
explanation.detection_box_refs[]
boundary_suggestion
```

完整语义见 `docs/AGENT_FEEDBACK_CONTRACT.md`。聚合接口可以原样透传这些字段，
不得把 `detection_count` 改写成连续帧数，也不得由前端根据文字反推证据。

### 6.2.1 反馈接口待后端实现的冻结语义

Agent 已冻结 `agent/schemas/agent_feedback.schema.json`，建议后端后续提供：

```text
POST /api/jobs/{job_id}/segments/{segment_id}/feedback
GET  /api/jobs/{job_id}/feedback
GET  /api/statistics/agent-feedback
```

这些路由当前尚未在本分支实现，不能作为已上线接口调用。后端实现时必须保留
`decision/rejection_reason/original_boundary/final_boundary/original_order/
final_order/reexported/recorded_at` 的冻结含义。

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
- Legacy 单片段兼容路径的 `/rough-cut` 可直接使用；项目型任务不能用它
  绕过最新 `approved` 审核快照。

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
- 用于多片段审核、排序和 pass-only 导出。

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

## 9. 已实现：SQLite 项目生命周期与上传任务归属

已实现接口：

```http
POST /api/projects
GET  /api/projects
GET  /api/projects/<project_id>
PATCH /api/projects/<project_id>
GET  /api/projects/<project_id>/jobs
DELETE /api/projects/<project_id>
```

所有项目接口均要求登录，并且只能访问当前用户自己的项目。`owner_id` 只来自
当前 Session，客户端不得指定或修改；不存在的项目返回 404，其他用户的项目
返回 403。

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

`GET /api/projects/<project_id>` 返回项目基础字段，以及直接从 SQLite `jobs`
统计的 `job_count` 和固定状态键 `jobs_by_status`：

```json
{
  "ok": true,
  "project": {
    "id": 1,
    "name": "CS2 教学素材",
    "description": "课程演示项目",
    "game_type": "cs2",
    "status": "active",
    "created_at": "2026-07-27T12:00:00+00:00",
    "updated_at": "2026-07-27T12:00:00+00:00",
    "job_count": 2,
    "jobs_by_status": {
      "created": 0,
      "queued": 0,
      "running": 0,
      "completed": 2,
      "failed": 0
    }
  }
}
```

`PATCH /api/projects/<project_id>` 只允许提交 `name/description/game_type/status`：
`name` 去空白后长度为 1–100；`description` 为字符串或 null、最多 1000；
`game_type` 为字符串或 null、最多 50；`status` 只支持 `active/archived`。
请求必须是非空 JSON 对象，未知字段返回 400。更新使用 SQLite
`BEGIN IMMEDIATE` 短事务并刷新 `updated_at`，不会修改项目内任务。

`archived` 只阻止向该项目新增上传，`POST /api/jobs` 返回
`409 PROJECT_ARCHIVED`；历史任务仍可读取、审核和下载。PATCH 恢复为
`active` 后可继续上传。自动创建项目仍默认为 `active`。

`GET /api/projects/<project_id>/jobs` 只查询 SQLite，不扫描 outputs。支持：

```text
status = created | queued | running | completed | failed（可选）
limit  = 1..100（默认 50）
offset = >= 0（默认 0）
```

响应包含 `jobs/total/limit/offset`。任务摘要公开 `job_id/status`、生命周期
时间、错误码/错误信息，以及由 SQLite 路径是否非空计算的
`report_available/rough_cut_available`；不公开内部存储路径。

`DELETE /api/projects/<project_id>` 只允许删除没有任何 jobs 的项目。服务在
`BEGIN IMMEDIATE` 事务内再次统计 jobs，非空返回
`409 PROJECT_NOT_EMPTY` 并提示先逐个删除任务。空项目删除不扫描或删除任意
文件目录，不删除用户，也不影响其他项目。该接口不会级联批量删除项目任务，
因此不能绕过 JobService 的 tombstone 任务删除流程；当前未实现批量删除项目
任务。

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
| 409 | `PROJECT_ARCHIVED` | 归档项目禁止新增任务 |
| 409 | `PROJECT_NOT_EMPTY` | 项目仍包含任务，必须先逐个删除任务 |
| 409 | `PROJECT_STATE_CONFLICT` | 项目状态并发变化，需要刷新重试 |

旧文件型任务可能没有 SQLite `jobs` 索引，并继续保留兼容访问。

---

## 10. 已实现：任务归属权限

每个具体 `job_id` 先查询 SQLite `jobs.public_job_id`。存在索引时，
必须登录并通过对应 `projects.owner_id` 校验；没有索引时视为旧文件
任务，保持原有兼容行为。不能依据 `job.json` 中的名称或项目字段判断
所有权。

```text
当前用户
→ SQLite jobs 记录
→ 所属 project
→ project.owner_id
```

不能只根据公开 `job_id` 判断权限。

权限错误：

| 状态 | `error_code` | 场景 |
| ---: | --- | --- |
| 401 | `AUTH_REQUIRED` | 未登录访问 SQLite 项目任务 |
| 403 | `JOB_ACCESS_DENIED` | 无权访问任务 |

统一受保护入口包括：

```text
GET    /api/jobs/<job_id>
DELETE /api/jobs/<job_id>
POST   /api/jobs/<job_id>/analyze
PATCH  /api/jobs/<job_id>/review
POST   /api/jobs/<job_id>/rough-cut
GET    /api/jobs/<job_id>/report
GET    /api/jobs/<job_id>/editor
GET    /jobs/<job_id>/editor
GET    /outputs/<job_id>/<path:filename>
```

权限检查发生在排队、删除、审核文件写回、粗剪生成和文件发送之前。
编辑页聚合接口成功响应继续遵守 `EDITOR_API_CONTRACT` 1.0。

---

## 11. 已实现：内容级三态审核

固定三态：

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
- 内容级三态保存到 SQLite `reviews.status`；
- `reviews.job_row_id` 指向内部 `jobs.id`，API 路径仍使用公开 `job_id`；
- 每次携带 `status` 的审核都新增历史记录，不覆盖旧记录；
- 每条带 `status` 的项目型审核都把审核完成后的完整片段快照序列化到
  `segments_json`；请求未提交片段时从当前报告严格校验后保存；
- 提交的关键帧序列化到 `keyframes_json`，未提交时保存 `null`；
- `PATCH /review` 继续更新 `analysis_report.json`，成功响应中的
  `report` 字段保持不变；
- Agent 不得更新或覆盖人工 `reviews` 记录。

查询接口：

```http
GET /api/jobs/<job_id>/reviews
GET /api/jobs/<job_id>/review/latest
```

历史按最新记录优先返回；没有记录时分别返回空数组或 `review: null`。
两个接口使用与任务详情相同的归属权限。

写回接口：

```http
PATCH /api/jobs/<job_id>/review
```

除原有 `keyframes`、`segments` 和 `recommended_clip` 外，可提交
`status`、`labels` 和 `note`。只有出现 `status` 时才新增 SQLite
审核历史。

Legacy 文件任务不携带 `status` 时继续更新文件报告；携带 `status`
时因没有可关联的内部任务行，返回
`409 REVIEW_PERSISTENCE_UNAVAILABLE`，并且不修改报告。

输入错误返回 `400 REVIEW_INPUT_INVALID`。项目任务仍使用
`401 AUTH_REQUIRED` 和 `403 JOB_ACCESS_DENIED`。

---

## 12. 已实现：Agent 执行与调用日志

后端已把调用日志与真实 Agent 工作流连接起来。执行器读取任务目录中的
`analysis_report.json`，依次运行报告解析、知识检索、建议生成和规则校验，
并分别持久化 `agent_report.json`、`agent_trace.json` 与 SQLite 生命周期日志。

接口：

```http
POST /api/jobs/<job_id>/agent-calls
GET  /api/jobs/<job_id>/agent-calls
GET  /api/agent-calls/<agent_call_id>
```

`POST` 要求任务属于当前用户、任务状态为 `completed` 且
`analysis_report.json` 已存在。成功返回 `202` 和一条真实 `queued`
日志，同时提交后台 Agent 执行。`force` 是兼容字段，不能绕过活动调用保护。

状态机：

```text
queued → running
queued → failed
running → completed
running → failed
running → needs_review
```

终态不能再次运行或互相覆盖。`services.agent_execution_service` 负责调用
Agent；生命周期只能通过 `services.agent_call_service` 的状态更新函数落库。

历史接口按调用 `id` 降序返回摘要；详情接口联表取得公开 `job_id`，
不会返回 `agent_calls.job_row_id` 或 SQLite `jobs.id`。

主要错误：

| HTTP | `error_code` | 场景 |
| ---: | --- | --- |
| 400 | `AGENT_CALL_INPUT_INVALID` | 创建输入或调用 ID 不合法 |
| 401 | `AUTH_REQUIRED` | 未登录访问项目任务 |
| 403 | `JOB_ACCESS_DENIED` | 当前用户不是任务所有者 |
| 404 | `AGENT_CALL_NOT_FOUND` | 调用记录不存在 |
| 409 | `AGENT_CALL_PERSISTENCE_UNAVAILABLE` | Legacy 任务无法持久化日志 |
| 409 | `AGENT_ALREADY_RUNNING` | 已存在活动调用 |
| 409 | `REPORT_NOT_READY` | 任务或报告尚未就绪 |
| 409 | `AGENT_CALL_STATE_CONFLICT` | 状态流转非法 |
| 503 | `AGENT_EXECUTION_UNAVAILABLE` | 后台线程池关闭或无法接受新调用 |

Legacy 任务的创建接口返回持久化不可用，历史接口返回空数组，不创建
隐式 SQLite 任务，也不在文件系统伪造日志。

现有表没有 `result_json`。服务使用
`result_path` 保存带 `inline_json$` 前缀的 JSON 兼容编码，并在 API
读取时恢复为 `result` 对象；API 不暴露该内部编码。完整结果同时保存在
任务目录的 `agent_report.json`，Editor 只读取该经过规则校验的文件。

`failed` 必须保存错误码和错误信息。`needs_review` 是 Agent 建议状态，
不等于人工 `reviews.pending`。Agent 服务不写入 `reviews`，也不修改
`analysis_report.json`；只原子写入独立的 `agent_report.json` 和
`agent_trace.json`。

模型提供方失败时，`agent_report.json.errors[]` 保留兼容字段
`code/message/stage/retryable`，并可增加 `provider_code` 与
`attempt_count`。`code=model_generation_failed` 供现有 Editor 判断降级，
`provider_code` 用于区分 Dify 的认证、限流、网络、超时、服务端和契约错误。
映射到 `agent_calls.result.risk_flags` 时两类错误码都会保留并去重；任何日志和
API 响应都不得包含 API Key、Authorization 请求头或本机绝对路径。

每次后台调用先写入任务目录下调用专属的
`.agent_runs/<agent_call_id>-<random>/`。只有状态映射为 `completed` 或
`needs_review`，且报告和轨迹均为非空 JSON 对象、`job_id` 匹配时，才把两份
文件作为一组发布到任务目录。新运行失败、产物无效、第二份文件发布失败或
数据库终态写入失败时，服务恢复完整的上一组正式文件；原先没有正式文件时
删除本次新文件。staging 与备份文件始终清理。

应用启动会在一个事务中把遗留的 `queued`、`running` 调用改为 `failed`，
错误码为 `AGENT_PROCESS_INTERRUPTED`，不会自动重跑。调度提交失败时，新建
记录会改为 `failed`，接口返回 `503 AGENT_EXECUTION_UNAVAILABLE`，不会留下
永久 `queued`。数据库和 API 中的运行错误会隐藏绝对路径、凭据、请求头与
堆栈；完整异常仅进入服务日志。

`agent_calls.result` 只是调用日志的一部分，不作为 Editor 评论的直接来源：
Editor 评论仍只来自 `agent_report.json.segment_comments[]` 或带可验证
证据的 `suggestions[]`。调用状态（包括 `completed`）不得直接映射为
`agent_comment_status`，日志中的 `result`、`result_path` 或
`inline_json$` 内容也不得直接作为 Editor 评论。

`highlights[].agent_review_status` 独立透传逐片段的
`pass/needs_review/reject`，不得与评论可用状态混淆。日志不得保存 API Key、
完整系统 Prompt 或未经脱敏的原始输入。SQLite 只作为单机调用日志，不是
生产级消息队列。

---

## 13. 编辑结果写回与多片段导出

当前已实现：

- 修改片段边界；
- 修改片段顺序；
- 内容级三态审核；
- 刷新和历史重开后恢复编辑结果；
- 按已审核片段生成多片段粗剪；

后续能力包括：

- 输出统计 JSON；
- 导出审核包和 HTML/PDF 报告。

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

---

## 16. 流式分块分析与进度契约

任务创建参数在原有字段之外支持：

| 字段 | 默认值 | 范围 | 说明 |
|---|---:|---:|---|
| `chunk_duration` | `60.0` | 5–1800 秒 | 逻辑分析分块长度，不生成物理切片文件 |
| `keyframes_per_chunk` | `4` | 1–24 | 每个分块最多保留的审核关键帧 |
| `yolo_batch_size` | `8` | 1–64 | 单次 YOLO 推理的采样帧微批大小 |

`GET /api/jobs/{job_id}` 的 `job.progress` 返回：

```json
{
  "stage": "detecting",
  "message": "已完成 2/5 个分析分块",
  "percent": 39.0,
  "total_chunks": 5,
  "completed_chunks": 2,
  "processed_frames": 120,
  "total_frames": 300,
  "current_chunk": {
    "id": "chunk_0003",
    "index": 3,
    "start": 120.0,
    "end": 180.0
  },
  "video": {
    "duration": 300.0,
    "width": 1920,
    "height": 1080,
    "fps": 30.0
  },
  "chunks": [
    {
      "id": "chunk_0001",
      "index": 1,
      "start": 0.0,
      "end": 60.0,
      "status": "completed",
      "provisional_segments": []
    },
    {
      "id": "chunk_0003",
      "index": 3,
      "start": 120.0,
      "end": 180.0,
      "status": "running",
      "provisional_segments": []
    }
  ]
}
```

`stage` 依次为：

```text
queued → initializing → sampling → detecting → finalizing → completed
                                                    └──────→ failed
```

读取视频元数据后立即预建立完整逻辑分块队列，`chunks[].status` 按
`queued → running → completed` 变化。这里不预写物理视频文件，避免首帧结果
被全量切片 I/O 延迟。

每个已完成分块包含时间范围、采样数量、已落盘关键帧和暂定片段。暂定片段带
`provisional=true`，仅用于分析过程反馈；最终 `analysis_report.json` 中的
`segments[]` 仍由全部采样元数据统一归并，且 `provisional=false`。

进度单独原子写入 `analysis_progress.json`。最终报告继续写入
`analysis_report.json`。Editor 在首块完成后读取中间进度并实时追加暂定片段；
Agent、审核保存与粗剪仍等待最终报告。

最终报告新增：

- `analysis_mode="streaming_chunks"`；
- `chunk_duration`；
- `analysis_chunks[]`；
- 每个关键帧的 `chunk_id` 与 `chunk_index`。

视频帧按分块保存在内存中；已完成分块释放帧数组，只保留检测元数据和落盘
关键帧。因此帧图像内存上限由单个分块和 YOLO 微批大小决定，不再随整段视频
时长线性增长。

## Editor Segment Schema 1.0（冻结）

Editor、人工审核快照和项目粗剪使用同一 Schema。Editor GET 继续返回
`contract_version="1.0"`，并新增 `segment_schema_version="1.0"`。

| 字段 | 类型 | 校验、默认值与规范化 |
| --- | --- | --- |
| `id` | `string` | 去空白后非空、唯一、最多 100 字符；非 legacy 不可缺失 |
| `order` | 正整数 | 输入唯一；按值排序后重编号为连续 `1..N` |
| `start/end` | `number` | 有限且 `0 <= start < end <= video_duration`，布尔值无效 |
| `duration` | `number` | 后端忽略客户端值并设置 `round(end-start, 3)` |
| `score` | `number \| null` | 数字范围 `0..1`；cv 必须有数字，其他来源可为 null |
| `source_keyframes` | `string[]` | 默认 `[]`；元素去空白、非空、唯一 |
| `source` | `string` | `cv/manual/merged/split`；默认 `cv` |
| `source_segment_ids` | `string[]` | 默认 `[]`；非空、唯一，不含自身 ID |
| `review` | `string` | `""/pass/needs_review/reject`；历史存储缺失默认 `pass`，全新 Segment 缺失默认 `""`，显式空串保持 |
| `review_note` | `string` | 默认 `""`；兼容 null 并转空串，去首尾空白，最多 500 字符 |

来源规则：cv/manual 不得有来源 ID；merged 至少两个；split 恰好一个。
服务端原 Segment 已有的所有非冻结扩展证据字段在编辑保存时继续保留，包括未来
新增字段；客户端只能控制冻结字段，未知字段一律忽略，不能新增或覆盖服务端证据。
这些服务端扩展字段的持久化保留不扩大 Editor 或 report-data 的公开白名单。

人工新增、合并、拆分示例：

```json
[
  {
    "id": "seg_manual_8f3a",
    "order": 2,
    "start": 30.0,
    "end": 42.0,
    "duration": 12.0,
    "score": null,
    "source_keyframes": [],
    "source": "manual",
    "source_segment_ids": [],
    "review": "pass",
    "review_note": "自动检测遗漏，人工补充"
  },
  {
    "id": "seg_merged_01",
    "order": 3,
    "start": 50.0,
    "end": 72.0,
    "duration": 22.0,
    "score": 0.91,
    "source_keyframes": ["kf_010", "kf_012"],
    "source": "merged",
    "source_segment_ids": ["seg_004", "seg_005"],
    "review": "pass",
    "review_note": "相邻交火合并"
  },
  {
    "id": "seg_split_01a",
    "order": 4,
    "start": 80.0,
    "end": 89.0,
    "duration": 9.0,
    "score": 0.72,
    "source_keyframes": ["kf_020"],
    "source": "split",
    "source_segment_ids": ["seg_006"],
    "review": "needs_review",
    "review_note": ""
  }
]
```

PATCH `/api/jobs/{job_id}/review` 顶层仍只接受 `segments/status/labels/note/
keyframes/recommended_clip`。片段 `review/review_note` 不得放到顶层。规范化
数组写回报告；带顶层 status 时也写入审核快照。

片段 `review` 是用户人工决定；`agent_review_status` 是 Agent 建议；顶层
`status=approved|pending|rejected` 是整次审核快照状态，三者相互独立且不得
映射。片段空 review 表示未审核，pass 表示采用，needs_review 表示待复核，
reject 表示不采用。

历史存储缺失字段默认 `source="cv"`、`source_segment_ids=[]`、
`review="pass"`、`review_note=""`。PATCH 按 `id` 从服务端原 Segment 继承
请求省略的 review/review_note/source/source_segment_ids；显式空串不继承。
全新 Segment 缺少 review 时默认 `""`，不会自动进入导出。服务端原 Segment
的所有非冻结扩展字段均按 `id` 深拷贝保留；客户端未知字段一律忽略，不能新增或
覆盖服务端证据，也不进入报告或审核快照。

全空串/needs_review/reject 合法保存，且不覆盖已有 `recommended_clip`。
非 legacy 粗剪只向 FFmpeg 传 pass 片段，输出元数据也只包含 pass。
最新审核非 approved 仍返回 409；approved 但无 pass 时不调用 FFmpeg，
返回 `409 没有已通过的片段可以导出`。

本节不表示已实现前端自动保存、拖动边界、撤销恢复、后台导出、任务取消/重试
或单片段导出接口。

## Job 文件与 SQLite 索引一致性

ReelFire 保持兼容的双层持久化职责：

- `job.json` 保存任务完整运行信息，是文件任务生命周期的主要持久化记录；
- SQLite `jobs` 保存账户权限、项目查询和重要生命周期索引；
- SQLite 镜像 `status/report_json_path/rough_cut_path/error_code/
  error_message/started_at/completed_at/updated_at`，但不取代完整
  `job.json`。

后台分析线程不使用 Flask `g` 或请求连接。`JobIndexRepository` 根据配置的
数据库文件为每次操作创建短生命周期 SQLite 连接，启用外键、5 秒 busy
timeout 和 WAL，并在明确事务结束后关闭连接。索引路径统一相对于
`OUTPUTS_DIR` 的父目录，使用 POSIX `/`，拒绝存储根目录外路径和不存在的
报告/粗剪文件。

应用启动顺序为：完成数据库迁移和用户导入，按 SQLite 状态恢复或清理上次删除
遗留的隐藏 tombstone，对账已存在的 SQLite 项目任务，再把重启时遗留的
queued/running 任务同步标记为 failed，最后创建后台 Analysis 与 Agent 执行
服务。对账只处理已有 SQLite `jobs` 行：以对应 `job.json` 修复生命周期字段，
按真实文件补齐或清空报告和粗剪路径。SQLite 行对应的工作目录或 `job.json`
缺失时保留账户和项目数据，将任务索引标记为 failed，并记录
`JOB_STORAGE_MISSING`。没有 `project_id` 的显式 legacy 文件任务不会被猜测
owner、自动创建项目或自动认领；具有合法正整数 `project_id` 的项目型任务若
缺少 SQLite `jobs` 行，则属于持久化一致性错误，不会静默降级为 legacy。

任务状态、报告路径等双写采用文件原子替换加 SQLite 短事务。项目型任务的
SQLite UPDATE 必须恰好匹配一行；匹配零行会恢复先写入的 `job.json` 或报告
文件，并抛出明确的一致性错误。分析报告成功写入后才设置
`report_json_path`；粗剪先把 staging 文件原子发布到正式路径，再更新报告和
`job.json`/SQLite，任一步失败都会恢复旧报告、旧任务元数据和旧正式输出。
正式状态全部提交后，旧输出备份清理失败只记录警告并保留待清理文件，不会把
成功响应改为普通 500。Segment Schema 1.0 的 pass-only 导出规则不变。

删除不是跨 SQLite/文件系统的真正 ACID 事务，而是：

1. 权限、状态和路径全部校验通过后，把 `outputs/<job_id>` 原子重命名为
   `OUTPUTS_DIR` 内严格命名的隐藏 tombstone；
2. SQLite 事务删除 `jobs`，外键级联删除 `reviews` 和 `agent_calls`，并仅在
   没有其他任务引用时删除 `asset`；`project` 永不随任务删除；
3. 数据库失败时回滚并把 tombstone 恢复为正常任务目录；
4. 数据库提交后再物理删除 tombstone；最终清理失败时不重新暴露正常任务
   路径，返回 `JOB_CLEANUP_PENDING`，下次应用启动进行数据库感知处理。

启动时不能仅凭 tombstone 名称认定数据库删除已提交。严格名称中解析出的
`job_id` 按以下矩阵处理：

- SQLite `jobs` 行不存在且正常目录不存在：数据库删除已提交，可重试删除
  tombstone；失败则保留并记录清理警告，不重建数据库行；
- SQLite 行存在且正常目录不存在：删除可能在提交前中断，使用原子重命名把
  tombstone 恢复为正常目录，再由对账读取 `job.json`；
- SQLite 行与正常目录同时存在，或 SQLite 行不存在但正常目录存在：状态不
  明确，为避免数据丢失保留 tombstone 并记录一致性警告，不盲删、不自动创建
  SQLite 行。

项目型任务删除时，SQLite 删除事务返回“未找到 jobs 行”同样属于一致性错误：
tombstone 必须恢复为正常目录，不能物理删除任务文件。没有 `project_id` 的
legacy 文件任务继续允许没有 SQLite 行。

因此该方案应描述为“SQLite 事务 + 文件原子重命名 + 补偿恢复 + 启动清理”，
不是文件系统与 SQLite 之间的真正 ACID 事务。任务取消、自动重试和后台导出
任务仍未实现。
