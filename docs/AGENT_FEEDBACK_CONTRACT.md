# Agent 逐片段解释与反馈闭环契约

本文冻结 Agent/工作流工程师交付给 CV、后端和前端的字段语义。所有字段均来自真实报告或人工操作记录，不允许由界面或模型补猜。

## 1. 逐片段输出

Agent 继续沿用 `agent_report.json.segment_comments[]`，不会另建前端难以关联的平行数组。每项至少包含：

| 字段 | 语义 | 来源 |
|---|---|---|
| `segment_id` | 稳定候选片段 ID | CV `segments[].id` |
| `review_status` | `pass/needs_review/reject` | 规则校验器 |
| `action_recommendation` | `adopt/needs_review/reject` | 与三态审核一一映射 |
| `explanation.highlight_type` | 可证明的高光候选类型 | CV `reason` 与检测类别 |
| `explanation.trigger_rule` | 原始触发规则；缺失时明确标记 | CV `reason` |
| `explanation.time_range` | 片段起止时间 | CV `start/end` |
| `explanation.detections[]` | 类别、出现时间、观察帧数、连续帧数、平均/最大置信度和轨迹 | CV `detections_summary[]` |
| `explanation.keyframe_refs[]` | 关键帧证据编号 | CV `source_keyframes[]` |
| `explanation.detection_box_refs[]` | 可解析到 `evidence_refs[].value.bbox` 的检测证据编号 | CV 帧检测框 |
| `boundary_suggestion` | 保留或人工检查哪一侧边界 | 目标首次/末次出现时间与当前边界 |
| `evidence_refs[]` | 本片段实际引用的证据白名单 | 受控视觉摘要 |

`detection_count` 只表示观察到目标的帧数，不能冒充连续帧数。只有 CV 明确提供 `consecutive_frame_count` 时，Agent 才会输出具体连续帧数；否则为 `null`。

## 2. 事实与降级规则

- 没有 `kill`、`kill_feed` 或 `kill_notification` 等明确类别时，不生成“击杀”“连续击杀”等事实。
- 没有检测、没有评分、知识库未命中、置信度不足、模型超时或服务不可用时，片段进入 `needs_review`。
- CV 精彩度低于 `0.25`、检测证据充分且不属于低置信度时，规则可建议 `reject`；其他低分情况保持 `needs_review`。
- 边界附近存在目标证据时，只提示检查起点、终点或两侧，不猜测新的秒数；证据不足时返回 `manual_review`。
- 模型草稿不能覆盖逐片段事实。最终 `segment_comments[]` 由 `RuleValidatorTool` 从受控 CV 摘要重建。

## 3. CV 必须提供的字段

生产联调时，CV 应在任务目录的正式 `analysis_report.json.segments[]` 中提供：

```json
{
  "id": "seg_001",
  "start": 12.4,
  "end": 20.8,
  "score": 0.82,
  "reason": "enemy_engagement",
  "source_keyframes": ["kf_004"],
  "detections_summary": [
    {
      "track_id": "17",
      "class": "enemy",
      "first_seen": 13.1,
      "last_seen": 19.9,
      "detection_count": 23,
      "consecutive_frame_count": 11,
      "confidence": 0.78,
      "confidence_max": 0.93,
      "confidence_min": 0.51
    }
  ]
}
```

检测框继续位于 `samples[].objects[].bbox` 或 `keyframes[].objects[].bbox`。如果 CV 不提供连续帧数、关键帧或检测框，Agent 会保留 `null`/空数组，不会制造数据。

## 4. 反馈记录 Schema（后端尚未持久化）

单条人工操作记录使用 `agent/schemas/agent_feedback.schema.json`。Agent 当前
只冻结语义并提供离线统计；本轮后端没有实现反馈事件持久化、写入 API、数据库
表或 migration：

```json
{
  "schema_version": "1.0",
  "feedback_id": "fb_001",
  "job_id": "job_001",
  "segment_id": "seg_001",
  "decision": "rejected",
  "rejection_reason": "boundary_error",
  "original_boundary": {"start": 12.4, "end": 20.8},
  "final_boundary": {"start": 11.5, "end": 22.0},
  "original_order": 1,
  "final_order": 2,
  "reexported": true,
  "recorded_at": "2026-07-27T10:00:00+08:00"
}
```

`decision` 固定为 `adopted/needs_review/rejected`。只有 `rejected` 允许填写 `rejection_reason`，其枚举为：

- `not_highlight`
- `duplicate`
- `detection_error`
- `boundary_error`
- `other`

起止调整量由 Agent 统计工具使用 `final - original` 重算，不接受客户端自行上报的差值，避免统计口径不一致。

建议后端提供：

- `POST /api/jobs/{job_id}/segments/{segment_id}/feedback`
- `GET /api/jobs/{job_id}/feedback`
- `GET /api/statistics/agent-feedback`

以上仅为后续接口建议，不是已上线能力。具体路由和数据库迁移仍待独立设计与
评审。后端不得提交 API Key；Dify 应用 Key 仍只通过本机环境变量或部署平台
密钥管理传递。

## 5. 统计与规则建议

离线 `FeedbackAnalyzerTool` 对同一 `job_id + segment_id` 只采用时间最新的
反馈，输出：

- 候选采纳率；
- 三态数量；
- 常见拒绝原因；
- 起止边界平均调整量与调整率；
- 顺序变化率；
- 重新导出率；
- 基于固定阈值触发的规则优化建议；
- 工具耗时和输入事件数量。

本地验证命令：

```powershell
python -m agent.analyze_feedback feedback.json --output feedback_summary.json
```

输出须通过 `agent/schemas/agent_feedback_summary.schema.json`。统计建议只供 CV/产品负责人调参评审，不能自动修改生产阈值。

该命令读取调用者明确提供的本地 JSON 文件，不代表后端已经收集用户反馈。

## 6. 跨角色验收

| 角色 | 验收条件 |
|---|---|
| CV/数据工程师 | 正式报告提供真实 `reason`、出现时间、置信度、关键帧、检测框；连续帧数缺失时明确缺失 |
| 后端工程师 | 当前仅从 `report-data.agent.segment_comments[]` 安全公开解释；反馈持久化仍待后续实现 |
| 前端工程师 | 从 `report-data.agent.segment_comments[]` 展示解释；当前没有反馈写入 API，不从文字反推字段 |
| 产品负责人 | 使用真实成功、低置信度、空结果和失败案例完成浏览器端回归 |
| Agent/工作流工程师 | Schema、Prompt、规则校验、降级、反馈统计和测试全部通过 |
