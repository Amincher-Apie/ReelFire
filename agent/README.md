# ReelFire Agent 模块

`agent/` 独立负责把 CV 流程生成的 `analysis_report.json` 转换为有证据引用的内容摘要、知识规则和审核建议。模型或向量服务失败不能修改原始 CV 报告。

## Day 02～Day 03 工具与逐片段输出

当前已实现四个工具：

- `ReportParserTool`：校验输入、关键帧、检测结果和片段边界，生成受控视觉摘要及稳定的 `evidence_ref`；
- `KnowledgeRetrieverTool`：构建内存向量索引，执行向量召回和规则重排；Embedding 不可用时自动返回 `degraded` 并使用确定性规则检索；
- `AdviceGeneratorTool`：调用已配置模型或确定性规则生成摘要、标签和建议；
- `RuleValidatorTool`：校验结构、引用边界和禁止虚构项。

完整工作流由 `AgentService` 编排：

1. `report_parser` 生成受控视觉摘要；
2. `knowledge_retriever` 返回 Top-K 知识引用；
3. `advice_generator` 调用本地模型或确定性规则；
4. `rule_validator` 检查结构、引用、三态审核和禁止虚构项；
5. 按 CV `segments[].id` 生成 `segment_comments[]`；
6. 原子写入 `agent_report.json` 和脱敏后的 `agent_trace.json`。

每个工具轨迹均包含状态、耗时、输入摘要和输出摘要。摘要只保存数量、状态等
非敏感信息，不写入原始报告、视频内容、令牌或本机绝对路径。

## 在线 Dify 配置

仓库提供真实的 Dify Chat API 适配器，密钥只从本地环境读取。先复制配置样例：

```powershell
Copy-Item .env.example .env
```

然后只在本机 `.env` 中填写：

```dotenv
AGENT_PROVIDER=dify
DIFY_BASE_URL=https://api.dify.ai
DIFY_API_KEY=
DIFY_USER=reelfire-demo
DIFY_MODEL_LABEL=dify-chat-app
```

`DIFY_API_KEY` 在公开仓库中必须保持空值。测试人员填入 Dify 应用的 API Key
后，可直接运行：

```powershell
python -m agent.run_agent `
  --analysis-report outputs/<job_id>/analysis_report.json `
  --output-dir outputs/<job_id> `
  --provider dify
```

Web 端在分析完成后调用 `POST /api/jobs/<job_id>/agent-calls`，后端会使用
同一配置启动真实后台 Agent 执行。调用状态可通过
`GET /api/jobs/<job_id>/agent-calls` 查询；完整结果写入任务目录中的
`agent_report.json` 和 `agent_trace.json`。

若 CV 跟踪结果仍是独立文件，可额外传入：

```powershell
--highlight-report outputs/<job_id>/<video>_highlights.json
```

Key 为空、Dify 超时、返回非 JSON 或引用不合法时，工作流会记录错误并切换为
确定性规则结果，不会把在线调用失败伪装为成功，也不会破坏 CV 报告。

本地 Ollama 调用示例：

```python
from agent.tools import KnowledgeRetrieverTool, OllamaEmbedder, ReportParserTool

visual_summary = ReportParserTool().run(agent_input)
retrieval = KnowledgeRetrieverTool(embedder=OllamaEmbedder()).run(
    visual_summary
)
```

运行前通过环境变量指定真实模型：

```powershell
$env:OLLAMA_BASE_URL='http://127.0.0.1:11434'
$env:OLLAMA_EMBED_MODEL='qwen3-embedding:0.6b'
```

工具不会把 `ai_cover_prompt` 中未被检测模型证明的事件提升为事实。可引用事实只能来自受控摘要的 `evidence_refs` 和检索结果中的 `knowledge_id`。

完整调用示例：

```python
from pathlib import Path

from agent.providers import OllamaChatClient
from agent.service import AgentService
from agent.tools import AdviceGeneratorTool, KnowledgeRetrieverTool, OllamaEmbedder

service = AgentService(
    knowledge_retriever=KnowledgeRetrieverTool(embedder=OllamaEmbedder()),
    advice_generator=AdviceGeneratorTool(model_client=OllamaChatClient()),
)
agent_report = service.run(agent_input, output_dir=Path("outputs/job_id"))
```

直接对接主干生成的 `analysis_report.json`：

```python
import json
from pathlib import Path

from agent.integrations import to_backend_agent_call

cv_report = json.loads(
    Path("outputs/job_id/analysis_report.json").read_text(encoding="utf-8")
)
agent_report = service.run_analysis_report(
    cv_report,
    provider={"type": "ollama", "model": "qwen3:0.6b"},
    output_dir=Path("outputs/job_id"),
)
backend_record = to_backend_agent_call(agent_report, prompt_version="v2")
```

适配器不会修改原始 CV 报告。Agent 的 `degraded` 状态会映射为后端
`agent_calls` 契约中的 `needs_review`。

当 CV 跟踪模块暂时把多片段输出保存为单独的 highlights JSON 时，可通过
`highlight_report` 参数做兼容接入：

```python
highlights = json.loads(
    Path("outputs/job_id/video_highlights.json").read_text(encoding="utf-8")
)
agent_report = service.run_analysis_report(
    cv_report,
    highlight_report=highlights,
    provider={"type": "ollama", "model": "qwen3:0.6b"},
    output_dir=Path("outputs/job_id"),
)
```

适配器会按源数组顺序为缺少 ID 的片段稳定生成 `seg_001`、`seg_002` 等编号，
但不会补造缺失的评分。最终编辑页评论至少包含
`segment_id/comment/evidence_refs`，并始终引用
`ev:segment:<segment_id>`；无评分或证据不足时状态为 `needs_review`。

模型返回无效引用、虚构事件或示例占位文本时，校验工具会拒绝模型草稿，记录错误并改用确定性输出。输入损坏时返回 `failed`；模型、Embedding 或落盘服务可恢复失败时返回 `degraded`。

专项测试：

```powershell
python -m unittest tests.test_agent_tools -v
python -m unittest tests.test_agent_workflow -v
python -m unittest tests.test_agent_contracts -v
```
