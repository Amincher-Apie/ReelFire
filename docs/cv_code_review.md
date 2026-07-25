# ReelFire CV 代码复核报告

**复核人**: 韩玖原（CV/数据工程师）
**复核日期**: Day 1
**复核范围**: `cv_engine/` 原有模块 + `services/analysis_service.py`

---

## 一、复核模块清单

| 模块 | 路径 | 功能 | 状态 |
|---|---|---|---|
| VideoProcessor | `cv_engine/video_processor.py` | 视频采样、信息读取、场景变化、运动强度 | ✅ 可用 |
| YoloDetector | `cv_engine/yolo_detector.py` | YOLO 推理封装 | ✅ 可用 |
| HighlightScorer | `cv_engine/highlight_scorer.py` | 三项评分 + 关键帧选择 | ✅ 可用 |
| AnalysisService | `services/analysis_service.py` | 后台任务编排 + CV 集成 | ✅ 可用 |

---

## 二、模块详细复核

### 2.1 VideoProcessor（`cv_engine/video_processor.py`）

**功能**：视频帧采样、信息读取、场景变化检测、运动强度计算

**核心方法**：
- `sample_video(video_path, interval=1)`：按间隔采样帧，返回 frames + timestamps
- `get_video_info(video_path)`：获取视频信息（fps/duration/width/height/has_audio）
- `has_audio_track(video_path)`：用 ffprobe 检测音频轨
- `calculate_scene_change(frame1, frame2)`：帧差法计算场景变化（归一化到 0-1）
- `calculate_motion_intensity(frame_sequence)`：光流法计算运动强度（归一化到 0-1）

**评估**：
- ✅ 健壮性好：fps/interval 都有有效性校验
- ✅ 异常处理完善：视频打不开、fps 无效都有明确错误
- ✅ 归一化合理：场景变化 /50、运动强度 /10
- ⚠️ `calculate_motion_intensity` 用 Farneback 光流，计算较慢，大视频可能卡顿
- ⚠️ `sample_video` 用 `cap.set(POS_FRAMES)` 跳帧，部分编码可能不准

**与题目对应**：
- 满足要求 3（OpenCV 采样与关键帧）
- 满足要求 10（画面变化、运动、目标数评分）

---

### 2.2 YoloDetector（`cv_engine/yolo_detector.py`）

**功能**：YOLO 模型加载 + 推理封装

**核心方法**：
- `__init__(model_path, confidence_threshold=0.35)`：加载模型
- `detect(frame)`：单帧检测，返回 detections 列表
- `detect_frames(frames)`：批量检测
- `get_object_count(detections)`：目标计数
- `get_high_confidence_objects(detections, threshold=0.5)`：高置信度目标过滤

**输出格式**：
```python
[{
    'class': 'weapon_rifle',      # 类别名
    'confidence': 0.92,           # 置信度
    'bbox': [x1, y1, x2, y2],    # 检测框
    'class_id': 2                 # 类别 ID
}]
```

**评估**：
- ✅ 接口清晰，输出格式符合后端 Schema
- ✅ 模型缺失有明确报错
- ✅ 置信度阈值可配置
- ⚠️ 默认模型是 `models/yolo11n.pt`，需改为支持自定义模型切换
- ⚠️ 没有模型版本记录，无法追溯用的是哪个模型

**与题目对应**：
- 满足要求 2（YOLO 类别、置信度、检测框）
- 需扩展：支持官方/自定义模型切换（要求 9）

---

### 2.3 HighlightScorer（`cv_engine/highlight_scorer.py`）

**功能**：三项评分 + 关键帧选择 + 片段推荐

**评分权重**：
- object_score（目标数量）: 0.45
- scene_change_score（场景变化）: 0.35
- motion_score（运动强度）: 0.20
- kill_notification_score（击杀提示）: 0.0（已禁用）

**核心方法**：
- `calculate_object_score(detections, max_objects=5)`：目标数 /5 归一化
- `calculate_scene_change_score(frame, prev_frame)`：帧差 /20 归一化
- `calculate_motion_score(frame, prev_frame)`：光流 /5 归一化
- `calculate_kill_notification_score(frame)`：红色击杀提示检测（已禁用，weight=0）
- `calculate_highlight_score(...)`：加权求和
- `calculate_segment_tags(samples, segments)`：统计片段内真实检测类别
- `generate_cover_prompt(keyframe)`：基于真实检测生成封面描述
- `_select_segments(...)`：片段选择（去重、合并、时长控制）

**评估**：
- ✅ 评分逻辑合理，三项权重清晰
- ✅ `calculate_segment_tags` 只统计真实检测类别，不虚构
- ✅ `generate_cover_prompt` 强调"不添加未检测到的目标"，符合诚实原则
- ✅ 片段选择有去重（时间间隔 8s）+ 合并逻辑
- ⚠️ `kill_notification_score` 代码保留但权重为 0，可删除或保留作为扩展
- ⚠️ 评分阈值（/50、/20、/5）是硬编码，建议提取为配置

**与题目对应**：
- 满足要求 10（画面变化、运动、目标数评分）
- 满足要求 17（轨迹和片段推荐的前置评分）

---

### 2.4 AnalysisService（`services/analysis_service.py`）

**功能**：后台任务编排，串联 VideoProcessor + YoloDetector + HighlightScorer

**核心流程**：
1. `enqueue(job_id)`：提交后台任务
2. `_run(job_id)`：
   - 读取视频信息
   - 采样帧（sample_interval 默认 0.5s）
   - YOLO 检测
   - 三项评分 + 关键帧选择
   - 保存关键帧图片（带标注框）
   - 生成 contact_sheet（缩略图联系表）
   - 推荐片段（_bounded_clip）
   - 写入 analysis_report.json
3. 异常处理：所有失败都写入 job 状态

**输出报告 Schema**（`analysis_report.json`）：
```json
{
  "video": {"duration", "fps", "width", "height", "has_audio"},
  "samples": [{"frame_index", "timestamp", "object_count", "object_score",
               "scene_change_score", "motion_score", "highlight_score", "objects"}],
  "keyframes": [{"id", "timestamp", "highlight_score", "objects", "image"}],
  "segments": [{"id", "start", "end", "score"}],
  "segment_tags": {"total_tags", "tags", "summary"},
  "ai_cover_prompt": "...",
  "recommended_clip": {"start_time", "end_time", "output_ratio"},
  "output": {"contact_sheet": "result/contact_sheet.jpg"}
}
```

**评估**：
- ✅ 异常处理完善：所有失败都持久化到 job 状态
- ✅ 线程安全：`_active_lock` 保护任务集合
- ✅ 关键帧图片带标注框，可人工验证
- ✅ contact_sheet 缩略图便于快速浏览
- ✅ `segment_tags` 只统计真实检测，不虚构事件
- ⚠️ 模型路径硬编码在 `AnalysisService.__init__`，需支持动态切换
- ⚠️ 没有记录模型版本，报告里只有 `model.path`（文件名）

**与题目对应**：
- 满足要求 4（检测结果、证据图、JSON 报告）
- 满足要求 8（异常处理：视频损坏、模型缺失都有处理）
- 需扩展：支持官方/自定义模型切换（要求 9）

---

## 三、与题目要求的差距分析

### 已满足的要求（无需改动）

| # | 要求 | 对应模块 |
|---|---|---|
| 2 | YOLO 类别、置信度、检测框 | YoloDetector |
| 3 | OpenCV 采样与关键帧 | VideoProcessor |
| 4 | 检测结果、证据图、JSON 报告 | AnalysisService |
| 8 | 模型/格式/空文件/推理异常 | AnalysisService |
| 10 | 画面变化、运动、目标数评分 | HighlightScorer |

### 需要扩展的要求

| # | 要求 | 现状 | 扩展方案 |
|---|---|---|---|
| 9 | 自定义 YOLO 训练 | ❌ 只用官方模型 | ✅ 已完成：训练了 best.pt |
| 16 | 多模型或多阈值对比 | ❌ 无 | ✅ 已完成：evaluate.py 对比 |
| 17 | 目标跟踪和运动轨迹 | ❌ 无 | ✅ 已完成：tracking.py |
| 15 | 30 条素材元数据 | ❌ 无 | 待做：整理数据来源表 |

### 模型切换改造点

| 文件 | 改造内容 |
|---|---|
| `services/analysis_service.py` L157 | `model_path` 支持从 settings 传入，默认 best.pt |
| `services/analysis_service.py` L278 | `__init__` 默认模型改为 `runs/detect/custom_fps/weights/best.pt` |
| `cv_engine/yolo_detector.py` | 增加模型版本记录（官方/自定义） |

---

## 四、代码质量评估

| 维度 | 评分 | 说明 |
|---|---|---|
| 健壮性 | ⭐⭐⭐⭐ | 异常处理完善，边界情况考虑到位 |
| 可读性 | ⭐⭐⭐⭐ | 命名清晰，注释适当 |
| 可维护性 | ⭐⭐⭐ | 部分阈值硬编码，建议提取配置 |
| 诚实性 | ⭐⭐⭐⭐⭐ | segment_tags/cover_prompt 都强调不虚构 |
| 可扩展性 | ⭐⭐⭐ | 模型切换需改造，其他扩展性 OK |

---

## 五、建议改进项（Day 2-3 处理）

| 优先级 | 改进项 | 说明 |
|---|---|---|
| P0 | 模型切换支持 | AnalysisService 默认用 best.pt |
| P1 | 模型版本记录 | 报告里记录用的是官方还是自定义模型 |
| P2 | 评分阈值配置化 | /50、/20、/5 提取到 settings |
| P2 | 删除 kill_notification 死代码 | weight=0 且有 print 调试 |

---

## 六、复核结论

ReelFire 原有 CV 代码**质量良好，可直接复用**：
- 三项评分、关键帧、片段推荐逻辑完善
- 异常处理和诚实性原则到位
- 只需补充模型切换 + 自定义权重集成

**Day 2 重点**：将 best.pt 接入 AnalysisService，支持官方/自定义模型切换。
