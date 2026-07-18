# 系统设计文档

## 1. 架构设计

### 1.1 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                      前端工作台 (Web)                       │
│  ┌──────────┐  ┌─────────────┐  ┌──────────────────────┐   │
│  │ 文件上传  │  │ 任务状态展示 │  │  分析结果可视化       │   │
│  └────┬─────┘  └──────┬──────┘  └───────────┬──────────┘   │
└───────┼───────────────┼─────────────────────┼───────────────┘
        │               │                     │
        ▼               ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    Flask 后端 API                           │
│  ┌──────────┐  ┌─────────────┐  ┌──────────────────────┐   │
│  │ /api/jobs│  │ /api/health │  │ /api/jobs/:id/*      │   │
│  └────┬─────┘  └──────┬──────┘  └───────────┬──────────┘   │
└───────┼───────────────┼─────────────────────┼───────────────┘
        │               │                     │
        ▼               ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                      CV 引擎模块                            │
│  ┌────────────────┐  ┌─────────────────┐  ┌──────────────┐  │
│  │ VideoProcessor │  │ YoloDetector    │  │ HighlightSco │  │
│  │ 视频帧采样     │  │ YOLO目标检测    │  │ rer评分计算   │  │
│  └────────────────┘  └─────────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────┘
        │               │                     │
        ▼               ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                     本地文件系统                             │
│  ┌──────────┐  ┌─────────────┐  ┌──────────────────────┐   │
│  │ assets/  │  │ outputs/    │  │ models/yolo11n.pt   │   │
│  │ 原始素材 │  │ 任务输出     │  │ YOLO模型文件         │   │
│  └──────────┘  └─────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 模块职责

| 模块 | 职责 | 主要文件 |
|---|---|---|
| 前端工作台 | 用户界面、文件上传、结果展示 | `templates/index.html`, `static/` |
| Flask API | HTTP 接口、任务管理、文件处理 | `app.py` |
| VideoProcessor | 视频读取、帧采样、画面分析 | `cv_engine/video_processor.py` |
| YoloDetector | YOLO 模型加载、目标检测 | `cv_engine/yolo_detector.py` |
| HighlightScorer | 评分计算、关键帧筛选、片段推荐 | `cv_engine/highlight_scorer.py` |

## 2. 目录结构

```
team_project/
├─ app.py                    # Flask 应用入口
├─ requirements.txt          # Python 依赖清单
├─ models/
│  └─ yolo11n.pt            # YOLO 模型文件
├─ assets/                   # 上传的原始素材
├─ outputs/
│  └─ {job_id}/             # 每个任务的输出目录
│     ├─ input/             # 输入文件
│     ├─ keyframes/         # 关键帧图片
│     ├─ result/            # 分析结果
│     ├─ job.json           # 任务状态
│     └─ analysis_report.json # 分析报告
├─ static/                   # 静态资源
├─ templates/                # HTML 模板
├─ cv_engine/               # CV 引擎模块
│  ├─ __init__.py
│  ├─ video_processor.py    # 视频处理
│  ├─ yolo_detector.py      # YOLO检测
│  └─ highlight_scorer.py   # 评分计算
├─ tests/                   # 测试文件
└─ docs/                    # 文档
   ├─ PRD.md
   ├─ SYSTEM_DESIGN.md
   ├─ API.md
   ├─ TEST_REPORT.md
   └─ BUG_RECORD.md
```

## 3. 任务状态流转

```
created → queued → running → completed
                          └-> failed
```

| 状态 | 含义 | 触发条件 |
|---|---|---|
| created | 任务已创建 | 用户上传文件后 |
| queued | 任务排队中 | 等待处理 |
| running | 任务处理中 | 开始分析 |
| completed | 任务已完成 | 分析成功结束 |
| failed | 任务失败 | 分析过程出错 |

## 4. 数据模型

### 4.1 job.json

```json
{
  "job_id": "20260717_101530_a1b2c3d4",
  "project_name": "游戏录屏精彩片段提取",
  "asset_name": "game_play.mp4",
  "status": "completed",
  "created_at": "2026-07-17T10:15:30",
  "started_at": "2026-07-17T10:15:31",
  "completed_at": "2026-07-17T10:16:08",
  "settings": {},
  "result_file": "result/analysis_report.json",
  "error": null
}
```

### 4.2 analysis_report.json

```json
{
  "job_id": "20260717_101530_a1b2c3d4",
  "total_frames": 90,
  "sample_interval": 2,
  "keyframes": [
    {
      "frame_index": 0,
      "timestamp": 0.0,
      "object_score": 0.5,
      "scene_change_score": 0.0,
      "motion_score": 0.0,
      "highlight_score": 0.225,
      "objects": []
    }
  ],
  "top_keyframes": [],
  "recommended_segments": [
    {
      "start": 10.0,
      "end": 25.0,
      "score": 0.85,
      "center_timestamp": 17.5
    }
  ],
  "scoring_weights": {
    "object_weight": 0.45,
    "scene_change_weight": 0.35,
    "motion_weight": 0.20
  }
}
```

## 5. 关键算法

### 5.1 帧采样算法

```
输入: 视频路径, 采样间隔(秒)
输出: 帧列表, 时间戳列表

1. 获取视频帧率 fps
2. 计算帧间隔: sample_interval_frames = fps * interval
3. 遍历视频: for i in range(0, frame_count, sample_interval_frames)
4. 读取帧并记录时间戳
```

### 5.2 YOLO 检测

```
输入: 帧图像
输出: 检测结果列表 [{class, confidence, bbox, class_id}]

1. 调用 YOLO 模型推理
2. 解析检测框结果
3. 返回结构化数据
```

### 5.3 评分计算

```
输入: 检测结果, 当前帧, 前一帧
输出: 综合精彩分数

1. object_score = min(detection_count / max_objects, 1.0)
2. scene_change_score = 计算相邻帧灰度差异归一化
3. motion_score = 光流法计算运动强度归一化
4. highlight_score = object_score * 0.45 + scene_change_score * 0.35 + motion_score * 0.20
```

### 5.4 片段选择算法

```
输入: 排序后的关键帧, 视频时长, 目标时长
输出: 推荐片段列表

1. 按 highlight_score 降序排序关键帧
2. 遍历关键帧，以每个关键帧为中心生成候选片段
3. 检查是否与已选片段重叠
4. 如果不重叠，添加到推荐列表
5. 直到达到目标时长或遍历完所有关键帧
6. 按时间顺序排序片段
```