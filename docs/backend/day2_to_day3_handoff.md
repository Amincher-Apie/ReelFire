# Backend Day 2 to Day 3 Handoff

## 1. 当前分支与基线

- 当前功能分支：`feature/backend-authz-persistence-7.25`
- Day 2 起始基线：`ed8b6a6`
- 当前 HEAD：`313964f`

## 2. 已实现服务

- `services/session_service.py`：校验 Session 中的 SQLite 用户，并统一处理失效登录状态。
- `services/project_service.py`：校验、创建、列出项目并执行 owner 归属查询。
- `services/job_index_service.py`：映射公开 `job_id` 与内部 `jobs.id`，并原子写入项目型上传的 asset/job 索引。
- `services/job_access_service.py`：区分项目任务与 legacy 任务，对项目任务执行统一 owner 权限校验和列表可见性过滤。
- `services/review_service.py`：校验三态人工审核，追加历史，并协调 SQLite 写入与报告文件补偿。
- `services/agent_call_service.py`：创建和查询 Agent 调用日志，并执行受约束的生命周期状态更新。

## 3. Day 3 上游输入契约

CV 输入至少需要：

```json
{
  "segments": [
    {
      "id": "seg_001",
      "order": 1,
      "start": 1.0,
      "end": 5.0,
      "score": 0.8,
      "source_keyframes": []
    }
  ]
}
```

Agent 输入至少需要：

```json
{
  "segment_comments": [
    {
      "segment_id": "seg_001",
      "comment": "真实 Agent 评论",
      "evidence_refs": []
    }
  ]
}
```

约束：

- 不得从 `score` 自动伪造 Agent 评论。
- `segment_id` 必须与 CV 片段 ID 精确匹配。
- 没有合法且可验证的 Agent 评论时保持 `agent_comment_status = pending`。
- Agent 调用日志 `completed` 不等于 Editor 评论 `ready`。
- `agent_calls.result` 是执行日志，不是 Editor 评论的直接数据源。

## 4. Editor 1.0 不可破坏项

- 页面唯一数据源仍为 `GET /api/jobs/<job_id>/editor`。
- 不删除字段，也不改变已有字段类型。
- `agent_comment_status` 只允许 `ready`、`pending`、`unavailable`。
- 项目任务继续执行 `401 AUTH_REQUIRED` 和 `403 JOB_ACCESS_DENIED`。
- `/outputs/<job_id>/...` 继续执行与任务 API 相同的归属校验。
- Editor 评论仍只从合法 `agent_report.json.segment_comments[]` 或带可验证证据的 `suggestions[]` 聚合。

## 5. Day 3 后端待办

- 校验多片段 ID、排序、边界、重叠和证据引用。
- 按 `segment_id` 聚合真实 Agent 评论与证据。
- 支持刷新后恢复编辑与三态审核状态。
- 实现多片段 FFmpeg 导出和失败清理。
- 增加统计 JSON、审核包或报告接口。
- 保持 legacy 文件任务兼容。
- 增加并发、权限、损坏输入和失败补偿回归。

## 6. 已知风险

- 损坏视频异步测试的约 3 秒等待窗口存在时序抖动。
- SQLite 与文件系统不能形成统一事务，目前依赖回滚和补偿。
- 删除任务后的 SQLite 关联记录生命周期仍需设计。
- Agent 结果暂以 `inline_json$` 编码保存在 `result_path`，后续需要正式迁移。
- Agent 活动调用去重只覆盖 SQLite 单机和当前进程，不是分布式队列。
- 真实 Agent、RAG 和 `segment_comments[]` 尚未接入。
- 多片段生产、聚合和导出尚未实现。
- legacy 文件任务没有完整 SQLite 业务索引。
