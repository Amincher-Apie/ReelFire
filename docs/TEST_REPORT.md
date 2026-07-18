# 测试报告 | TEST_REPORT

> 本文件保留后端第一轮测试的原始记录。CV、FFmpeg 与前端完成阶段性接线后的最新结果见 [`INTEGRATION_TEST_REPORT.md`](INTEGRATION_TEST_REPORT.md)。第一轮中的“占位实现/阻塞”描述不代表当前 `Test-Glob` 状态。

## 基本信息

| 项目 | 内容 |
|------|------|
| 项目名称 | ReelFire - 智能视频精彩片段提取系统 |
| 方向 | B |
| 记录角色 | 测试工程师 |
| 测试日期 | 2026-07-18 |
| 测试环境 | Windows 11, Python 3.x, conda yolo 环境 |

---

## 一、正常测试记录 (5条)

### T-001 正常视频上传并创建任务

| 项目 | 内容 |
|------|------|
| 场景 | 上传合法 MP4 视频（16:9，有音频），创建任务 |
| 前置条件 | 服务运行在 http://127.0.0.1:7880 |
| 步骤 | 1. POST /api/jobs 上传 gameplay_normal.mp4（53s, 1280×720, 30fps） 2. 验证 job.json 目录结构 3. GET /api/jobs 验证列表 4. GET /api/jobs/\<id\> 验证详情 |
| 预期结果 | 201 返回 job_id；job.json 含完整 settings、时间戳；目录创建 input/keyframes/result 子目录 |
| 实际结果 | 集成测试：201 Created，job_id=20260718_142718_e35ba612；列表接口返回 1 条记录；详情含完整 settings（16:9, target_duration=15.0, max_keyframes=5）；单元测试 test_create_job_persists_workspace_and_metadata 通过 |
| 通过/失败 | ✅ 通过 |

### T-002 关键帧查看与人工审核

| 项目 | 内容 |
|------|------|
| 场景 | 对已完成任务执行审核（review）操作 |
| 前置条件 | 任务已完成，存在 analysis_report.json |
| 步骤 | 1. 手动写入模拟 report（duration=10.0, keyframes=[]） 2. PATCH /api/jobs/\<id\>/review 3. 验证边界：start=8,end=11（超出范围）应返回 400 4. 正常审核：start=2,end=9,output_ratio=9:16 |
| 预期结果 | 无 report 时返回 409；越界返回 400；合法审核返回 200 并写入 recommended_clip |
| 实际结果 | 单元测试 test_review_requires_existing_report_and_validates_boundaries 通过：无 report→409，越界→400，合法审核→200（output_ratio=9:16 正确写入）。集成测试阻塞：CV 模块未接入，无真实 analysis_report.json |
| 通过/失败 | ⚠️ 单元测试通过，集成测试阻塞（CV未就绪） |

### T-003 粗剪视频输出

| 项目 | 内容 |
|------|------|
| 场景 | 基于审核后的关键帧调用粗剪接口 |
| 前置条件 | 任务已完成且有关键帧通过审核 |
| 步骤 | 1. 写入模拟 report（含 recommended_clip: start=1.0,end=8.0,ratio=16:9） 2. 模拟 ffmpeg 可用 3. POST /api/jobs/\<id\>/rough-cut |
| 预期结果 | 当前阶段返回 501（占位接口）；输出目录不产生虚假文件 |
| 实际结果 | 单元测试 test_rough_cut_placeholder_returns_501_without_fake_file 通过：返回 501，result/ 目录下无 rough_cut.mp4 文件。后端确认 FFmpeg 服务已预留接口但未实现 |
| 通过/失败 | ✅ 通过（501 占位行为符合预期） |

### T-004 历史任务重新打开

| 项目 | 内容 |
|------|------|
| 场景 | 通过任务编号重新打开之前已完成的任务 |
| 前置条件 | 之前至少有一个已完成任务 |
| 步骤 | 1. 创建任务获取 job_id 2. GET /api/jobs 验证列表包含该任务 3. GET /api/jobs/\<id\> 验证详情可访问 |
| 预期结果 | 任务列表和详情接口正常返回，数据完整 |
| 实际结果 | 集成测试：列表返回所有任务记录；详情返回完整 job 对象（含 job_id/project_name/asset_name/status/timestamps/settings）。单元测试 test_create_job_persists_workspace_and_metadata 中列表和详情断言均通过 |
| 通过/失败 | ✅ 通过 |

### T-005 删除已完成任务

| 项目 | 内容 |
|------|------|
| 场景 | 删除一个 created/failed 状态的任务 |
| 前置条件 | 存在 created 状态任务 |
| 步骤 | 1. 创建任务 2. DELETE /api/jobs/\<job_id\> 3. 检查任务列表和本地目录 |
| 预期结果 | 返回 200 ok；任务从列表中移除；本地 outputs/\<job_id\> 目录被清理 |
| 实际结果 | 集成测试：DELETE 返回 ok=true, deleted_job_id 确认；outputs/ 目录仅剩 .gitkeep。单元测试 test_delete_created_job 通过；test_delete_queued_or_running_job_returns_409 正确拒绝删除 queued/running 状态任务 |
| 通过/失败 | ✅ 通过 |

---

## 二、异常测试记录 (5条)

### T-006 上传非视频文件

| 项目 | 内容 |
|------|------|
| 场景 | 上传 fake_video.mp4（实际为改名后的 PNG 图片） |
| 前置条件 | 服务运行中 |
| 步骤 | 上传 fake_video.mp4（41字节 PNG 头，改名 .mp4） |
| 预期结果 | 返回明确错误提示，不创建任务，服务不崩溃 |
| 实际结果 | 集成测试：上传阶段接受文件并创建了任务（job_id=20260718_142730_a3829496），因扩展名 .mp4 在允许列表中。进入分析后返回 failed，error="CV 分析模块尚未接入"。说明格式深度校验依赖分析阶段，上传层仅校验扩展名。单元测试 test_create_job_with_unsupported_extension_returns_400 仅验证扩展名拦截（.txt 返回 400） |
| 通过/失败 | ⚠️ 部分通过：扩展名校验正常；建议上传阶段增加文件头魔数校验 | |

### T-007 上传空文件

| 项目 | 内容 |
|------|------|
| 场景 | 上传 0 字节文件 |
| 前置条件 | 服务运行中 |
| 步骤 | POST /api/jobs 上传 empty_file.mp4（0字节） |
| 预期结果 | 返回明确错误提示，任务不被创建 |
| 实际结果 | 集成测试：返回 {"ok":false,"error":"上传文件不能为空"}。单元测试 test_create_job_with_empty_file_returns_400_and_cleans_workspace 通过（400 返回 + 目录清理） |
| 通过/失败 | ✅ 通过 |

### T-008 模型文件缺失

| 项目 | 内容 |
|------|------|
| 场景 | YOLO 模型文件不存在时触发分析 |
| 前置条件 | models/yolo11n.pt 不存在；当前服务器 model_ready=false |
| 步骤 | 1. 确认 health 接口返回 model_ready=false 2. 上传正常视频 3. POST /api/jobs/\<id\>/analyze |
| 预期结果 | 任务进入 failed 状态；job.json 中 error 字段包含明确描述；服务进程不退出 |
| 实际结果 | 集成测试：analyze 返回 202 queued，3s 后任务 status=failed，error="CV 分析模块尚未接入，请由算法工程师实现 analyze_video"。health 接口仍然 ok。单元测试 test_analyze_returns_202_then_persists_clear_failure 通过（assert job["status"]=="failed"，error 含 "CV 分析模块尚未接入"） |
| 通过/失败 | ✅ 通过 |

### T-009 删除正在运行的任务

| 项目 | 内容 |
|------|------|
| 场景 | 尝试删除 queued 或 running 状态的任务 |
| 前置条件 | 存在一个 queued 状态任务 |
| 步骤 | 1. 将任务状态手动设为 queued 2. DELETE /api/jobs/\<id\> |
| 预期结果 | 返回 409 Conflict，任务继续存在不受影响 |
| 实际结果 | 单元测试 test_delete_queued_or_running_job_returns_409 通过：返回 409，任务目录仍存在（assert is_dir）。集成测试：因无法在真实环境中将任务锁定在 queued 状态，未做 HTTP 层验证 |
| 通过/失败 | ✅ 通过（单元测试） |

### T-010 无音频视频处理

| 项目 | 内容 |
|------|------|
| 场景 | 上传无音频轨道的视频 |
| 前置条件 | gameplay_no_audio.mp4（去音频副本，11.1MB） |
| 步骤 | POST /api/jobs 上传 gameplay_no_audio.mp4 |
| 预期结果 | 上传成功，任务创建 |
| 实际结果 | 集成测试：返回 201 Created, job_id=20260718_142802_00615502。分析阶段阻塞（CV未就绪）。粗剪阶段阻塞（FFmpeg 未就绪） |
| 通过/失败 | ⚠️ 上传阶段通过；分析/粗剪阻塞（CV + FFmpeg 未就绪） |

---

## 三、方向B专项边界测试

### T-011 最高分关键帧靠近视频开头

| 项目 | 内容 |
|------|------|
| 场景 | 精彩帧出现在视频前3秒，验证推荐片段不会过短 |
| 前置条件 | CV 模块就绪，能生成真实 keyframes |
| 步骤 | 上传并分析该视频，查看推荐片段的 start 时间 |
| 预期结果 | 推荐片段仍包含合理时长（非仅2~3秒），start >= 0 且合法 |
| 实际结果 | 阻塞：CV 分析模块未接入，无法生成 keyframes |
| 通过/失败 | ⏸️ 阻塞（等待 CV 模块） |

### T-012 最高分关键帧靠近视频结尾

| 项目 | 内容 |
|------|------|
| 场景 | 精彩帧出现在视频最后3秒 |
| 前置条件 | CV 模块就绪 |
| 步骤 | 上传并分析该视频，查看推荐片段 |
| 预期结果 | end <= video_duration，不出现 end > duration 或崩溃 |
| 实际结果 | 阻塞：CV 分析模块未接入 |
| 通过/失败 | ⏸️ 阻塞（等待 CV 模块） |

### T-013 目标片段时长超过原视频时长

| 项目 | 内容 |
|------|------|
| 场景 | 用户设置目标片段时长为 60s，但视频只有 15s |
| 前置条件 | 15s 短视频 + CV 模块就绪 |
| 步骤 | 上传该视频，设 target_duration=60.0 |
| 预期结果 | 系统降级处理，输出不超过视频实际时长 |
| 实际结果 | 阻塞：CV 分析模块未接入。但 settings 中的 target_duration 参数已通过 API 正确传递 |
| 通过/失败 | ⏸️ 阻塞（等待 CV 模块） |

---

## 四、测试总结

### 4.1 统计

| 统计项 | 数量 |
|------|------|
| 正常测试 | 3/5 通过，2 阻塞（T-002审核/T-003粗剪 单元测试通过，集成阻塞于CV） |
| 异常测试 | 3/5 通过，2 部分通过（T-006 魔数校验建议、T-010 阻塞于CV+FFmpeg） |
| 边界测试 | 0/3 通过，3 阻塞（全部依赖CV模块就绪） |
| 单元测试 | 16/16 全部通过（0.653s） |
| 集成测试 | 8/8 可测接口全部通过 |
| 发现 Bug | 1（T-006：上传层未校验文件魔数，假视频被接受） |
| 整体结论 | 后端 v0.1 基础架构扎实，API 规范完整，阻塞项均为 CV+FFmpeg 模块未就绪 |

### 4.2 阻塞项清单

| 阻塞项 | 影响测试 | 预计解除 |
|------|------|------|
| CV 分析模块（analyze_video 函数） | T-002, T-010, T-011, T-012, T-013 | 算法工程师实现 |
| FFmpeg 可用性 | T-003, T-010 | 安装 FFmpeg 并配置 PATH |
| YOLO 模型文件（yolo11n.pt） | T-001 完整流程, T-008 | 下载 / models/ 目录 |

### 4.3 单元测试覆盖详情

| 测试方法 | 状态 |
|------|------|
| test_health | ✅ |
| test_create_job_persists_workspace_and_metadata | ✅ |
| test_create_job_without_file_returns_400 | ✅ |
| test_create_job_with_empty_file_returns_400_and_cleans_workspace | ✅ |
| test_create_job_with_unsupported_extension_returns_400 | ✅ |
| test_invalid_settings_return_400_without_crashing | ✅ |
| test_get_missing_and_invalid_job_ids | ✅ |
| test_delete_created_job | ✅ |
| test_delete_queued_or_running_job_returns_409 | ✅ |
| test_analyze_returns_202_then_persists_clear_failure | ✅ |
| test_duplicate_analyze_returns_409 | ✅ |
| test_review_requires_existing_report_and_validates_boundaries | ✅ |
| test_rough_cut_placeholder_returns_501_without_fake_file | ✅ |
| test_startup_marks_interrupted_job_failed | ✅ |
| test_corrupt_report_returns_json_500_and_service_survives | ✅ |
| test_unknown_route_and_wrong_method_use_json_errors | ✅ |

### 4.4 附加集成测试（HTTP 层）

| 测试项 | 接口 | 结果 |
|------|------|------|
| 健康检查 | GET /api/health | ✅ ok=true, model_ready=false, ffmpeg_ready=false |
| 上传正常视频 | POST /api/jobs | ✅ 201, job_id 返回 |
| 任务列表 | GET /api/jobs | ✅ 返回 jobs 数组 |
| 任务详情 | GET /api/jobs/\<id\> | ✅ status/timestamps/settings 完整 |
| 空文件上传 | POST /api/jobs | ✅ 400 "上传文件不能为空" |
| 无文件上传 | POST /api/jobs | ✅ 400 "缺少必填的 file 字段" |
| 非法参数 | POST /api/jobs | ✅ 400 "sample_interval 必须是数字" |
| 缺失任务ID | GET /api/jobs/xxx | ✅ 404 "任务不存在" |
| 错误方法 | PUT /api/health | ✅ 405 "当前接口不支持该 HTTP 方法" |
| 删除任务 | DELETE /api/jobs/\<id\> | ✅ 200, deleted_job_id 返回 |
| 分析触发 | POST /api/jobs/\<id\>/analyze | ✅ 202 queued → failed (预期) |
