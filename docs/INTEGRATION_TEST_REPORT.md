# ReelFire Test-Glob 阶段性集成测试报告

## 1. 测试结论

当前 `Test-Glob` 已完成已上传代码的阶段性集成，前端、后端、CV 引擎、任务持久化和 FFmpeg 粗剪可以形成真实闭环。由于其他成员代码尚未全部上传，本报告只证明当前分支可联调，不表示项目最终验收完成，也不作为合并 `main` 的依据。

| 项目 | 结果 |
|---|---|
| Python 依赖 | `pip check` 通过，无损坏依赖 |
| Python 语法 | `py_compile` 通过 |
| JavaScript 语法 | `node --check static/app.js` 通过 |
| 自动化测试 | 35/35 通过 |
| 实际 HTTP 首页 | 200，包含 ReelFire 上传表单 |
| 实际健康接口 | 200，模型与 FFmpeg 均 ready |
| OpenCV 真实采样 | 通过 |
| YOLO 真实推理 | 通过（最终模型 `yolo11n.pt`，由初始化脚本下载） |
| 关键帧与边界 | 通过 |
| 联系表生成 | 通过 |
| 有音频 16:9 粗剪 | 通过 |
| 无音频 9:16 粗剪 | 通过 |
| 分支策略 | 仅推送 `Test-Glob`，不合并 `main` |

## 2. 集成内容

### 2.1 正常合并

- `feature/frontend`：基于当前 `main`，使用普通 merge；
- `main`：作为集成基线，已有后端 API 和任务服务。

### 2.2 选择性提取

- `test/qa-delivery`：只提取 QA 报告和测试素材，不带入旧历史；
- `master`：只提取 `cv_engine/` 与 CV 测试，不覆盖当前 `app.py`、服务层、前端和文档；
- `feature/backend-api`：主体已在 `main`，未重复合并；
- `docs-test`：内容已包含在 QA 增量中，未重复合并。

## 3. 自动化测试

执行命令：

```powershell
python -m py_compile app.py config.py routes/api_routes.py services/*.py cv_engine/*.py
node --check static/app.js
python -m unittest discover -s tests -v
python -m pip check
```

结果：

```text
Ran 35 tests
OK
No broken requirements found.
```

覆盖范围：

- 上传、空文件、扩展名和伪装格式；
- 任务创建、列表、详情、删除和状态恢复；
- 异步分析失败留档和重复提交；
- 人工审核、关键帧字段和 `segments` 边界；
- 粗剪结果写回任务与报告；
- YOLO 模型缺失提示和模型加载；
- 目标、场景变化、运动和综合分数；
- 关键帧时间去重；
- 片段靠近开头、靠近结尾、目标时长过长和无效时长。

## 4. 真实视频联调

测试素材：`tests/test_assets/gameplay_normal.mp4`

| 属性 | 结果 |
|---|---|
| 视频规格 | 1280×720，30 FPS，有音频 |
| ffprobe 时长 | 约 54.33 秒 |
| 联调采样间隔 | 2.0 秒（为缩短烟雾测试时间） |
| 实际采样帧 | 27 |
| YOLO 模型 | Ultralytics `yolo11n.pt` |
| 关键帧 | 5 张 |
| 推荐片段 | 20.0–35.0 秒 |
| 联系表 | 成功生成 |
| 16:9 粗剪 | 成功生成，约 11.56 MB |

真实联调调用的是 `services.analysis_service.analyze_video()` 和 `services.ffmpeg_service.create_rough_cut()`，没有使用模拟报告或伪造输出。

本地服务启动后还通过真实 HTTP 请求验证：`GET /` 返回 200 且包含上传表单，`GET /api/health` 返回 `model_ready: true` 与 `ffmpeg_ready: true`。完整浏览器回归已覆盖加载、运行、完成、失败、审核写回、输出视频和历史任务，浏览器控制台错误与失败请求均为 0，证据见 `Acceptance_screenshot/`。

## 5. 无音频兼容测试

测试素材：`tests/test_assets/gameplay_no_audio.mp4`

| 项目 | 结果 |
|---|---|
| ffprobe/OpenCV 音轨判断 | `has_audio: false` |
| 输出规格 | 9:16 |
| 测试片段 | 0–3 秒 |
| FFmpeg 结果 | 成功 |
| 输出大小 | 459,356 字节 |

FFmpeg 使用可选音轨映射 `0:a?`，源视频没有音频时不会导致任务失败。

## 6. 本轮修复的集成问题

1. 前端 `output_aspect` 与后端 `output_ratio` 不一致；
2. 前端未解包任务详情响应中的 `job`；
3. 创建任务后前端没有调用分析接口；
4. 普通 JSON POST 没有执行 `JSON.stringify`；
5. 前端发送 `segments`，后端只接受 `recommended_clip`；
6. 人工审核会丢失关键帧分数字段；
7. 粗剪完成后输出路径没有写回分析报告；
8. 关键帧和视频缺少安全的 `/outputs/` 访问路由；
9. 原 FFmpeg 和 CV `NotImplementedError` 占位已替换为真实实现；
10. 上传层只看扩展名，伪装文件可以进入任务系统。

## 7. 当前限制

- 项目最终使用通用 `yolo11n.pt`，不自训练；其 FPS 专用事件识别能力有限，报告只展示真实 COCO 类别；
- 其他成员尚未上传的代码没有进入本分支；
- 多片段合并、1:1、ZIP 和封面 Prompt 仍属于 P1；
- 当前真实联调结果保存在本机 `outputs/integration_smoke/`，该目录被 `.gitignore` 排除；
- 模型文件被 `.gitignore` 排除，不会推送到 GitHub；`setup_environment.py` 会自动下载并校验；
- 第一轮 QA 报告中的占位结论保留为历史记录，以本报告作为当前状态依据。

## 8. 后续接入规则

其他成员代码上传后：

1. 从远程更新目标功能分支；
2. 确认分支是否基于当前 `main/Test-Glob`；
3. 有共同祖先时正常 merge；
4. 无共同祖先时只提取有效提交或文件；
5. 每次接入后重新执行 35 项测试和真实视频烟雾测试；
6. 在所有成员代码到齐并通过最终验收前，不将 `Test-Glob` 合并到 `main`。
