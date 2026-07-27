# Agent/工作流工程师最终验收记录

## 范围

本记录只验收 Agent/工作流工程师负责的代码与契约，不把 CV 自定义模型、后端反馈 API、前端页面或最终分支合并冒充为本角色已完成内容。

## 新要求覆盖

| 要求 | 实现 | 状态 |
|---|---|---|
| 逐片段高光类型与触发规则 | `segment_comments[].explanation` | 已实现 |
| 类别、出现时间与轨迹 | `explanation.detections[]` | 已实现 |
| 观察帧数与连续帧数 | 分字段保存；CV 未提供连续值时为 `null` | 已实现 |
| 平均/最大置信度 | 直接读取受控 CV 摘要 | 已实现 |
| 关键帧与检测框 | 使用 `keyframe_refs` 与 `detection_box_refs` 指向证据 | 已实现 |
| 禁止虚构击杀等事件 | Prompt v3 + 确定性规则重建 | 已实现 |
| 采用/复核/拒绝 | `action_recommendation` 与三态审核映射 | 已实现 |
| 边界建议 | `boundary_suggestion` | 已实现 |
| 空检测/无命中/超时/不可用降级 | 原有服务降级链路 + 新输出兼容 | 已实现 |
| 反馈记录语义 | `agent_feedback.schema.json` | 已实现 |
| 采纳率/拒绝原因/边界统计 | `FeedbackAnalyzerTool` | 已实现 |
| 规则优化建议 | 基于最新反馈的确定性触发规则 | 已实现 |
| 工具轨迹/证据/知识/耗时/失败 | Agent 主报告与反馈摘要分别保留 | 已实现 |

## 验收边界

- CV 仍需把真实 FPS 模型字段写入正式 `analysis_report.json`；当前 Agent 不会把 COCO 类别包装成 FPS 事件。
- 后端仍需按冻结反馈 Schema 建表或扩展现有审核表，并提供查询/统计接口。
- 前端仍需从 `report-data.agent.segment_comments[]` 展示新字段并提交人工反馈。
- 以上跨角色工作未合并前，团队端到端产品闭环不能标记为完成。

## 测试命令

```powershell
python -m unittest tests.test_agent_feedback -v
python -m unittest tests.test_agent_tools -v
python -m unittest tests.test_agent_workflow -v
python -m unittest tests.test_agent_contracts -v
python -m unittest tests.test_agent_providers -v
python -m unittest tests.test_agent_execution -v
python -m unittest tests.test_agent_assets -v
```

## 2026-07-27 实测结果

- Agent 专项：`python -m unittest discover -s tests -p 'test_agent_*.py'`，100 项通过。
- 全仓回归：`python -m unittest discover -s tests -p 'test_*.py'`，238 项通过。
- 编辑器、审核持久化、API 与权限兼容组合测试首次出现 1 个异步轮询时序失败；对应单项立即复跑通过，全仓回归随后通过。
- Dify Cloud 的真实 Chatflow 已确认使用 `sys.query` 作为用户输入、DeepSeek Chat 模型和直接回复节点；Prompt v3 已保存并发布。
- Dify 应用密钥只允许通过本地环境变量或私密渠道配置，不写入 Git、日志、截图和文档。

最终提交前仍需执行 `git diff --check`、隐私扫描和密钥扫描；跨角色端到端验收由负责人基于真实 CV、后端反馈接口和前端展示完成。
