# Dify 配置交接与测试约定

## 是否需要在本机启动 Dify

不一定。

- 使用 Dify Cloud 时，`DIFY_BASE_URL=https://api.dify.ai`，本机不需要启动
  Dify。
- 使用团队自建 Dify 时，`DIFY_BASE_URL` 必须填写测试机器能够访问的服务地址。
  除非 ReelFire 与 Dify 运行在同一台机器，否则不能填写 `localhost` 或
  `127.0.0.1`。
- 当前 ReelFire 适配器调用 Chat/Chatflow/Agent 应用的
  `/v1/chat-messages`。如果团队发布的是 Workflow 应用，需要改用
  `/v1/workflows/run`，不能只替换 API Key。

## 可以进入 Git 的内容

- `.env.example` 中的变量名和非敏感示例值。
- Dify 应用类型、输入输出字段、Prompt 版本和发布版本说明。
- 经检查不含密钥、个人信息和私有地址的 Dify DSL 导出文件。
- 本文档以及接口契约、失败码和联调步骤。

## 不能进入 Git 的内容

- `.env`。
- `DIFY_API_KEY` 的真实值。
- Dify 管理员密码、模型供应商密钥或知识库私有凭据。
- 只能在成员个人电脑上访问的私有地址。

真实密钥应通过团队批准的密码管理器、加密传输工具或 GitHub
Environment/Repository Secret 交接。推荐为不同测试环境创建可撤销的独立
应用 Key，不共享管理员凭据。

## Agent 开发成员需要交接的信息

1. 部署方式：Dify Cloud 或自建服务。
2. 可访问的 `DIFY_BASE_URL`。
3. 应用类型：Chatbot、Chatflow、Agent 或 Workflow。
4. 已发布应用的 API Key；只通过安全渠道传递。
5. 应用发布版本、Prompt 版本和期望 JSON 输出契约。
6. 若使用自建 Dify，提供网络访问条件、TLS 证书要求和健康检查地址。
7. 可选：不含秘密的 Dify DSL 导出文件，用于重建应用。

## 本地配置

复制示例文件后，仅在本机填写：

```powershell
Copy-Item .env.example .env
```

```dotenv
AGENT_PROVIDER=dify
DIFY_BASE_URL=https://api.dify.ai
DIFY_API_KEY=<通过安全渠道取得的应用 Key>
DIFY_USER=reelfire-test
DIFY_MODEL_LABEL=dify-chat-app
```

修改 `.env` 后必须重启 ReelFire。配置只在 Python 进程启动时加载。

## 验收标准

1. 使用相同 Key 请求 `GET {DIFY_BASE_URL}/v1/info` 返回 HTTP 200。
2. YOLO 完成后，ReelFire 自动创建一条 Agent 调用记录。
3. 调用状态依次进入 `queued`、`running`，最终为 `completed` 或
   `needs_review`。
4. 任务目录生成 `agent_report.json` 与 `agent_trace.json`。
5. Editor 展示每个片段的最终评论。
6. 若在线调用失败，页面明确显示失败或规则降级，而不是长期显示“分析中”。

常见问题：

- HTTP 401：Key 无效、已撤销，或 Key 与 Dify 服务地址不匹配。
- HTTP 403 / Cloudflare 1010：请求特征或网络出口被网关拒绝。
- HTTP 404：`DIFY_BASE_URL` 或应用类型对应的 API 路径错误。
- 有调用记录但只有规则结果：查看调用详情中的 `risk_flags`，检查是否包含
  `model_generation_failed` 或 `model_provider_not_configured`。
