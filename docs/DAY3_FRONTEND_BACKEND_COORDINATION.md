# Day 3 前端实现完毕 — 需要后端对接的内容

> 前端工程师：唐鹏 (T-BB) | 日期：2026-07-26 | 分支：feature/frontend

---

## 已完成的前端实现（无需后端即可用 Mock 数据验证）

| 功能 | 涉及文件 | 说明 |
|---|---|---|
| 三态审核（通过/待复核/不通过） | editor.html, editor.js, editor.css | 片段详情面板中的三态按钮 + 审核备注 |
| 片段边界编辑 | editor.html, editor.js, editor.css | 起止时间输入框，含客户端校验 |
| 片段排序（上移/下移） | editor.html, editor.js, editor.css | 卡片上的 ↑↓ 按钮，自动更新 timeline |
| 统计仪表盘 | editor.html, editor.js, editor.css | 审核汇总、Agent 状态、分值分布柱状图、时长对比图、审核饼图 |
| 目标跟踪轨迹图 | editor.html, editor.js, editor.css | Canvas 轨迹可视化（有数据时绘制，否则显示"无跟踪数据"） |
| 导出与报告区域 | editor.html, editor.css | 分析报告/审核数据/粗剪 三张导出卡片 |
| 保存状态指示 | editor.html, editor.js | 未保存修改时按钮显示 ● 标记 + beforeunload 拦截 |
| 工作台统计图表 | index.html, app.js, style.css | 检测类别柱状图、片段分值图、轨迹图、下载链接区 |
| 所有 CSS 变量桥接 | editor.css | 确保 editor 页面变量与全局 style.css 一致 |

---

## 一、需要后端对接的具体事项

### 1. 审核写回接口扩展 (`PATCH /api/jobs/<job_id>/review`)

**现状**：当前后端 `_validate_segments()` 只校验 `id/start/end/order`，不感知 `review` 和 `review_note`。

**前端发送格式**：
```json
{
  "segments": [
    {
      "id": "seg_001",
      "start": 18.5,
      "end": 48.5,
      "order": 1,
      "review": "pass",
      "review_note": "确认为核心集锦片段"
    }
  ]
}
```

**后端需要做的**：
- 扩展 `_validate_segments()` 接受 `review`（值：`pass` / `needs_review` / `reject` / 空字符串）和 `review_note`（最长 500 字符）
- 将审核数据持久化到 `analysis_report.json` 或独立的 `review.json`
- 返回更新后的完整报告，以便前端刷新状态

---

### 2. Agent 逐片段评论生成 (`agent_report.json`)

**现状**：`GET /api/jobs/<job_id>/editor` 尝试读取 `agent_report.json` 中的 `segment_comments`，但目前 Agent 工作流尚未真正产出此文件。

**需要 Agent/工作流工程师 (姚博) 交付**：
```json
{
  "job_id": "20260725_...",
  "segment_comments": [
    {
      "segment_id": "seg_001",
      "status": "completed",
      "summary": "该片段包含多次击杀事件…",
      "tags": [{ "name": "多人交战", "description": "…", "evidence_refs": ["ref_001"] }],
      "suggestions": [{ "suggestion_id": "sug_001", "title": "…", "action": "…", "priority": "high", "evidence_refs": [], "knowledge_refs": [] }],
      "review": { "recommendation": "pass", "confidence": 0.78, "reasons": ["…"] },
      "evidence_refs": [{ "ref_id": "ref_001", "type": "detection", "source_id": "kf_003", "class_name": "person", "confidence": 0.72 }],
      "knowledge_refs": [{ "knowledge_id": "KB-FPS-001", "category": "精彩判定", "title": "多人交战事件定义" }]
    }
  ]
}
```

**状态值**：`completed`（有结果）、`pending`（进行中）、`unavailable`（失败/不可用，需含 `error` 字段）

前端已经完整处理了这三种状态的 UI 展示。

---

### 3. 多片段粗剪 (`POST /api/jobs/<job_id>/rough-cut`)

**现状**：当前粗剪接口基于 `recommended_clip` 单一时间范围。

**需要后端/CV 工程师做的**：
- 支持按 `segments[]` 数组中的已审核片段生成合并粗剪
- 前端流程：先 `PATCH /review` 保存审核和边界 → 再 `POST /rough-cut`
- 返回所有生成文件的相对路径列表

---

### 4. 轨迹数据接入

**现状**：前端已实现 Canvas 轨迹可视化，但当前 `analysis_report.json` 中关键帧没有轨迹数据。

**需要 CV 工程师 (韩玖原) 在报告中增加**：
```json
{
  "keyframes": [
    {
      "id": "kf_001",
      "timestamp": 14.0,
      "highlight_score": 0.55,
      "trajectory": [
        { "track_id": 1, "x": 320, "y": 240, "w": 80, "h": 120 },
        { "track_id": 2, "x": 800, "y": 300, "w": 60, "h": 90 }
      ]
    }
  ]
}
```

如果没有轨迹数据，前端会显示"目标跟踪数据不可用"占位状态，不会报错。

---

### 5. 审核状态持久化与恢复

**现状**：前端在内存中管理审核状态（`state.reviews`），刷新页面后丢失。

**需要后端做的**：
- `PATCH /api/jobs/<job_id>/review` 保存后在后续 `GET /api/jobs/<job_id>/editor` 中返回已保存的审核状态
- 聚合接口响应中增加 `reviews` 字段：
```json
{
  "reviews": {
    "seg_001": { "recommendation": "pass", "note": "已确认" },
    "seg_002": { "recommendation": "needs_review", "note": "" }
  }
}
```

---

### 6. 项目归属与权限校验

**现状**：编辑器页面路由 `/jobs/<job_id>/editor` 未做登录校验。

**需要后端做的**：
- 编辑页 API 需要登录态检查（`_require_user()`）
- 任务归属校验：用户只能编辑自己的任务
- 未登录用户访问编辑页时返回 401，前端已准备好处理

---

### 7. HTML/PDF 报告生成

**现状**：只有 JSON 格式的分析报告可下载。

**需要后端做的**：
- `GET /api/jobs/<job_id>/report?format=html` — 返回 HTML 分析报告
- `GET /api/jobs/<job_id>/report?format=pdf` — 返回 PDF 分析报告
- 前端导出区域已预留入口

---

### 8. 实时视频流支持（Range 请求）

**现状**：视频文件通过 `/outputs/<job_id>/<filename>` 静态服务。

**需要后端做的**：
- 支持 HTTP Range 请求，使 `<video>` 元素可以拖动定位
- 当前不支持的后果：视频播放器无法 seek，只能从头播放

---

## 二、API 契约确认清单

| 端点 | 当前状态 | Day 3 需要确认 |
|---|---|---|
| `GET /api/jobs/<job_id>/editor` | ✅ 已实现，返回 segments + agent_comments | 确认 `agent_comments` 字段名和 `reviews` 字段是否加入 |
| `PATCH /api/jobs/<job_id>/review` | ✅ 已实现，接受 segments | 确认接受 `review` + `review_note` 子字段 |
| `POST /api/jobs/<job_id>/rough-cut` | ✅ 已实现，单片段 | 确认多片段支持方案 |
| `GET /api/jobs/<job_id>/report` | ✅ 已实现，JSON | 确认 `?format=html` 和 `?format=pdf` 时间线 |
| 轨迹数据 | ❌ 未实现 | 确认 `keyframes[].trajectory` 数据结构 |
| Agent 报告 | ❌ 未产出 | 确认 `agent_report.json` 产出时间和 Schema |
| 审核持久化 | ❌ 未实现 | 确认 `reviews` 存储和返回方案 |

---

## 三、前端 Mock 数据说明

所有 Day 3 新增功能均可在 Mock 模式下完整运行：

- 编辑器访问 `/jobs/mock_20260725_143000_a1b2c3d4/editor`（任意 job_id 均可，API 失败时自动降级 Mock）
- 三态审核、边界编辑、排序、统计图、轨迹图均在 Mock 数据下可交互
- 保存/粗剪操作在 Mock 模式下会弹出"Mock 模式下无法保存"提示
- 统计图表基于 Mock 数据实时计算渲染

---

## 四、验收检查点

- [ ] 编辑页刷新后，已保存的审核状态和边界调整不丢失
- [ ] 时间轴标记与 JSON 中的秒数一致
- [ ] Agent `pending`/`unavailable`/`completed` 三种状态均有可读提示
- [ ] API 错误（4xx/5xx/网络超时）均有具体错误信息展示
- [ ] 未保存修改时离开页面有确认提示
- [ ] 三态审核按钮正确切换，卡片左边框颜色随之变化
- [ ] 边界编辑后时间轴标记实时更新
- [ ] 统计图表数值与原始数据一致
- [ ] 轨迹图在无数据时显示占位提示
