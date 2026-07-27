# Agent 逐片段解释与反馈闭环契约

本文冻结 Agent/工作流工程师交付给 CV、后端和前端的字段语义。所有字段均来自真实报告或人工操作记录，不允许由界面或模型补猜。

## 1. 逐片段输出

Agent 继续沿用 `agent_report.json.segment_comments[]`，不会另建前端难以关联的平行数组。每项至少包含：

| 字段 | 语义 | 来源 |
|---|---|---|
| `segment_id` | 稳定候选片段 ID | CV `segments[].id` |
| `comment` | 供剪辑者继续润色的片段内容描述初稿；只含时间和可验证画面事实 | 规则校验器依据受控 CV 摘要重建 |
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
- `segments[].score` 仅作为 CV 候选排序分，不作为具体游戏事件已发生的证明。分数低于 `0.25`、检测证据充分且不属于低置信度时，规则可建议 `reject`；只有角色、阵营或武器检测时，即使分数很高也保持 `needs_review`。
- 边界附近存在目标证据时，只提示检查起点、终点或两侧，不猜测新的秒数；证据不足时返回 `manual_review`。
- 模型草稿不能覆盖逐片段事实。最终 `segment_comments[]` 由 `RuleValidatorTool` 从受控 CV 摘要重建。
- `comment` 与审核决策分离：正文不写候选分、规则名或“建议保留/删除/复核”；这些判断只进入 `score_reason`、`review_status`、`action_recommendation` 和 `explanation`。

### 2.1 评论口吻

评论正文采用简短、自然、有情绪的评论区口吻，并按证据强度分层：

- 有独立 `kill/kill_notification` 事件及时间：可写“8.4 秒出现击杀提示，nice，这波很干净”。
- 同一片段有两个及以上独立击杀事件：可写“8.4—10.2 秒两次击杀提示紧接着出现，这波连杀节奏完全没断，漂亮”。
- 有 `clutch/clutch_event`：可写“残局节点出现，压力感拉满，太极限了”。
- 同时有 CT/T 独立轨迹：按唯一 `track_id` 写“2 名 CT 对 3 名 T、形成 2 打 3”；`enemy_engagement` 可写交火，其余情况只写对峙。武器没有队伍归属字段时只描述“画面中出现 AWP/步枪”，不猜由哪一方使用。
- 只有人物、武器和高候选分：可写“节奏拉满、这段很有看点”，但不得写击杀、连杀、爆头、残局或胜负。
- 中低候选分使用“节奏顺畅”“更像过渡段”等语气；候选分只控制表达强弱，不成为事件事实。

同一 `segment_id` 使用稳定模板选择，同一输入重复运行应得到相同评论。

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

## 4. 后端反馈记录

单条人工操作记录使用 `agent/schemas/agent_feedback.schema.json`。后端负责持久化，Agent 负责定义语义和统计：

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

具体路由和数据库迁移由后端工程师实现。后端不得提交 API Key；Dify 应用 Key 仍只通过本机环境变量或部署平台密钥管理传递。

## 5. 统计与规则建议

`FeedbackAnalyzerTool` 对同一 `job_id + segment_id` 只采用时间最新的反馈，输出：

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

## 6. 跨角色验收

| 角色 | 验收条件 |
|---|---|
| CV/数据工程师 | 正式报告提供真实 `reason`、出现时间、置信度、关键帧、检测框；连续帧数缺失时明确缺失 |
| 后端工程师 | 按反馈 Schema 持久化，返回稳定 `job_id/segment_id`，统计接口不改变字段语义 |
| 前端工程师 | 从 `report-data.agent.segment_comments[]` 展示解释；提交实际人工操作，不从文字反推字段 |
| 产品负责人 | 使用真实成功、低置信度、空结果和失败案例完成浏览器端回归 |
| Agent/工作流工程师 | Schema、Prompt、规则校验、降级、反馈统计和测试全部通过 |
