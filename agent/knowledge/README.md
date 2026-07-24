# ReelFire 媒体审核知识库

`media_review_rules.json` 是 Agent 的第一类知识库，覆盖检测证据、画面质量、精彩度指标、常见 COCO 类别和审核风险。

## 混合检索流程

Day 02 的知识库工具采用“向量召回 + 规则重排”的混合检索：

1. 将 `title`、`category`、`keywords`、`summary_guidance`、`suggestions` 和 `limitations` 拼接为知识条目文本；
2. 默认通过 Ollama Embedding 接口生成条目向量和查询向量；
3. 使用 NumPy 计算余弦相似度并召回 Top-K；
4. 使用 `match.detected_classes`、`match.metrics` 和关键词命中进行规则重排；
5. 无论是否向量命中，都加载 `match.always_apply` 为 `true` 的基础规则；
6. 返回 `knowledge_id`、`similarity` 和 `match_reasons`，供 Agent 输出引用。

默认 Embedding 配置从环境变量读取：

```text
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_EMBED_MODEL=<本机实际安装的 Embedding 模型>
```

不在仓库中固定不存在的模型，也不提交模型文件。可使用 `nomic-embed-text`、`bge-m3` 或其他实际可运行的 Embedding 模型，但最终报告必须记录真实模型名称。

Dify 或 Coze 已配置知识库时，可以通过适配器返回平台的向量召回结果；平台结果仍要转换为统一的 `knowledge_id`、相似度和命中原因。

当 Embedding 服务超时、模型缺失或平台不可用时，工具降级为以下确定性检索：

- `keywords`：中文或英文关键词；
- `match.detected_classes`：CV 报告中的真实 YOLO 类别；
- `match.metrics`：受控视觉摘要中的指标条件；
- `match.always_apply`：每次工作流都应加载的基础规则。

降级结果必须标记 `degraded`，不能伪装成向量检索成功。工具返回完整条目时必须保留 `knowledge_id`；没有命中的条目不能出现在引用中。

## 检索配置

`media_review_rules.json` 的 `retrieval` 节点冻结了 Day 02 的实现契约：

- `strategy`：`hybrid`；
- `embedding`：提供方、模型环境变量、索引文本字段；
- `vector_search`：余弦相似度、Top-K 和最低分；
- `rule_rerank`：类别、指标、关键词和常驻规则的加分；
- `fallback`：向量失败时的确定性检索模式。

## 维护规则

- 每个 `knowledge_id` 全局唯一；
- `review_recommendation` 只能是 `pass`、`needs_review` 或 `reject`；
- 建议必须说明所需证据，不得把推断写成检测事实；
- 新增类别时优先使用 YOLO 报告中的真实类名；
- 向量检索结果必须保留真实相似度，不能人工伪造；
- 最终演示至少保存一组向量召回与一组降级召回结果；
- 修改知识库后运行 `python -m unittest tests.test_agent_assets -v`。

## 当前范围

当前知识库用于课程 MVP 和通用媒体审核，不声称识别 FPS 击杀、爆头、武器或胜负。需要这类能力时，应先由 CV 侧提供可验证的新模型类别或结构化事件证据。
