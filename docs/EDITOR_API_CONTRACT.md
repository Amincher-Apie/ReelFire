# ReelFire 剪辑预览聚合接口契约

## 1. 文档状态

- 契约版本：`1.0`
- 适用页面：首个 YOLO 分块完成后的增量剪辑预览页
- 数据方向：后端分块进度/最终结果 → 前端增量展示
- 当前实现：`GET /api/jobs/{job_id}/editor`
- 兼容原则：允许新增字段，不允许在同一主版本中删除字段或改变字段类型

## 2. 设计目标

剪辑预览页不读取 YOLO 原始采样帧来推导业务文案，也不在浏览器中生成 Agent 评论。首个分块完成后，后端从进度文件聚合暂定片段；全片完成后切换为 CV 最终报告和 Agent 最终输出。前端始终消费同一个聚合接口。

数据处理边界：

1. YOLO/CV 模块生成视频时长、关键帧、评分和候选片段。
2. Agent 模块依据可追溯的 CV 证据生成逐片段评论。
3. 后端聚合层按 `segment_id` 合并片段与评论。
4. 前端只负责播放、定位、标记和展示。

## 3. 获取剪辑预览数据

### 3.1 请求

```http
GET /api/jobs/{job_id}/editor
Accept: application/json
```

路径参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `job_id` | string | 是 | ReelFire 公共任务编号 |

任务必须至少完成一个 YOLO 分块。首块尚未完成时返回 `409`；首块完成后即使
`analysis_report.json` 尚未生成也返回运行中契约。

### 3.2 成功响应

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
    "duration": 687.4,
    "preview_status": "source"
  },
  "highlights": [
    {
      "id": "seg_001",
      "order": 1,
      "start": 14.2,
      "end": 21.8,
      "duration": 7.6,
      "score": 0.86,
      "source_keyframes": ["kf_001", "kf_003"],
      "source": "cv",
      "source_segment_ids": [],
      "review": "pass",
      "review_note": "",
      "agent_comment": "该区间的运动变化与场景变化评分较高，建议优先复核。",
      "agent_comment_status": "ready",
      "agent_review_status": "needs_review",
      "agent_evidence_refs": ["ev:segment:seg_001"]
    }
  ],
  "output": {
    "rough_cut_url": null,
    "contact_sheet_url": "/outputs/20260725_120000_1a2b3c4d/result/contact_sheet.jpg",
    "ratio": "16:9"
  },
  "live_analysis": {
    "ready": true,
    "final": true,
    "stage": "completed",
    "message": "视频分块分析和最终报告已完成",
    "percent": 100.0,
    "total_chunks": 12,
    "completed_chunks": 12,
    "chunks": []
  },
  "actions_enabled": true
}
```

运行中响应保持相同结构，但有以下差异：

- `job.status="running"`；
- `highlights[]` 是已完成分块的暂定片段，ID 采用
  `seg_c{chunk}_{local}`；
- `agent_comment_status="pending"`；
- `live_analysis.final=false`；
- `actions_enabled=false`，不得保存审核或生成粗剪。

### 3.3 字段定义

#### `job`

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `job_id` | string | 否 | 任务编号 |
| `project_name` | string | 否 | 项目名称 |
| `status` | string | 否 | `running`、`completed`；失败后若已有分块也可为 `failed` |
| `created_at` | string | 是 | ISO 8601 时间 |
| `completed_at` | string | 是 | ISO 8601 时间 |

#### `video`

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `url` | string | 否 | 同源视频访问地址，应支持 HTTP Range 请求 |
| `filename` | string | 否 | 展示用文件名 |
| `duration` | number | 否 | 秒，必须大于等于零 |
| `preview_status` | string | 否 | `source`、`transcoded` 或 `source_unverified`；HEVC 等编码会生成 H.264 预览代理 |

#### `highlights[]`

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 否 | 片段稳定标识，推荐 `seg_001` 格式 |
| `order` | integer | 否 | 从 1 开始的粗剪输出顺序；Editor 重排后随审核快照写回 |
| `start` | number | 否 | 起始秒数 |
| `end` | number | 否 | 结束秒数，必须大于 `start` |
| `duration` | number | 否 | `end - start`，由后端计算 |
| `score` | number | 是 | YOLO/CV 最终精彩度，范围 `0..1` |
| `source_keyframes` | string[] | 否 | 片段关联关键帧编号 |
| `source` | string | 否 | `cv`、`manual`、`merged` 或 `split` |
| `source_segment_ids` | string[] | 否 | 合并或拆分来源片段 ID |
| `review` | string | 否 | 用户决定：`""`、`pass`、`needs_review` 或 `reject` |
| `review_note` | string | 否 | 用户备注，最多 500 字符 |
| `agent_comment` | string | 是 | Agent 最终评论；前端不得自行生成替代文本 |
| `agent_comment_status` | string | 否 | `ready`、`pending` 或 `unavailable` |
| `agent_review_status` | string | 是 | Agent 逐片段结论：`pass`、`needs_review`、`reject`；评论未就绪时为 `null` |
| `agent_evidence_refs` | string[] | 否 | Agent 评论引用的证据编号 |

片段约束：

```text
0 <= start < end <= video.duration
duration = end - start
order 唯一
id 唯一
```

Agent 评论状态：

| 状态 | `agent_comment` | 前端行为 |
| --- | --- | --- |
| `ready` | 非空字符串 | 显示最终评论 |
| `pending` | `null` | 显示“Agent 评论尚未生成” |
| `unavailable` | `null` | 显示“Agent 评论不可用” |

#### `output`

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `rough_cut_url` | string | 是 | 已生成粗剪视频的同源地址 |
| `contact_sheet_url` | string | 是 | 关键帧联系表地址 |
| `ratio` | string | 是 | `16:9`、`9:16` 或 `1:1` |

#### `live_analysis`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ready` | boolean | 已至少有一个可供 Editor 消费的分块 |
| `final` | boolean | 是否已切换为最终报告片段 |
| `stage` | string | 当前分析阶段 |
| `message` | string | 可直接展示的进度说明 |
| `percent` | number | `0..100` 总进度 |
| `total_chunks` | integer | 预建立的分块总数 |
| `completed_chunks` | integer | 已完成 YOLO 分析的分块数 |
| `chunks[]` | object[] | 各逻辑分块的 ID、范围、状态和暂定片段 ID |

`actions_enabled` 是最终写操作闸门。只有其为 `true` 时，前端才能保存审核、
启动 Agent 或生成粗剪。

## 4. Agent 结果兼容规则

聚合层按以下优先级读取逐片段评论：

1. `agent_report.json.segment_comments[]` 中 `segment_id` 精确匹配的 `comment`。
2. `agent_report.json.suggestions[]` 中存在 `ev:segment:{segment_id}` 证据引用的 `action`。
3. 没有可验证的 Agent 最终结果时返回 `agent_comment = null` 和 `agent_comment_status = pending`。

后端不得把未经 Agent 输出验证的前端拼接文案标记为 `ready`。

`agent_calls` 是 Agent 执行日志，不是 Editor 评论的直接数据源。
`agent_calls.status = completed` 不代表 `agent_comment_status = ready`。
Editor 1.0 仍只按照上述 `agent_report.json.segment_comments[]` 和带可验证
证据的 `suggestions[]` 聚合评论。`agent_calls.result`、`result_path` 或
`inline_json$` 编码内容不得直接填入 `highlights[].agent_comment`。
`queued`、`running`、`completed`、`failed`、`needs_review` 也不得与
`ready`、`pending`、`unavailable` 建立一一映射。

建议的 Agent 原生输出：

```json
{
  "segment_comments": [
    {
      "segment_id": "seg_001",
      "comment": "该区间的运动变化与场景变化评分较高，建议优先复核。",
      "evidence_refs": ["ev:segment:seg_001", "ev:score:kf_001"]
    }
  ]
}
```

## 5. 错误响应

统一格式：

```json
{
  "ok": false,
  "error": "首个 YOLO 分块尚未完成，暂时不能打开剪辑预览"
}
```

| HTTP 状态 | 场景 |
| --- | --- |
| `400` | `job_id` 格式不合法或报告字段不合法 |
| `401` | 项目任务未登录，`AUTH_REQUIRED` |
| `403` | 当前用户无权访问项目任务，`JOB_ACCESS_DENIED` |
| `404` | 任务或源视频不存在 |
| `409` | 首个 YOLO 分块尚未完成 |
| `500` | 持久化数据损坏或服务内部错误 |

## 6. 前端消费约束

- 页面只请求聚合接口，不直接读取 `samples` 推导评论。
- `live_analysis.final=false` 时每约 1.6 秒重新请求聚合接口；仅追加新片段，
  不得重置用户已有排序或播放位置。
- 暂定片段切换为最终片段时，按时间区间重叠关系保留用户排序；未匹配的最终
  片段按后端顺序追加。
- `actions_enabled=false` 时禁用保存审核和生成粗剪，并明确说明仍在后台分析。
- 页面通过 Agent 调用接口创建并轮询真实生命周期：
  `queued → running → completed/needs_review/failed`。
- Agent 只能在 `live_analysis.final=true` 后启动。
- `needs_review` 携带 `model_generation_failed` 风险标记时，页面必须明确显示
  “规则降级结果”，不得显示为在线 Dify 成功。
- 时间显示可在前端格式化，但不得改变原始秒数。
- 时间轴片段位置以 `start / video.duration` 和 `(end - start) / video.duration` 计算。
- 源时间轴位置只由 `start/end` 决定；调整 `order` 不改变片段在源视频中的位置。
- 用户重排片段后，前端必须将 `order` 规范化为连续的 `1..N` 再保存审核。
- `agent_comment_status != ready` 时必须明确展示状态，不得伪造评论。
- 未知新增字段必须忽略，避免前端因兼容性扩展而失败。

## Editor Segment Schema 1.0（冻结）

`GET /api/jobs/{job_id}/editor` 保持 `contract_version="1.0"`，并额外返回
`segment_schema_version="1.0"`。`highlights[]`、PATCH 审核请求和审核快照
使用同一个 Segment Schema 1.0。

| 字段 | 类型 | 规则与默认值 |
| --- | --- | --- |
| `id` | `string` | 非空、去除首尾空白、数组内唯一、最多 100 字符；当前任务缺失时拒绝 |
| `order` | 正整数 | 输入值唯一；排序后规范为连续 `1..N` |
| `start` | `number` | 有限数字，`0 <= start < end`，布尔值无效 |
| `end` | `number` | 有限数字，`start < end <= video_duration` |
| `duration` | `number` | 忽略客户端值，由后端以 `round(end-start, 3)` 重算 |
| `score` | `number \| null` | 数字范围 `0..1`；`cv` 必须为数字，其他来源允许 `null` |
| `source_keyframes` | `string[]` | 默认 `[]`；元素去空白后非空且不重复 |
| `source` | `string` | `cv/manual/merged/split`；默认 `cv` |
| `source_segment_ids` | `string[]` | 默认 `[]`；元素非空、唯一，不能包含当前 `id` |
| `review` | `string` | `""/pass/needs_review/reject`；历史存储缺失默认 `pass`，全新 Segment 缺失默认 `""`，显式空串保持 |
| `review_note` | `string` | 默认 `""`；兼容输入 `null` 并转为空串，去除首尾空白，最多 500 字符 |

`cv/manual` 的 `source_segment_ids` 必须为空；`merged` 至少包含两个不同
来源 ID；`split` 必须且只能包含一个来源 ID。后端不按数组位置重写已有 ID。
服务端原 Segment 已有的 `peak_enemy_count`、`detected_classes`、
`thumbnail`、`chunk_id` 及未来新增的所有非冻结扩展证据字段在编辑保存时继续
保留。客户端只能控制冻结字段，未知字段一律忽略，不能新增或覆盖服务端证据。
持久化保留服务端扩展字段不改变 Editor 或 report-data 的公开白名单。

人工新增示例：

```json
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
}
```

合并示例：

```json
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
}
```

拆分示例：

```json
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
```

`Segment.review` 是用户片段级决定：空串表示未审核，`pass` 表示采用，
`needs_review` 表示待复核，`reject` 表示不采用。`agent_review_status` 是
Agent 建议；顶层 `status=approved|pending|rejected` 是整次审核快照状态。
三者相互独立，不得映射或混用。PATCH
保存完整规范化 Segment 到 `analysis_report.json`；同时提交顶层 `status`
时，审核快照保存相同数组。刷新后 Editor 从持久化报告恢复。

历史报告完全缺少新字段时读取为 `source="cv"`、`source_segment_ids=[]`、
`review="pass"`、`review_note=""`。当前 PATCH 按稳定 `id` 查找服务端现有
Segment；请求省略 `review/review_note/source/source_segment_ids` 时继承
服务端值，显式空串则清空。全新 Segment 缺少 review 时默认 `""`，不会自动
进入导出。服务端原 Segment 的所有非冻结扩展字段均按 `id` 深拷贝保留；客户端
未知字段一律忽略，不能新增或覆盖服务端证据，也不写入报告或审核快照。

PATCH 只从排序后第一个 pass 片段更新 `recommended_clip`；全为
空串/needs_review/reject 仍允许保存并保留旧推荐。非 legacy 粗剪仍要求最新
顶层状态为 approved，且只导出 pass 片段。其他状态不计入 `segment_count`
或 `segment_ids`。没有 pass 时不调用 FFmpeg，返回
`409 没有已通过的片段可以导出`。

本版本不声称实现前端自动保存、拖动边界 UI、撤销恢复、后台导出任务或
单片段导出接口。
