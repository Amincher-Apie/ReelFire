# ReelFire Agent 模块

`agent/` 独立负责把 CV 流程生成的 `analysis_report.json` 转换为有证据引用的内容摘要、知识规则和审核建议。模型或向量服务失败不能修改原始 CV 报告。

## Day 02 工具节点

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
5. 原子写入 `agent_report.json` 和脱敏后的 `agent_trace.json`。

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
backend_record = to_backend_agent_call(agent_report, prompt_version="v1")
```

适配器不会修改原始 CV 报告。Agent 的 `degraded` 状态会映射为后端
`agent_calls` 契约中的 `needs_review`。

模型返回无效引用、虚构事件或示例占位文本时，校验工具会拒绝模型草稿，记录错误并改用确定性输出。输入损坏时返回 `failed`；模型、Embedding 或落盘服务可恢复失败时返回 `degraded`。

专项测试：

```powershell
python -m unittest tests.test_agent_tools -v
python -m unittest tests.test_agent_workflow -v
python -m unittest tests.test_agent_contracts -v
```
