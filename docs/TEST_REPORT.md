# ReelFire 最终测试报告

## 1. 结论

2026-07-18 在 Windows 11、Conda `TestAI`、Python 3.11、NVIDIA CUDA、`yolo11n.pt` 与 FFmpeg 环境完成本机验收。

| 检查项 | 结果 |
|---|---|
| 自动化单元/接口测试 | 37/37 通过 |
| 本机正常/异常验收 | 10/10 通过（5 正常 + 5 异常） |
| 浏览器完整流程 | 通过 |
| 浏览器控制台错误 | 0 |
| 浏览器失败请求 | 0 |
| 有音频 16:9 粗剪 | 通过 |
| 无音频 9:16 粗剪 | 通过，1080×1920 |
| 真实 Bug | 2 项，均已回归 |

完整浏览器流程的成功任务为 `20260718_163104_bed0ce69`，损坏视频失败任务为 `20260718_163203_53a26fda`。运行产物保存在本机 `outputs/`，截图保存在 `docs/Acceptance_screenshot/`。

## 2. 测试环境

| 项目 | 配置 |
|---|---|
| 操作系统 | Windows 11 |
| Python | 3.11.15 |
| Conda 环境 | `TestAI`（复用环境） |
| PyTorch | 2.11.0+cu128，CUDA 可用 |
| OpenCV | 4.13.0 |
| Ultralytics | 8.4.95 |
| 模型 | 官方 `yolo11n.pt`，SHA-256 校验通过 |
| 浏览器 | Microsoft Edge，无头自动化回归 |
| 视频工具 | FFmpeg + ffprobe |

## 3. 五条正常场景

| ID | 场景 | 操作与预期 | 实际证据 | 结果 |
|---|---|---|---|---|
| N-01 | 健康检查 | 启动服务后读取 `/api/health` | HTTP 200，`model_ready=true`、`ffmpeg_ready=true` | PASS |
| N-02 | 页面及静态资源 | 打开首页、加载 CSS/JS/favicon | 首页与 favicon 均 200；浏览器无失败请求 | PASS |
| N-03 | 无音频真实分析 | 上传 `gameplay_no_audio.mp4`，2 秒采样，执行 YOLO | 任务 `20260718_163000_71c79c0d` 完成；采样 27 帧，关键帧 8 张，片段标签 3 类 | PASS |
| N-04 | 人工审核写回 | 修改关键帧 `decision/note` 与片段边界后保存 | PATCH 200，刷新报告后修改仍存在 | PASS |
| N-05 | 无音频 9:16 粗剪 | 对完成任务生成竖屏输出并用 ffprobe 检查 | `rough_cut_9x16.mp4`，1080×1920，4,867,266 字节 | PASS |

浏览器另使用有音频 `gameplay_normal.mp4` 跑通上传、`running`、`completed`、检测框关键帧、审核和 16:9 粗剪，证据见截图 03～06。

## 4. 五条异常场景

| ID | 场景 | 预期 | 实际错误/状态 | 结果 |
|---|---|---|---|---|
| E-01 | 缺少上传文件 | HTTP 400 | `缺少必填的 file 字段` | PASS |
| E-02 | `.txt` 扩展名 | HTTP 400 | `不支持的文件格式` | PASS |
| E-03 | PNG 伪装为 MP4 | 上传阶段 HTTP 400 | `文件内容与视频格式不匹配或文件已损坏` | PASS |
| E-04 | `start >= end` | 审核接口 HTTP 400 | `segments[0] 必须满足 0 <= start < end` | PASS |
| E-05 | 含 `ftyp` 但无法解码 | 创建后分析进入 `failed`，保留错误 | 任务 `20260718_163012_fa027f5c`：`无法读取视频信息，文件可能已损坏或不受支持` | PASS |

浏览器失败页面证据见 `07_failed.png`，历史列表中同时展示完成与失败状态，见 `08_task_history.png`。

## 5. 浏览器完整回归

执行脚本：

```powershell
npm install
npm run test:browser
```

该命令只用于 QA 浏览器复测，需要本机已安装 Microsoft Edge；项目正常运行不依赖 Node.js。脚本实际操作上传表单和页面按钮，不直接伪造完成结果。覆盖顺序：

```text
首页 -> 列表加载 -> 上传真实视频 -> running
     -> completed -> 检测框关键帧 -> 审核写回
     -> 生成粗剪 -> 输出视频 -> 损坏视频 failed -> 历史任务
```

| 截图 | 内容 |
|---|---|
| `01_upload_ready.png` | 上传表单就绪 |
| `02_loading.png` | 任务列表加载状态 |
| `03_running.png` | 真实 YOLO 后台分析中 |
| `04_completed.png` | 完成状态、评分、片段与关键帧 |
| `05_detection_keyframe.png` | 最终 YOLO11n 检测框、类别数量和三项分数 |
| `06_output_video.png` | 粗剪视频与联系表输出区 |
| `07_failed.png` | 损坏视频失败状态与可读错误 |
| `08_task_history.png` | 完成/失败历史任务重开入口 |

## 6. 自动化与复现命令

```powershell
python -m unittest discover -s tests -v
python -m tests.local_acceptance
python -m pip check
node --check static/app.js
```

结果分别为 37/37、10/10、无损坏依赖、JavaScript 语法通过。浏览器回归还会打开 JSON 报告并校验 `segment_tags` 与 `ai_cover_prompt` 存在。

## 7. Bug 回归与限制

两个真实 Bug 的现象、原因、修复和回归见 `BUG_RECORD.md`：伪装格式上传和前后端字段契约不一致均已修复。

项目最终采用通用 `yolo11n.pt`，不自训练。它能输出真实 COCO 类别、置信度和边界框，但不宣称识别击杀、残局等 FPS 专用事件；精彩分数还结合场景变化和运动强度，以降低单一通用类别的局限。
