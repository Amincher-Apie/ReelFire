# ReelFire Agent 模块

`agent/` 独立负责把 CV 流程生成的 `analysis_report.json` 转换为有证据引用的内容摘要、知识规则和审核建议。模型或向量服务失败不能修改原始 CV 报告。

## Day 02 工具节点

当前已实现两个基础工具：

- `ReportParserTool`：校验输入、关键帧、检测结果和片段边界，生成受控视觉摘要及稳定的 `evidence_ref`；
- `KnowledgeRetrieverTool`：构建内存向量索引，执行向量召回和规则重排；Embedding 不可用时自动返回 `degraded` 并使用确定性规则检索。

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

专项测试：

```powershell
python -m unittest tests.test_agent_tools -v
```
