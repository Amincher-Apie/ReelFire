# Day 02 Agent 三工具工作流验收记录

## 验收范围

本次使用符合冻结 Schema 的 Mock CV 报告验证工作流，模型和 Embedding 均调用本机 Ollama 真实服务。Mock 只替代尚未在 Day 02 接入的真实 `analysis_report.json`，工具、模型调用、向量计算、校验和落盘均为真实执行。

## 真实运行配置

| 项目 | 实际值 |
|---|---|
| Embedding 模型 | `qwen3-embedding:0.6b` |
| 生成模型 | `qwen3:0.6b` |
| 知识条目 | 12 |
| 向量维度 | 1024 |
| 检索参数 | Cosine，Top-K=5，最低分 0.45 |
| 输入 | 2 帧 Mock CV 报告，含 `person`、`car`、关键帧和候选片段 |
| 输出文件 | `agent_report.json`、`agent_trace.json` |
| 输入摘要哈希 | `bb51bfc8e5d40795fc8117bfffa38422b15dac8fb92cb6e1b2b86ba8ec73bf74` |

## 工具轨迹

| 工具 | 状态 | 实测耗时 |
|---|---|---:|
| `report_parser` | `completed` | 0 ms |
| `knowledge_retriever` | `completed` | 779 ms |
| `advice_generator` | `completed` | 3586 ms |
| `rule_validator` | `degraded` | 0 ms |
| 工作流总计 | `degraded` | 4366 ms |

## 真实失败与处理

生成模型第一次返回了结构合法但仍含示例占位词的草稿。`rule_validator` 将其识别为不可交付内容，记录 `generated_output_rejected`，随后切换为确定性规则输出。

最终结果：

- 输出状态：`degraded`；
- 实际输出提供方：`rule_only / deterministic-v1`；
- 审核建议：`needs_review`；
- 摘要：共采样 2 帧，检测到 `person(2)`、`car(1)`，最高精彩度 0.735，候选片段 1 个；
- 所有标签和建议只引用真实 `evidence_ref` 与 `knowledge_id`；
- 调用轨迹不保存原始报告、密钥和本机绝对路径。

该失败案例证明工作流没有把“JSON 结构正确”误判为“内容可用”，模型低质量输出不会直接进入业务结果。

## 自动化验证

专项测试覆盖：

- 正常规则输出；
- 有效模型输出；
- 虚构事件拦截；
- 示例占位文本拦截；
- Embedding、检索和生成工具失败降级；
- 空检测强制人工复核；
- 非法输入明确失败；
- 引用完整性；
- 原子落盘及落盘失败处理。
