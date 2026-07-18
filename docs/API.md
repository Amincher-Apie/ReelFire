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

## 方向 B 接口

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
