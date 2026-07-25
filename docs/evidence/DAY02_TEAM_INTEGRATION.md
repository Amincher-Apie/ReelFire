# Day 02 跨成员契约对接记录

## 对接对象

本次在不合并其他成员分支的前提下，同步检查了以下远端版本：

| 模块 | 远端分支 | 检查版本 | 对接结论 |
|---|---|---|---|
| 主干 CV/任务服务 | `origin/main` | `4c6faf1` | `analysis_report.json` 可作为 Agent 真实输入 |
| 后端认证与报告契约 | `origin/feature/backend-auth-report` | `678cbc0` | 需要映射 `agent_calls` 状态和工具轨迹字段 |
| CV 算法扩展 | `origin/feat/cv-algorithm-v2` | `94cf390` | 新增训练与跟踪能力，未改变当前任务服务报告入口 |
| 前端 | `origin/feature/frontend` | `f7842d8` | 暂无 Agent 字段消费，后续按后端接口接入 |

## 已解决的契约差异

### CV 输入

主干直接保存原始 `analysis_report.json`，Agent 边界额外要求
`schema_version` 和 `provider`。`build_agent_input()` 负责包装真实报告，并使用
深拷贝确保 Agent 不会修改 CV 模块持有的证据。

`AgentService.run_analysis_report()` 可直接接收主干报告，继续执行报告解析、
知识检索、建议生成和规则校验。

### 后端调用记录

Agent 内部状态包含 `degraded`，后端契约使用 `needs_review`。映射规则为：

- Agent `failed` -> 后端 `failed`；
- Agent `degraded` -> 后端 `needs_review`；
- Agent 输出建议人工复核 -> 后端 `needs_review`；
- 其余校验通过结果 -> 后端 `completed`。

`to_backend_agent_call()` 同时转换：

- `trace.tools[].name` -> `tool_trace[].tool`；
- `report_parser` -> `visual_report_parser`；
- `rule_validator` -> `result_validator`；
- 模型名、耗时、错误码、知识引用和审核意见 -> 后端对应字段。

## 自动化契约验证

`tests/fixtures/cv_analysis_report_v1.json` 按主干
`services/analysis_service.py::analyze_video()` 的真实返回结构固化，不使用 Agent
自定义 Mock Schema。`tests/test_agent_contracts.py` 验证：

1. 原始 CV 报告不会被修改；
2. 当前主干报告可直接完成 Agent 工作流；
3. 后端状态和工具轨迹映射符合 `agent_calls` 契约；
4. 非法 CV 报告映射为明确失败；
5. 未知模型提供方在进入工作流前被拒绝。

## 本地真实链路复验

契约测试通过后，使用上述 CV 契约夹具调用本机
`qwen3-embedding:0.6b` 和 `qwen3:0.6b`：

| 项目 | 结果 |
|---|---|
| `report_parser` | `completed` |
| `knowledge_retriever` | `completed` |
| `advice_generator` | `completed` |
| `rule_validator` | `degraded`，拒绝低质量模型草稿并使用确定性输出 |
| Agent 最终状态 | `degraded` |
| 后端映射状态 | `needs_review` |
| 总耗时 | 4169 ms |
| 输出 | `agent_report.json`、`agent_trace.json` 均成功落盘 |

该结果验证了真实模型调用、向量检索、安全降级和后端状态映射可以共同工作。
`degraded` 没有被错误转换成后端 `completed`。

## 后续联调边界

Day 02 完成的是代码契约兼容，不宣称已经合并或调用其他成员尚未实现的运行时接口。
Day 03 应使用团队实际生成的 `outputs/<job_id>/analysis_report.json` 运行一次完整
Agent 流程，并由后端保存 `agent_calls` 记录；接口实现发生变化时同步更新本记录和
契约测试。
