# Day 03 逐片段 Agent 联调记录

## 验收口径

本记录按剪辑预览 1.0 契约验证 Agent 的多片段输入、逐片段评论、证据引用、
调用轨迹和安全降级。只有实际运行得到的数据才记为运行证据；根据跨分支说明整理
的 JSON 只作为契约样例，不冒充 CV 运行产物。

## 跨分支检查基线

| 模块 | 检查分支与版本 | 当前事实 |
|---|---|---|
| CV 跟踪/多片段 | `origin/feat/cv-algorithm-v2` @ `61e553d` | README 已说明多片段与轨迹字段，但分支中没有提交实际生成的 highlights JSON |
| 编辑聚合 | `origin/Test-Glob` @ `65cdb81` | 已按 `segment_id` 读取 `agent_report.json.segment_comments[]`，缺失与损坏状态有兼容 |
| Agent | 当前功能分支本地工作区 | 已兼容独立 highlights 契约，缺失评分保持为空，逐段生成受证据约束的评论 |

`tests/fixtures/cv_highlights_v2.json` 明确标记为
`fixture_kind=contract_example` 和 `runtime_evidence=false`。它只用于冻结字段和
消费者行为，不能用于证明真实视频已产生多片段。

## 已完成的代码与契约验证

1. 合并适配器不修改原始 Web CV 报告或 highlights 输入；
2. 缺少片段 ID 时按源数组顺序稳定生成 `seg_001`、`seg_002`；
3. 缺少评分时不补常量，评论明确提示“CV 未提供可验证的片段评分”；
4. 跟踪的类别、时间边界、计数和置信度经过格式与范围校验；
5. 每个 `segment_comments[]` 都包含精确 `segment_id`、
   `comment`、三态建议和 `evidence_refs`；
6. 每条评论至少引用 `ev:segment:<segment_id>`，禁止生成未被检测证明的
   击杀、爆头、胜负等 FPS 事件；
7. 输出通过 Draft 2020-12 JSON Schema 校验；
8. `agent_report.json` 与 `agent_trace.json` 使用临时文件加 `os.replace`
   原子写入；
9. 四个工具轨迹保存输入摘要、输出摘要、状态、耗时和错误，不保存原始报告、
   密钥或绝对本地路径；
10. 后端交接记录默认使用 Prompt v2，并携带相对结果路径
    `agent_report.json`。

专项测试命令：

```powershell
python -m pytest -q tests/test_agent_tools.py tests/test_agent_workflow.py tests/test_agent_contracts.py tests/test_agent_assets.py
```

当前结果：`47 passed`。

## 本地真实 Ollama 生成调用

使用 `qwen3-embedding:0.6b` 和 `qwen3:0.6b` 对两片段契约样例执行了
真实 `/api/embed` 与 `/api/chat` 调用。这里的“真实”只表示 Embedding、模型
请求、规则校验和原子落盘均实际执行；输入仍是明确标记的契约样例，不代表 CV
已实际处理对应视频。

| 项目 | 实测结果 |
|---|---|
| `report_parser` | `completed` |
| `knowledge_retriever` | `completed`，真实 Embedding、Top-K=5 |
| `advice_generator` | `completed`，`ollama / qwen3:0.6b` |
| `rule_validator` | `completed` |
| 工作流 | `completed`，错误列表为空 |
| 片段评论 | `seg_001`、`seg_002` 均为 `needs_review` |
| 知识引用 | 5 条，包含 `KB-SEGMENT-001`、`KB-CORE-001` 等真实检索结果 |
| 工作流耗时 | 6556 ms |
| JSON Schema | 通过 |
| 禁止事件词检查 | 未出现击杀、爆头、胜负或残局结论 |
| 落盘 | `agent_report.json`、`agent_trace.json` 均已生成 |

在 Embedding 模型尚未补回本机时，还先执行了一次生成模型调用：
`knowledge_retriever=degraded`、`advice_generator=completed`、最终
`status=degraded`。该运行证明 Embedding 不可用时不会伪装为完全成功。

运行中还复现了一次中文输出路径经 PowerShell 管道传入 Python 后变成问号的
持久化失败。改用环境变量传递 Unicode 路径后，重新运行成功；失败结果中的
`agent_persistence_failed` 没有被隐藏。

## 当前集成阻塞

### 1. 缺少实际 CV 多片段文件

远端 CV 分支没有提交可复核的实际 `analysis_report.json` 或
`*_highlights.json`。在拿到一次真实运行产物前，只能完成契约级联调，不能把
“真实 CV 多片段端到端”标记为完成。

所需交接物：

- 一个实际任务的多片段 JSON；
- 每段稳定 `id/order/start/end`；
- 可用时提供 `score/source_keyframes`；
- 保留真实类别、置信度、时间和轨迹摘要。

### 2. `agent_calls` 尚无运行时写入与查询

`origin/Test-Glob` 已有 `agent_calls` 建表和索引，但当前 Python 代码中没有
该表的插入或查询实现。表内 `agent_calls.job_id` 是引用 `jobs.id` 的整数，
Agent 交接记录中的 `job_id` 是公开字符串任务号。后端入库时必须先通过
`jobs.job_id` 解析内部 `jobs.id`，并提供按公开任务号查询调用轨迹的服务或接口。

## 待实际联调后填写

- 实际 CV 任务号与输入文件：
- 实际片段数量与 ID：
- Ollama Embedding/生成模型配置：
- Agent 成功或降级状态：
- 编辑聚合接口返回：
- 按 `job_id` 查询调用日志结果：
