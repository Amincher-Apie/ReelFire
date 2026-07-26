# ReelFire Agent 工作流设计

## 1. 目标与范围

ReelFire Agent 读取现有 CV 流程生成的 `analysis_report.json`，结合媒体审核知识库，输出可追溯的内容摘要、标签、剪辑建议和三态审核建议。

Agent 不替代 OpenCV、YOLO 或精彩度评分，也不直接修改原始检测结果。现有 `segment_tags` 和 `ai_cover_prompt` 保留为规则基线，用于模型不可用时的降级输出和结果对照。

Day 01 冻结工作流、事实边界、知识库来源与切分、输入输出 Schema 和 Prompt，并使用本地 Ollama 完成至少一类知识库的真实 Embedding 与 Top-K 检索。模型调用、日志落盘与接口接入在 Day 02～Day 03 继续完善。

## 2. 事实边界

Agent 可以引用的事实只有：

1. `analysis_report.json` 中真实存在的类别、置信度、检测框和时间戳；
2. 报告中的目标数、运动强度、画面变化和精彩度分数；
3. 候选片段、关键帧和人工审核字段；
4. 检索命中的知识库条目。

以下内容不得作为事实生成：

- 击杀、爆头、残局、胜负、玩家身份、武器名称等未被当前模型直接检测的 FPS 事件；
- 报告中不存在的类别、时间戳、置信度或片段；
- 未命中的知识库规则；
- 由画面风格推断出的剧情、情绪或比赛结果。

模型可以给出编辑建议，但必须明确它是“建议”，并附带检测证据或知识条目引用。证据不足时必须返回 `needs_review`，不能用猜测补齐。

## 3. 模块边界

| 模块 | 输入 | 输出 | 责任 |
|---|---|---|---|
| CV 流程 | 视频与分析设置 | `analysis_report.json` | 采样、检测、评分、关键帧和候选片段 |
| 报告解析工具 | 原始 CV 报告 | 受控视觉摘要 | 过滤可引用字段、归一化数值、生成证据编号 |
| 知识库检索工具 | 类别、分数、关键词、查询向量 | 知识条目列表 | 混合检索并返回 `knowledge_id`、相似度和命中原因 |
| 建议生成工具 | 视觉摘要、知识条目、Prompt | Agent 草稿 | 生成摘要、标签、建议和三态审核建议 |
| 规则校验工具 | Agent 草稿、受控视觉摘要 | 合法输出或降级输出 | 拒绝无证据类别、时间戳和事件 |
| Agent 工作流 | `job_id` 与报告 | Agent 报告、调用轨迹 | 编排工具、选择模型、记录状态和错误 |
| 后端服务 | Agent 报告 | 查询与写回接口 | 持久化、按 `job_id` 查询、三态审核写回 |

## 4. 工作流

```text
analysis_report.json
        |
        v
[1. 报告解析]
  - 校验 job_id 和关键字段
  - 汇总真实类别、置信度、时间戳和分数
  - 为事实建立 evidence_ref
        |
        v
[2. 知识库检索]
  - 对知识条目和查询生成 Embedding
  - 计算余弦相似度并召回 Top-K
  - 使用真实类别、质量状态、分数和关键词重排
  - 返回 knowledge_id、相似度、命中原因与审核规则
        |
        v
[3. 建议生成]
  - Ollama/Qwen3、Dify、Coze 或规则降级
  - 输出统一 JSON 草稿
        |
        v
[4. 事实与结构校验]
  - JSON 结构检查
  - evidence_ref / knowledge_id 存在性检查
  - 禁止虚构 FPS 事件
        |
        +---- 合法 ----> completed
        |
        +---- 模型失败但规则可用 ----> degraded
        |
        +---- 输入损坏或无法形成安全输出 ----> failed
```

## 5. 三态审核建议

| 状态 | 英文字段值 | 使用条件 |
|---|---|---|
| 通过 | `pass` | 证据充分、置信度和片段边界合理，未触发风险规则 |
| 待复核 | `needs_review` | 低置信度、空检测、知识库未命中、证据冲突或模型降级 |
| 不通过 | `reject` | 输入损坏、片段非法、输出无法通过事实校验或存在明确违规风险 |

Agent 只给出审核建议。最终审核状态由人工或后端审核接口确认，不能由模型静默覆盖。

## 6. 模型提供方策略

工作流对外只接受统一的 `provider` 配置，不把平台特有字段写入业务输出。

| 提供方 | 建议用途 | 配置方式 | 失败处理 |
|---|---|---|---|
| `ollama` | 默认本地推理，使用已安装的 Qwen3 | `OLLAMA_BASE_URL`、`OLLAMA_MODEL` | 超时后进入规则降级 |
| `dify` | 通过阻塞式 Chat API 调用 Dify Cloud Chatflow（`advanced-chat`） | `DIFY_BASE_URL`、Chatflow 应用 `DIFY_API_KEY`、`DIFY_USER` | 空 Key、类型错误、超时或非法 JSON 时记录错误并切换降级 |
| `coze` | 复用课程中配置的 Coze 智能体或工作流 | `COZE_BASE_URL`、`COZE_API_TOKEN`、`COZE_BOT_ID` | 记录平台错误，切换降级 |
| `rule_only` | 无模型或演示离线模式 | 无密钥 | 只输出规则可证明的内容 |

默认顺序为：

```text
用户指定提供方
  -> 调用成功：继续事实校验
  -> 调用失败：rule_only 生成受限结果
  -> 规则也无法处理：failed
```

不同平台必须复用同一份 Prompt 和输出 Schema。平台返回的会话编号只写入调用轨迹，不得成为业务事实。

Dify 部署、应用类型、输入输出契约、版本、DSL 和跨电脑验证步骤冻结在
`docs/DIFY_CONFIGURATION_HANDOFF.md`。当前适配器使用 `blocking` 的
`/v1/chat-messages`，因此交付类型固定为 Chatflow，不能用 Workflow 或 Agent
应用替换。

公开仓库的 `.env.example` 只保存变量名和非敏感默认值，`DIFY_API_KEY` 必须为空。
测试人员将其复制为被 Git 忽略的 `.env` 后再填写真实 Key。命令行入口
`python -m agent.run_agent` 读取该文件并实际调用 Dify；Key 缺失时输出
`model_generation_failed` 并安全降级。

知识库使用混合检索：

1. Day 01 验收使用本地 Ollama 对 12 个媒体审核条目生成真实 Embedding；
2. 检索参数冻结为 Top-K `5`、最低分 `0.45`，相似度算法为 Cosine；
3. Ollama 模型名从 `OLLAMA_EMBED_MODEL` 读取，小数据量直接在内存中计算余弦相似度；
4. 向量服务不可用时降级为关键词、类别和指标条件检索，并把调用状态标为 `degraded`；
5. 最终结果必须返回 `knowledge_id`、相似度和具体命中原因，保证检索可验证。

知识来源表位于 `agent/knowledge/SOURCES.md`，可选的 Dify 上传源位于
`agent/knowledge/dify_media_review_rules.md`，真实检索记录位于
`docs/evidence/OLLAMA_KNOWLEDGE_ACCEPTANCE.md` 和
`docs/evidence/ollama_topk_results.json`。相似度必须由真实 Embedding 调用产生，不得人工填写。

## 7. 安全配置

- 所有令牌只从环境变量读取；
- `.env`、日志、Agent 报告和测试夹具都不得保存真实密钥；
- 调用轨迹只记录提供方、模型、耗时、状态、错误类型和脱敏后的输入摘要；
- Prompt 中不包含本地绝对路径、令牌或用户隐私；
- 外部模型收到的是受控视觉摘要，不是原始视频和完整本地文件。

## 8. 状态与调用轨迹

Agent 调用状态固定为：

```text
queued -> running -> completed
                  -> degraded
                  -> failed
```

每次调用至少记录：

- `job_id`；
- `provider` 和 `model`；
- 开始、结束时间与 `duration_ms`；
- 三个工具节点的状态与耗时；
- 输入摘要的哈希或计数，不保存完整敏感输入；
- 错误类型和可读错误信息；
- 是否发生规则降级；
- 输出报告相对路径。

## 9. 与现有代码的接入点

Day 02～Day 03 的代码接入遵循以下原则：

1. 在独立 `agent/` 包中实现工具和编排，不把模型逻辑塞进 Flask 路由；
2. `AnalysisService` 完成 CV 报告落盘后，再触发 Agent 工作流；
3. Agent 失败不能把已经完成的 CV 任务改成失败；
4. Agent 输出单独保存，建议文件名为 `agent_report.json`；
5. 后端按 `job_id` 提供 Agent 报告和轨迹查询；
6. API 字段变化必须同步更新 `docs/API.md` 和测试。

当前主干的 `analysis_report.json` 通过
`agent.integrations.build_agent_input()` 添加 Agent 边界元数据，
`AgentService.run_analysis_report()` 可直接运行该真实报告。Agent 结果通过
`agent.integrations.to_backend_agent_call()` 映射到后端 `agent_calls` 契约；
内部 `degraded` 对外映射为 `needs_review`，不会伪装成成功。

当前后端的 `POST /api/jobs/<job_id>/agent-calls` 会创建 `queued` 日志并交给
`AgentExecutionService` 后台运行。执行器把真实工具轨迹和终态写入 SQLite，
同时在任务目录原子保存 `agent_report.json` 与 `agent_trace.json`。Editor 聚合
逐片段评论时另行透传 `agent_review_status`，不再丢失 `needs_review`。

当前 CV 跟踪分支的多片段 highlights 导出与 Web
`analysis_report.json` 仍是两个产物。兼容层可把 highlights 中的真实轨迹、
类别和时间边界合并到 Agent 输入，并按源顺序补充稳定片段 ID；缺失评分保持
为空，不能用常量或模型猜测补齐。最终生产链仍应由 CV/后端把多片段
`segments[]` 写入任务目录中的 `analysis_report.json`。

## 10. Day 01 验收

- [x] 规则基线与独立 Agent 的边界明确；
- [x] 三工具工作流和状态转换明确；
- [x] Ollama、Dify、Coze 与规则降级策略明确；
- [x] Embedding、向量检索、规则重排和降级策略明确；
- [x] 知识库来源表和 12 条可独立切分的 Dify 上传文本已完成；
- [x] 三态审核建议口径明确；
- [x] 事实引用和禁止虚构规则明确；
- [x] 密钥与调用日志安全边界明确；
- [x] 知识库、输入输出 Schema 和 Prompt v2 通过本地资产测试。
- [x] 本地 Ollama 已完成真实 Embedding，并保存两组 Top-K=5 检索结果。

## 11. Day 02 验收

- [x] `ReportParserTool` 校验报告、检测结果、时间戳和片段边界；
- [x] `KnowledgeRetrieverTool` 完成向量索引、Top-K、规则重排和确定性降级；
- [x] `AdviceGeneratorTool` 支持本地 Ollama 与规则生成；
- [x] `RuleValidatorTool` 校验所有证据引用和知识引用，拒绝虚构内容及示例占位文本；
- [x] `AgentService` 保存输入摘要哈希、工具状态、耗时、错误和降级状态；
- [x] Agent 报告与脱敏调用轨迹使用原子 JSON 写入；
- [x] Mock CV 报告稳定返回结构化 JSON，空检测和非法输入均有明确状态；
- [x] 真实 `qwen3-embedding:0.6b` 检索与 `qwen3:0.6b` 生成链路已执行；
- [x] 小模型复制示例占位文本的真实失败被规则校验拦截，并安全降级。
- [x] 已检查 CV、后端和前端远端分支，保存跨成员契约对接记录；
- [x] 当前主干真实 `analysis_report.json` 结构已通过契约夹具测试；
- [x] Agent 状态、工具轨迹、引用和错误已映射到后端 `agent_calls` 字段。

## 12. Day 03 逐片段联调口径

- `segment_comments[].segment_id` 必须与 CV `segments[].id` 精确一致；
- 每条评论必须包含对应的 `ev:segment:<segment_id>`，可附加真实检测或关键帧引用；
- 评论只描述报告中存在的时间、类别、置信度、评分和知识条目；
- CV 未提供评分时明确写“未提供可验证的片段评分”，状态进入 `needs_review`；
- `agent_report.json` 与 `agent_trace.json` 使用同目录原子替换写入；
- 工具轨迹记录输入摘要、输出摘要、耗时、状态和错误，可由后端按 `job_id`
  写入或查询 `agent_calls`；
- `tests/fixtures/cv_highlights_v2.json` 仅用于冻结跨分支契约，不是实际运行数据；
- 只有拿到 CV 实际生成的多片段 JSON 并完成整链运行后，才可把“真实多片段联调”
  标记为完成。
