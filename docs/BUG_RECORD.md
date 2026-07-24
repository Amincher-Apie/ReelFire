# Bug 记录 | BUG_RECORD

## 基本信息

| 项目 | 内容 |
|------|------|
| 项目名称 | ReelFire - 智能视频精彩片段提取系统 |
| 历史记录协作 | Agent/工作流工程师 |
| 最终回归组织 | 产品与项目负责人、集成测试 |
| 记录日期 | 2026-07-18 |

---

## Bug 清单

### BUG-001

| 项目 | 内容 |
|------|------|
| 问题现象 | 上传层未校验文件内容魔数（Magic Number），将 PNG 图片改名 .mp4 后被接受并创建任务 |
| 复现步骤 | 1. 准备 fake_video.mp4（PNG 文件头 41 字节，改名 .mp4） 2. POST /api/jobs 上传 3. 返回 201 Created |
| 原因分析 | file_service.py 的 validate_file 方法仅检查扩展名是否在 ALLOWED_VIDEO_EXTENSIONS 集合中，未读取文件头魔数校验实际格式 |
| 修复方案 | 在 `FileService.save_upload` 中增加容器签名校验：MP4/MOV 检查 `ftyp`，AVI 检查 `RIFF/AVI`，MKV 检查 EBML 文件头；不合规时删除已保存文件并返回 `FileValidationError` |
| 验证结果 | `test_create_job_rejects_spoofed_video_extension` 通过；伪装 PNG 返回 400，临时任务目录已清理 |

---

### BUG-002

| 项目 | 内容 |
|------|------|
| 问题现象 | 前端创建任务后没有启动分析；任务详情始终读不到状态；保存审核时后端返回“不支持的审核字段 segments” |
| 复现步骤 | 1. 合并 `feature/frontend` 到集成分支 2. 上传视频 3. 打开任务详情 4. 尝试保存关键帧与片段审核 |
| 原因分析 | 前后端独立开发时未遵守同一契约：前端发送 `output_aspect/segments`，后端使用 `output_ratio/recommended_clip`；详情接口返回 `{ok,job}`，前端却直接读取顶层状态；非 FormData POST 也没有 JSON 序列化 |
| 修复方案 | 前端统一使用 `output_ratio`、创建后调用 analyze、解包 `data.job` 并正确序列化 JSON；后端兼容并验证 `segments`，同步生成 `recommended_clip`，粗剪后将输出路径写回报告 |
| 验证结果 | 30 项自动化测试全部通过；审核 `segments/keyframes` 写回测试和粗剪报告更新测试通过 |

---

### BUG-003

| 项目 | 内容 |
|------|------|
| 问题现象 | `project_name` 和关键帧备注被持久化后直接拼入前端 `innerHTML`/HTML 属性，恶意 `<img onerror=...>` 载荷可能在任务列表或结果页重新打开时执行 |
| 复现步骤 | 1. 创建任务时把项目名设为 `<img src=x onerror="window.__reelfireProjectXss=1">` 2. 打开任务列表 3. 将类似载荷保存为关键帧备注并重新加载报告 |
| 原因分析 | 动态文本未经上下文转义便进入 HTML 字符串，同时关键帧操作依赖拼接式内联事件处理器，扩大了属性注入面 |
| 修复方案 | 对所有进入 HTML 文本或属性的动态值统一编码；任务与关键帧按钮改用 `addEventListener`；可变 ID 查询改为安全的 `dataset` 精确匹配；外部链接增加 `rel="noopener"` |
| 验证结果 | 浏览器回归分别注入项目名和持久化备注载荷，重新渲染后载荷保持纯文本且脚本标记未产生；控制台错误与失败请求均为 0 |

---

## 统计

| 统计项 | 数量 |
|------|------|
| 已发现 | 3 |
| 已修复 | 3 |
| 待修复 | 0 |
