---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 865769157893023abaf4ed66de1097ad_617244b4828711f184135254006c9bbf
    ReservedCode1: vKzTTcAO6YXF7Ys+WiPv9p8ucn238bUQpemNV21mbYNOB13OQIIDfzfFSqIWeMAphOMdCu4FQsUC2cgctBhkKimIMIjf8jafZ3a/YWoq/VD6IPyjlkfScR2xpd/18auuRODqtwe+tGBYH4dJLkF+xOSY3k8MX+eeIe1p23Sv/VoGtHaZljv9CJ85iM0=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 865769157893023abaf4ed66de1097ad_617244b4828711f184135254006c9bbf
    ReservedCode2: vKzTTcAO6YXF7Ys+WiPv9p8ucn238bUQpemNV21mbYNOB13OQIIDfzfFSqIWeMAphOMdCu4FQsUC2cgctBhkKimIMIjf8jafZ3a/YWoq/VD6IPyjlkfScR2xpd/18auuRODqtwe+tGBYH4dJLkF+xOSY3k8MX+eeIe1p23Sv/VoGtHaZljv9CJ85iM0=
---

# 测试报告 — ReelFire

**版本**: v0.1.0  
**测试日期**: 2026-07-18  
**分支**: feature/backend-api  
**执行人**: Marvis（自动化测试）

---

## 1. 测试概览

| 类别 | 总数 | 通过 | 失败 | 通过率 |
|------|------|------|------|--------|
| 单元测试 (unittest) | 16 | 15 | 1 | 93.75% |
| HTTP 集成测试 (手动) | 11 | 11 | 0 | 100% |
| 端到端测试 | 1 | 1 | 0 | 100% |
| **合计** | **28** | **27** | **1** | **96.43%** |

---

## 2. 单元测试详情（16 项）

测试文件：`tests/test_api.py`  
框架：Python unittest  
命令：`python -m unittest tests.test_api -v`

| # | 测试用例 | 结果 | 说明 |
|---|----------|------|------|
| 1 | test_health | ✅ PASS | `/api/health` 返回 200，服务正常运行 |
| 2 | test_create_job_persists_workspace_and_metadata | ✅ PASS | 上传有效 MP4 返回 201，workspace 与 job.json 持久化正确 |
| 3 | test_create_job_without_file_returns_400 | ✅ PASS | 无文件上传返回 400 |
| 4 | test_create_job_with_empty_file_returns_400_and_cleans_workspace | ✅ PASS | 空文件返回 400 并清理临时工作区 |
| 5 | test_create_job_with_unsupported_extension_returns_400 | ✅ PASS | 不支持扩展名返回 400 |
| 6 | test_invalid_settings_return_400_without_crashing | ✅ PASS | 非法 settings 参数返回 400，服务不崩溃 |
| 7 | test_get_missing_and_invalid_job_ids | ✅ PASS | 不存在/非法 job_id 返回 404 |
| 8 | test_delete_created_job | ✅ PASS | 删除已创建任务返回 200 |
| 9 | test_delete_queued_or_running_job_returns_409 | ✅ PASS | 删除运行中任务返回 409（状态保护） |
| 10 | test_analyze_returns_202_then_persists_clear_failure | ❌ FAIL | 见下方分析 |
| 11 | test_duplicate_analyze_returns_409 | ✅ PASS | 重复触发分析返回 409 |
| 12 | test_review_requires_existing_report_and_validates_boundaries | ✅ PASS | 审核接口正确校验报告存在性与边界值 |
| 13 | test_rough_cut_placeholder_returns_501_without_fake_file | ✅ PASS | 粗剪占位接口返回 501 |
| 14 | test_startup_marks_interrupted_job_failed | ✅ PASS | 启动时将中断任务标记为 failed |
| 15 | test_corrupt_report_returns_json_500_and_service_survives | ✅ PASS | 损坏报告文件返回 500 JSON，服务不崩溃 |
| 16 | test_unknown_route_and_wrong_method_use_json_errors | ✅ PASS | 未知路由/错误方法返回 JSON 格式错误 |

### test_analyze 失败分析

```
AssertionError: 'CV 分析模块尚未接入' not found in
'Cannot open video file: C:\Users\...\demo.mp4'
```

**原因**: 测试用例使用伪造视频文件（非真实 MP4 容器），原期望返回"CV 分析模块尚未接入"错误。CV 引擎（cv_engine + yolo11n.pt）已于本轮集成，分析流程真实运行到 OpenCV 解码步骤，因此错误信息变为"Cannot open video file"。**非功能回归，属测试用例未适配 CV 集成后的行为变更。**

---

## 3. HTTP 集成测试详情（11 项）

手动通过 HTTP 请求验证 API 端点：

| # | 端点 | 方法 | 请求 | 预期 | 实际 | 结果 |
|---|------|------|------|------|------|------|
| 1 | /api/health | GET | — | 200, service ok | 200, `{"status":"ok","model_ready":true}` | ✅ |
| 2 | /api/jobs | POST | 有效 .mp4 | 201, job 创建 | 201, job JSON | ✅ |
| 3 | /api/jobs | GET | — | 200, 任务列表 | 200, jobs[] | ✅ |
| 4 | /api/jobs/{id} | GET | 有效 job_id | 200, 任务详情 | 200, job 详情 | ✅ |
| 5 | /api/jobs/{id}/analyze | POST | 有效 job_id | 202, 分析排队 | 202, queued | ✅ |
| 6 | /api/jobs/{id} | DELETE | 有效 job_id | 200, 删除成功 | 200 | ✅ |
| 7 | /api/jobs | POST | 空文件 | 400 | 400, 错误信息 | ✅ |
| 8 | /api/jobs | POST | 无文件 | 400 | 400, 错误信息 | ✅ |
| 9 | /api/jobs/{invalid_id} | GET | 非法 job_id | 404 | 404 | ✅ |
| 10 | /api/health | PUT | — | 405 | 405 | ✅ |
| 11 | /api/nonexistent | GET | — | 404 | 404, JSON 错误 | ✅ |

---

## 4. 端到端测试

| 项目 | 详情 |
|------|------|
| 素材 | F:\Day08\gameplay_normal.mp4（11.5MB / 53秒 / 1280×720 / 30fps） |
| 任务 ID | 20260718_165731_640f23f1 |
| 采样帧数 | 27 |
| YOLO 检出 | person, motorcycle, car 等 |
| 关键帧产出 | 8 张 .jpg |
| 候选片段 | 6 个 |
| final_score | 0.6727 |
| analysis_report.json | 完整返回，通过 API 可访问 |
| 结果 | ✅ PASS |

---

## 5. 已发现缺陷

| ID | 标题 | 严重等级 | 状态 |
|----|------|----------|------|
| BUG-001 | 上传层仅校验扩展名，未校验文件魔数 | 中 | 待修复 |
| BUG-002 | project_name 存储型 XSS（前端 innerHTML 渲染） | 高 | 待修复 |

详见 `BUG_RECORD.md`。

---

## 6. 已知限制

| 项目 | 状态 | 说明 |
|------|------|------|
| FFmpeg | ❌ 未安装 | health 接口 `ffmpeg_ready=false`，粗剪功能不可用 |
| test_analyze 测试用例 | ⚠️ 需更新 | 断言需适配 CV 引擎集成后的新错误信息 |

---

## 7. 结论

后端 API 核心功能（上传、状态管理、CV 分析、审核、删除、错误处理）均通过自动化测试和集成测试验证。CV 引擎端到端全链路跑通。1 个单元测试失败为测试用例未适配本次 CV 集成所致，非功能缺陷。2 个已知 Bug 已记录待修复。整体测试通过率 96.43%，达到可交付状态。
*（内容由AI生成，仅供参考）*
