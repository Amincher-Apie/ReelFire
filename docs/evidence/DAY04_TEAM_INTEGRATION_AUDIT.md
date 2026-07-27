# Day 04 团队集成与发布审计

## 1. 审计基线

| 角色 | 远端分支 | 审计提交 |
| --- | --- | --- |
| Agent/工作流 | `feature/agent-reliability-day04` | `e540344` |
| 后端 | `feature/backend-day4-integration-7.27` | `32e6a15` |
| CV/数据 | `feat/cv-algorithm-v2` | `3ce8222` |
| 前端 | `feature/frontend` | `10a055a` |

审计只记录公开分支、契约和测试结果，不包含应用 API Key、模型供应商 Key、
个人身份或本机绝对路径。

## 2. 后端联合验证

Agent 分支与最新后端分支可以自动合并，仅共同修改 `docs/API.md`，没有内容冲突。
在不创建合并提交的临时工作树中运行：

```powershell
python -m unittest `
  tests.test_agent_call_persistence `
  tests.test_report_data_api `
  tests.test_statistics_api `
  tests.test_streaming_report_compatibility -v
```

结果为 `37` 项通过、`0` 项失败。说明 Agent 的最终报告、调用生命周期和后端
`report-data/statistics` 接口可以共同运行。

## 3. 前端契约阻塞

最新前端仍请求：

```http
GET /api/jobs/{job_id}/editor
```

并把 `agent_report.json.segment_comments[]` 直接作为完整 Agent 展示对象使用，
期待每项具有：

```text
status / summary / tags / suggestions / review / evidence_refs
```

正式 Agent 逐片段评论实际为：

```text
segment_id / title / comment / score_reason / review_status / evidence_refs
```

因此直接合并后，前端会因为缺少 `comment.status` 而把已有评论显示为
“待 Agent 分析”或“Agent 不可用”，同时 `summary/tags/suggestions/review`
也无法从逐片段对象获得。

## 4. 推荐的唯一发布契约

统一使用最新后端接口：

```http
GET /api/jobs/{job_id}/report-data
```

前端基础映射：

```text
payload.report_data.cv.segments
  -> 时间轴和片段列表

payload.report_data.agent.availability
payload.report_data.agent.status
  -> Agent 整体状态

payload.report_data.agent.segment_comments[]
  -> 按 segment_id 匹配逐片段 comment/review_status/evidence_refs
```

为了满足现有前端的完整 Agent 详情面板，后端还需从经过校验的
`agent_report.json` 白名单公开：

```text
tags / suggestions / review / evidence_refs
```

前端不得从 `agent_calls.result`、CV 类别或大模型原始响应自行拼接评论。

## 5. CV 集成状态

最新 CV 分支已经输出统一片段字段：

```text
id / order / start / end / score / source_keyframes
detected_classes / enemy_classes_in_segment
detections_summary / peak_enemy_count / reason
```

这些字段在 Agent 解析器中已有校验与受控摘要映射。CV 与 Agent 分支同时修改了
`highlight_extractor.py`、`analysis_service.py`、`docs/API.md` 和
`docs/CV_segments.md` 等文件，不能在任一功能分支中直接选择 ours/theirs。
应由组长的集成分支逐文件保留双方功能后运行 CV、Agent 和 API 联合回归。

`character_ct` 和 `character_t` 只能描述为 CT/T 角色；只有 CV 类别明确为
`enemy` 时，Agent 才能使用“敌人”一词。击杀、爆头、胜负和武器事实仍必须有
对应检测或证据编号。

## 6. 发布前阻塞清单

1. 后端确认 `report-data.agent` 是否增加
   `tags/suggestions/review/evidence_refs` 白名单字段。
2. 前端改为读取 `report-data`，不得把 `segment_comments[]` 当完整报告。
3. 组长建立集成分支并依次合并后端、Agent、CV、前端，解决 CV/前端核心文件冲突。
4. 合并后运行 Agent/后端联合测试、前端浏览器验收和 CV 可运行测试。
5. 部署环境通过环境变量注入 Dify 应用 Key；不得把 Key 写入 Git、镜像或前端代码。
6. 线上执行一个真实视频任务，确认：
   `CV completed -> Agent Dify -> report-data -> Editor -> rough cut`。

