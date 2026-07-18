---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 865769157893023abaf4ed66de1097ad_626f1b16828711f180b3525400bff409
    ReservedCode1: 4VVsPsXWzm8coJk5FVrPNTTOPjp8q3RkmhvmosxKALxcczRzayXkNGcNL17ZSJz76eXpkclIIDEXxa41HYTdThiewxtMxJKfwAbggIze62qhrkVn5f8Xv7uLjoKL3fX0JC61otiWbLRNU2QfpfQ/vLXlIYX6+KmatYqfpHOgSvrV0nMJGuyz9iBRqZI=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 865769157893023abaf4ed66de1097ad_626f1b16828711f180b3525400bff409
    ReservedCode2: 4VVsPsXWzm8coJk5FVrPNTTOPjp8q3RkmhvmosxKALxcczRzayXkNGcNL17ZSJz76eXpkclIIDEXxa41HYTdThiewxtMxJKfwAbggIze62qhrkVn5f8Xv7uLjoKL3fX0JC61otiWbLRNU2QfpfQ/vLXlIYX6+KmatYqfpHOgSvrV0nMJGuyz9iBRqZI=
---

# Bug 记录 — ReelFire

| ID | 标题 | 严重等级 | 发现时间 | 状态 |
|----|------|----------|----------|------|
| BUG-001 | 上传层未校验文件魔数 | 中 | 2026-07-18 | 待修复 |
| BUG-002 | project_name 存储型 XSS | 高 | 2026-07-18 | 待修复 |

---

## BUG-001 — 上传层未校验文件魔数

- **触发条件**：将 PNG 文件重命名为 `.mp4` 后上传
- **期望行为**：后端应读取文件头魔数（如 `ftyp` box）判断是否为真实 MP4，拒绝伪造文件
- **实际行为**：`fake_video.mp4`（PNG 头，改扩展名 .mp4）被上传层接受，返回 201
- **影响范围**：所有上传入口，后续分析阶段会因无法解码而失败，但浪费存储与调度资源
- **建议修复**：在 `file_service.py` 上传入口增加魔数校验，至少验证 ISO BMFF 或 WebM 容器签名

---

## BUG-002 — project_name 存储型 XSS

- **触发条件**：创建任务时，project_name 填入 `<script>alert(1)</script>` 等 HTML/JS 载荷
- **期望行为**：后端应对用户输入做 HTML 实体转义（`<` → `&lt;` 等），前端渲染时使用 `textContent` 而非 `innerHTML`
- **实际行为**：
  1. 后端直接存储原始载荷到 `job.json`，API 响应中原样返回（`project_name: "<script>alert(1)</script>"`）
  2. 前端任务列表页将该值通过 `innerHTML` 或直接拼接到 HTML 中渲染，导致 `<script>` 标签嵌入 DOM
  3. 虽因浏览器安全策略未触发脚本执行，但存在绕过风险（如 `<img src=x onerror=...>`、SVG 载荷等）
- **影响范围**：任务列表页、任务详情页（详情页因特殊字符导致渲染异常，project_name 显示为 undefined）
- **验证步骤**：
  1. `POST /api/jobs` 上传任意文件，project_name 设为 `<script>alert(1)</script>`
  2. 打开前端任务列表页 → project_name 列显示为空白（载荷作为 HTML 元素被插入 DOM）
  3. 点击"查看"进入详情页 → 标题显示异常
- **建议修复**：
  1. 后端入库前对 project_name 做 HTML 实体编码或保留原始值不做转换
  2. 前端统一使用 `textContent` 渲染用户可控字段，或引入 DOMPurify 等 XSS 过滤库
*（内容由AI生成，仅供参考）*
