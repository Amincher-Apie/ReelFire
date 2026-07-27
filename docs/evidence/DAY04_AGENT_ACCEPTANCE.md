# Day 04 Agent 回归验收与失败分析

## 1. 验收范围

本次只验收 Agent/工作流职责：读取 CV 报告、检索知识、生成建议、校验引用、
生成逐片段评论，并把状态安全映射到后端和 Editor。测试不会修改 CV 检测结果，
也不会虚构击杀、爆头、胜负或武器等当前报告无法证明的事件。

输入为受控 `analysis_report.json` 与可选多片段 highlights；输出为
`agent_report.json`、`agent_trace.json` 和后端 `agent_calls` 映射。所有测试
使用公开夹具、占位 Key 或模拟 HTTP 响应，不保存真实密钥和本机路径。

## 2. 五个成功样例

| 编号 | 场景 | 自动化证据 | 通过标准 |
| --- | --- | --- | --- |
| S1 | 正常 CV 报告 | `test_agent_runs_from_current_cv_analysis_report_contract` | 生成摘要、知识引用和 `seg_001` 评论 |
| S2 | 正常多片段输入 | `test_multi_segment_result_validates_against_output_schema` | 每个源片段得到同 ID 评论并通过输出 Schema |
| S3 | 模型没有返回逐片段评论 | `test_valid_model_draft_is_used` 与规则校验测试 | 本地校验器按真实 `segments[]` 补建评论，不采信模型虚构片段 |
| S4 | 知识库 Embedding 与 Top-K 命中 | `test_vector_retrieval_builds_cached_index_and_returns_top_k` | Top-K=5，返回 `knowledge_id`、相似度和命中原因 |
| S5 | Dify 短时限流后恢复 | `test_rate_limit_retries_once_then_returns_answer` | 429 只触发有限退避，第二次成功并记录 2 次尝试 |

## 3. 失败与低置信度样例

| 编号 | 场景 | 自动化证据 | 预期处理 |
| --- | --- | --- | --- |
| F1 | 空检测 | `test_empty_detection_cannot_be_auto_passed` | 不自动通过；无标签并进入 `needs_review` |
| F2 | 低置信度检测 | `test_low_confidence_detection_requires_review` | 保留真实置信度，审核置信度不高于 0.45 |
| F3 | 知识库无命中 | `test_knowledge_miss_requires_review_and_keeps_segment_comment` | 无知识引用但仍保留逐片段评论并进入人工复核 |
| F4 | Embedding 超时或不可用 | `test_retrieval_falls_back_when_embedding_is_unavailable` | 使用确定性检索，记录 `knowledge_retrieval_degraded` |
| F5 | Dify Key 无效 | `test_auth_failure_is_classified_and_never_retried` | 标记 `dify_auth_failed`，不重试，规则降级 |
| F6 | Dify 网络持续不可用 | `test_network_failure_exhausts_bounded_retries` | 最多 3 次，标记 `dify_network_error` 和实际尝试次数 |
| F7 | Dify 输出不是业务 JSON | `test_contract_error_is_not_retried` | 标记 `dify_contract_error`，不重试，规则降级 |

覆盖数量为 5 个成功样例和 7 个失败/低置信度样例，高于课程要求的 5+3。
其中网络和 Dify HTTP 行为是可重复的适配器契约测试，不等同于真实 Dify
在线成功截图。

## 4. 错误分类与界面影响

| 提供方错误 | 是否重试 | Agent 结果 | Editor/后端行为 |
| --- | --- | --- | --- |
| `dify_auth_failed` | 否 | `degraded` + 规则结果 | `risk_flags` 同时保留兼容码和细分码 |
| `dify_network_error` / `dify_timeout` | 是，最多 3 次 | 最终失败后 `degraded` | 评论仍来自确定性结果，提示待复核 |
| `dify_rate_limited` / `dify_server_error` | 是，最多 3 次 | 恢复则继续；否则降级 | 日志保存尝试次数和脱敏请求编号 |
| `dify_request_rejected` | 否 | `degraded` | 修复请求或应用配置后再运行 |
| `dify_contract_error` | 否 | `degraded` | 修复 Chatflow Answer JSON，不盲目重试 |

## 5. 用途、局限与交接

- 用途：把可验证的 CV 片段变成编辑页可展示的说明、审核建议和引用链。
- 输入限制：片段必须满足 `0 <= start < end <= duration`，评论只使用报告中
  已有类别、置信度、分数、时间和知识条目。
- 输出限制：Agent 只给建议，不替代人工审核；`needs_review` 不能当作通过。
- 降级限制：Embedding 或大模型不可用时仍能生成规则结果，但必须显示降级状态。
- 真实在线状态：已在 Dify Cloud 创建 `ReelFire 媒体审核助手` Chatflow
  （应用 ID `69241329-2eb7-441c-b4e0-6035c644bce9`），并通过平台预览完成一次
  真实模型调用；结果是符合项目字段约定的纯 JSON，逐片段评论保留
  `seg_001` 与 `ev:segment:seg_001`，证据不足时为 `needs_review`。
- API 验收状态：应用 Key 健康检查已返回 `ok=true`、名称正确且模式为
  `advanced-chat`；真实任务调用最终保留 `provider.type=dify`。首次调用暴露
  DeepSeek API 的 `<think>...</think>` 前缀，适配器增加安全剥离后业务 JSON
  解析成功。仓库没有也不应包含该应用 Key。
- 当前降级边界：真实任务仍记录 `knowledge_retrieval_degraded`，原因是执行进程
  没有可用的 Embedding 配置；模型调用本身已成功，不再出现
  `model_generation_failed`。
- DSL 限制：当前仓库没有伪造 DSL。真实 DSL 必须从已发布 Chatflow 导出、清除
  密钥并记录版本和 SHA-256 后再交付。
- 后续项：跨请求熔断和生成结果缓存需要先冻结共享状态、缓存键和失效策略，
  不在本轮 Day 04 的已完成范围内。

交接配置见 `docs/DIFY_CONFIGURATION_HANDOFF.md`；工作流边界见
`docs/AGENT_WORKFLOW.md`；输入输出契约见 `agent/schemas/` 与 `docs/API.md`。

## 6. 本地复现命令

```powershell
python -m unittest tests.test_agent_providers -v
python -m unittest tests.test_agent_tools -v
python -m unittest tests.test_agent_workflow -v
python -m unittest tests.test_agent_contracts -v
python -m unittest discover -s tests -v
```

## 7. 2026-07-27 实测结果

- Agent、知识库、工作流、Dify 适配器、跨模块契约和后台执行专项测试：
  `82` 项通过，`0` 项失败；其中包含真实联调后新增的 DeepSeek 推理块解析用例。
- 全仓测试：执行 `214` 项，其中 `212` 项通过；另外 `2` 项受当前 Windows
  应用控制策略阻止 `torch_python.dll` 加载影响，分别表现为 CV 测试模块导入
  错误和损坏视频用例取得同一环境错误。该阻塞位于 CV/Torch 环境，不属于本次
  Agent 代码回归，但全仓结果不能写成全绿。
- `python -m compileall -q agent services tests` 与 `git diff --check` 通过。
