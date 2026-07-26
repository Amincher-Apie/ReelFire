# Dify Cloud Chatflow 配置与交接

本文档用于让另一台电脑在不接收模型供应商密钥、不把应用密钥写入 Git 的
前提下，运行 ReelFire 的真实 Dify 在线 Agent 链路。

## 1. 冻结配置

| 项目 | 固定值 |
|---|---|
| 部署 | Dify Cloud |
| 应用类型 | Chatflow |
| Dify 应用模式 | `advanced-chat` |
| 项目环境变量 | `DIFY_BASE_URL=https://api.dify.ai` |
| 实际消息接口 | `https://api.dify.ai/v1/chat-messages` |
| 响应方式 | `blocking` |
| 应用版本名 | `reelfire-chatflow-v1.0.0` |
| Prompt 版本 | `review_agent_v2` |
| 调用方用户标识 | `reelfire-demo` |

不得改用 Workflow 应用，因为 Workflow 使用另一套运行接口。也不得把当前
配置换成 Agent 应用；当前 ReelFire 适配器使用阻塞式 Chat API，交付时只验收
`advanced-chat` 模式的 Chatflow。

## 2. 密钥边界

需要交给运行 ReelFire 的成员的只有当前已发布 Chatflow 的“应用 API Key”。

- 该 Key 在 Dify 应用的“访问 API”页面创建；
- 它不是知识库 Service API Key；
- 它不是 DeepSeek、SiliconFlow、OpenAI 等模型供应商 Key；
- 模型供应商 Key 只保存在 Dify 工作区凭据中，不向 ReelFire 传递；
- 优先使用密码管理器的一次性分享；不得发到群聊、截图、DSL 或 Git；
- 接收方只把 Key 写入本机 `.env`，该文件已被 `.gitignore` 忽略。

跨电脑使用分为两种情况：

- **共用现有 Dify Cloud 应用**：接收方不需要登录应用所在工作区，只需要仓库、
  已发布应用的 API Key 和可用的 `analysis_report.json`；
- **在接收方自己的 Dify 工作区重建**：接收方导入不含密钥的 DSL，安装 DSL
  声明的模型插件，在自己的工作区配置模型供应商凭据，发布 Chatflow，再创建
  自己的新应用 API Key。旧应用的 Key 不能用于新导入的应用。

当前 Chatflow 的知识上下文由 ReelFire 本地检索后放入 `query`，因此组长共用
现有应用时不需要额外获得 Dify 知识库 Service API Key。

## 3. 接收方电脑配置

在仓库根目录执行：

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

然后由接收方在自己的 `.env` 中填写应用 Key：

```dotenv
AGENT_PROVIDER=dify
DIFY_BASE_URL=https://api.dify.ai
DIFY_API_KEY=
DIFY_USER=reelfire-demo
DIFY_MODEL_LABEL=reelfire-chatflow-v1.0.0
```

先验证 Key、部署地址和应用类型：

```powershell
python -m agent.check_dify
```

成功结果必须同时满足：

- `ok` 为 `true`；
- `mode` 为 `advanced-chat`；
- `chat_endpoint` 为 `https://api.dify.ai/v1/chat-messages`；
- `name` 是团队约定的 ReelFire Chatflow 应用。

错误解释：

| 现象 | 原因与处理 |
|---|---|
| HTTP 401 | Key 无效、已撤销、复制错误，或不是该应用的 API Key |
| `mode=workflow` | 给错了 Workflow 应用；不能用于当前适配器 |
| `mode=agent-chat` 或 `mode=agent` | 给错了 Agent 应用；当前阻塞调用不验收 |
| 连接到了其他域名 | Dify Cloud 地址填写错误，恢复为冻结配置 |

## 4. 输入契约

适配器向 Chatflow 发送：

```json
{
  "inputs": {},
  "query": "渲染后的 review_agent_v2 Prompt",
  "response_mode": "blocking",
  "conversation_id": "",
  "user": "reelfire-demo"
}
```

`query` 中包含 `job_id`、受控 `visual_summary_json`、
`knowledge_context_json`，以及允许使用的证据和知识编号白名单。Chatflow 不应
额外要求自定义输入字段，否则会与当前 `inputs: {}` 契约不兼容。

推荐 Chatflow 节点为：用户输入 `sys.query` → LLM → Answer。Answer 必须只返回
LLM 生成的 JSON 文本，不添加解释、标题或 Markdown。

## 5. 输出契约

Dify HTTP 响应的 `answer` 必须是可解析的 JSON 对象字符串。业务草稿至少包含：

```json
{
  "summary": "只描述可验证事实",
  "tags": [
    {
      "name": "真实检测类别",
      "description": "基于输入证据的说明",
      "evidence_refs": ["输入白名单中的证据编号"]
    }
  ],
  "suggestions": [
    {
      "suggestion_id": "SUG-001",
      "title": "建议标题",
      "action": "可执行操作",
      "priority": "medium",
      "evidence_refs": ["输入白名单中的证据编号"],
      "knowledge_refs": ["输入白名单中的知识编号"]
    }
  ],
  "segment_comments": [],
  "review": {
    "recommendation": "needs_review",
    "confidence": 0.8,
    "reasons": ["可追溯原因"]
  }
}
```

`review.recommendation` 只能为 `pass`、`needs_review`、`reject`。
模型输出的 `segment_comments` 不作为最终事实；本地 `RuleValidatorTool` 会根据
CV 的真实 `segments[]` 和 `ev:segment:<segment_id>` 重新生成最终评论。

## 6. 真实运行

先找到 CV 生成的真实报告，然后执行：

```powershell
python -m agent.run_agent `
  --analysis-report outputs/<job_id>/analysis_report.json `
  --output-dir outputs/<job_id> `
  --provider dify
```

验收时检查命令输出以及同目录的 `agent_report.json`、`agent_trace.json`：

- 调用轨迹中确实出现 Dify 提供方；
- 不出现 `model_generation_failed`；
- 标签、建议和审核理由使用合法证据引用；
- 最终逐片段说明的 `segment_id` 与 CV 输入完全一致。

知识检索仍在 ReelFire 本地执行。若接收方未运行 Ollama Embedding，系统会进入
确定性检索降级；Dify 调用仍可真实发生，但整条任务可能显示 `degraded`。若要
验收完整的 `completed` 链路，还需启动 Ollama 并准备 `.env.example` 中指定的
Embedding 模型。

## 7. 版本与 DSL 交付

1. 在 Dify 中把版本命名为 `reelfire-chatflow-v1.0.0` 并发布；
2. 发布后不要继续修改草稿；
3. 导出为 `reelfire_chatflow_v1.0.0.yml`；
4. 导出时不得包含 secret；
5. 交付前搜索 `api_key`、`token`、`secret` 并人工检查实际值为空；
6. 记录 DSL 文件的 SHA-256、发布时间和 Prompt 版本；
7. DSL 可以进入评审，但应用 API Key 仍只能安全私下传递。

在 Sandbox 套餐中始终运行最新发布版本。版本名、发布时间、DSL 哈希和真实
`/info` 验证结果共同作为本次交接证据。
