# ReelFire 剪辑预览聚合接口契约

## 1. 文档状态

- 契约版本：`1.0`
- 适用页面：视频分析完成后的剪辑预览页
- 数据方向：后端最终结果 → 前端只读展示
- 当前实现：`GET /api/jobs/{job_id}/editor`
- 兼容原则：允许新增字段，不允许在同一主版本中删除字段或改变字段类型

## 2. 设计目标

剪辑预览页不读取 YOLO 原始采样帧来推导业务文案，也不在浏览器中生成 Agent 评论。后端负责合并任务信息、CV 分析报告和 Agent 最终输出，前端只消费一个稳定的聚合结果。

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

任务必须已经生成 `analysis_report.json`。未完成或报告不存在时返回 `409`。

### 3.2 成功响应

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
      "source_keyframes": ["kf_001", "kf_003"],
      "agent_comment": "该区间的运动变化与场景变化评分较高，建议优先复核。",
      "agent_comment_status": "ready",
      "agent_evidence_refs": ["ev:segment:seg_001"]
    }
  ],
  "output": {
    "rough_cut_url": null,
    "contact_sheet_url": "/outputs/20260725_120000_1a2b3c4d/result/contact_sheet.jpg",
    "ratio": "16:9"
  }
}
```

### 3.3 字段定义

#### `job`

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `job_id` | string | 否 | 任务编号 |
| `project_name` | string | 否 | 项目名称 |
| `status` | string | 否 | 当前必须为 `completed` |
| `created_at` | string | 是 | ISO 8601 时间 |
| `completed_at` | string | 是 | ISO 8601 时间 |

#### `video`

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `url` | string | 否 | 同源视频访问地址，应支持 HTTP Range 请求 |
| `filename` | string | 否 | 展示用文件名 |
| `duration` | number | 否 | 秒，必须大于等于零 |

#### `highlights[]`

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 否 | 片段稳定标识，推荐 `seg_001` 格式 |
| `order` | integer | 否 | 从 1 开始的展示顺序 |
| `start` | number | 否 | 起始秒数 |
| `end` | number | 否 | 结束秒数，必须大于 `start` |
| `duration` | number | 否 | `end - start`，由后端计算 |
| `score` | number | 是 | YOLO/CV 最终精彩度，范围 `0..1` |
| `source_keyframes` | string[] | 否 | 片段关联关键帧编号 |
| `agent_comment` | string | 是 | Agent 最终评论；前端不得自行生成替代文本 |
| `agent_comment_status` | string | 否 | `ready`、`pending` 或 `unavailable` |
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
  "error": "分析报告尚未生成，不能打开剪辑预览"
}
```

| HTTP 状态 | 场景 |
| --- | --- |
| `400` | `job_id` 格式不合法或报告字段不合法 |
| `401` | 项目任务未登录，`AUTH_REQUIRED` |
| `403` | 当前用户无权访问项目任务，`JOB_ACCESS_DENIED` |
| `404` | 任务或源视频不存在 |
| `409` | 任务未完成或报告尚未生成 |
| `500` | 持久化数据损坏或服务内部错误 |

## 6. 前端消费约束

- 页面只请求聚合接口，不直接读取 `samples` 推导评论。
- 时间显示可在前端格式化，但不得改变原始秒数。
- 时间轴片段位置以 `start / video.duration` 和 `(end - start) / video.duration` 计算。
- `agent_comment_status != ready` 时必须明确展示状态，不得伪造评论。
- 未知新增字段必须忽略，避免前端因兼容性扩展而失败。
