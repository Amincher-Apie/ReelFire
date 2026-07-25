# CV 模块使用指南

本指南面向 **Agent 工程师** 和 **后端工程师**，介绍如何使用 CV 模块的产出数据和接口。

## 快速导航

| 你的角色 | 你需要看哪一节 |
|---|---|
| Agent 工程师 | [1. Agent 数据接口](#1-agent-数据接口) + [2. 一键导出](#2-一键导出-agent-所需数据) |
| 后端工程师 | [3. AnalysisService 集成](#3-analysisservice-集成) + [4. 模型切换](#4-模型切换) |
| 所有人 | [5. 常见问题](#5-常见问题) |

---

## 1. Agent 数据接口

Agent 同学通过以下 3 个 JSON 文件获取 CV 模块产出，**核心用第 1 个**。

### 1.1 精彩片段 JSON（核心）

**文件**：`outputs/highlights_track/{video_name}/{video_name}_highlights.json`

**用途**：每个精彩片段的边界、检测类别、track_id、置信度统计。

**结构示例**：

```json
{
  "segments": [
    {
      "start": 0.0,
      "end": 6.4,
      "duration": 6.4,
      "enemy_appear_at": 1.433,
      "enemy_disappear_at": 4.9,
      "peak_enemy_count": 1,
      "detected_classes": ["enemy", "weapon"],
      "enemy_classes_in_segment": ["enemy"],
      "detections_summary": [
        {
          "track_id": 11,
          "class": "enemy",
          "first_seen": 4.433,
          "last_seen": 4.867,
          "detection_count": 13,
          "confidence": 0.6858,
          "confidence_max": 0.9558,
          "confidence_min": 0.3745
        }
      ],
      "reason": "enemy_engagement"
    }
  ],
  "stats": {
    "total_segments": 3,
    "total_duration": 17.07,
    "highlight_ratio": 0.256,
    "video_duration": 66.57
  }
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `segments[].start` / `end` | float | 片段起止时间（秒）|
| `segments[].enemy_appear_at` | float | 敌人首次出现时间 |
| `segments[].enemy_disappear_at` | float | 敌人最后一次出现时间 |
| `segments[].peak_enemy_count` | int | 片段内峰值敌人数（交火激烈程度）|
| `segments[].detected_classes` | list[str] | 片段内所有检测类别（去重）|
| `segments[].enemy_classes_in_segment` | list[str] | 触发该片段的敌人类别 |
| `segments[].detections_summary` | list[dict] | 每个 track_id 的置信度统计 |
| `segments[].reason` | str | 固定为 `"enemy_engagement"` |
| `stats.highlight_ratio` | float | 精彩内容占比（0-1）|

**敌人类别说明**（重要）：

| 游戏 | 类别名 | 含义 |
|---|---|---|
| CS2 | `character_ct` | CT 阵营角色 |
| CS2 | `character_t` | T 阵营角色 |
| Valorant | `enemy` | 敌方角色 |

Agent 可根据 `enemy_classes_in_segment` 判断玩家阵营和敌人阵营。

### 1.2 轨迹 JSON（可选）

**文件**：`outputs/video_detect_track_v2/{video_name}_trajectory.json`

**用途**：每个 track_id 的完整运动轨迹，可用于分析敌人移动路径。

**结构示例**：

```json
{
  "11": [
    {
      "frame": 133,
      "timestamp": 4.433,
      "center": [1200, 540],
      "bbox": [1180, 500, 1220, 580],
      "class": "enemy",
      "confidence": 0.7521
    }
  ]
}
```

### 1.3 逐帧检测 JSON（可选）

**文件**：`outputs/video_detect_track_v2/{video_name}_detection.json`

**用途**：每帧的完整检测结果，包含 track_id，可用于自定义分析。

---

## 2. 一键导出 Agent 所需数据

对任意视频生成上述 3 个 JSON 文件：

```powershell
# 步骤 1: 检测 + 跟踪（生成 detection.json + trajectory.json）
python -m cv_engine.video_detector --video test_videos/test_06.mp4 --model runs/detect/valorant_v2/weights/best.pt --output outputs/video_detect_track_v2 --conf 0.35 --track

# 步骤 2: 提取精彩片段（生成 highlights.json + highlights.mp4）
python -m cv_engine.highlight_extractor --json outputs/video_detect_track_v2/test_06_detection.json --video test_videos/test_06.mp4 --output outputs/highlights_track/test_06
```

**模型选择**：

| 游戏 | 模型路径 |
|---|---|
| CS2 | `runs/detect/custom_fps_v5/weights/best.pt` |
| Valorant | `runs/detect/valorant_v2/weights/best.pt` |

---

## 3. AnalysisService 集成

后端同学通过 `AnalysisService` 在 Web 端调用 CV 能力。

### 3.1 基本用法

```python
from services.analysis_service import AnalysisService
from services.job_service import JobService

job_service = JobService(...)
analysis_service = AnalysisService(
    jobs=job_service,
    max_workers=2,
    model_path=Path("models/yolo11n.pt"),  # 默认官方模型
)

# 异步分析视频
analysis_service.enqueue(job_id)
```

### 3.2 输出报告结构

分析完成后生成 `analysis_report.json`，包含：

```json
{
  "video": {"duration": 32.5, "width": 2400, "height": 1080, "fps": 30},
  "model": {"id": "custom_v5", "display_name": "Custom FPS v5 (CS2)", ...},
  "keyframes": [...],
  "segments": [{"id": "seg_001", "start": 5.0, "end": 35.0, ...}],
  "recommended_clip": {"start_time": 5.0, "end_time": 35.0}
}
```

**注意**：Web 端的 `AnalysisService` 使用**采样模式**（默认 0.5s 采样一帧）以快速响应，**不输出 track_id**。如需 track_id，请用 CLI 工具（见第 2 节）。

---

## 4. 模型切换

通过 `ModelRegistry` 在 5 个模型间切换：

| 模型 ID | 显示名 | 类别数 | 适用场景 |
|---|---|---|---|
| `official` | YOLO11n (Official) | 80 | 通用 COCO 检测 |
| `custom_v3` | Custom FPS v3 | 4 | CS2（初版）|
| `custom_v5` | Custom FPS v5 (CS2) | 4 | **CS2（推荐）** |
| `valorant_v1` | Valorant v1 | 2 | Valorant（初版）|
| `valorant_v2` | Valorant v2 | 2 | **Valorant（推荐）** |

### 4.1 在 AnalysisService 中切换模型

```python
# 方式 1: 通过 settings 指定
settings = {"model_id": "valorant_v2", ...}
analysis_service.enqueue(job_id)  # 会自动使用 valorant_v2

# 方式 2: 直接调用
from cv_engine.model_registry import ModelRegistry
registry = ModelRegistry(Path("."))
model_path = registry.resolve_model_path("valorant_v2")
```

### 4.2 列出所有可用模型

```python
from cv_engine.model_registry import ModelRegistry
registry = ModelRegistry(Path("."))
for model in registry.list_models():
    print(f"{model.model_id}: {model.display_name} ({model.num_classes}类)")
```

---

## 5. 常见问题

### Q1: Web 端报告里没有 track_id？

Web 端 `AnalysisService` 用采样模式（0.5s 一帧）快速响应，不启用跟踪。如需 track_id，用 CLI：

```powershell
python -m cv_engine.video_detector --video xxx.mp4 --model xxx.pt --track
```

### Q2: CS2 和 Valorant 的模型能混用吗？

**不能**。类别不同（CS2: 4类 CT/T/rifle/pistol；Valorant: 2类 enemy/weapon），混用会导致检测类别名错乱。请根据视频游戏选择对应模型。

### Q3: 左手持枪视角检测不到武器？

已知局限。训练数据全部为右手持枪视角。**不影响精彩片段提取**，因为提取逻辑基于敌人出现/消失，不依赖 weapon 检测。

### Q4: 如何调整精彩片段的边界？

修改 `highlight_extractor` 的参数：

```powershell
# 前后缓冲改为 2 秒
python -m cv_engine.highlight_extractor --json xxx.json --video xxx.mp4 --pre-buffer 2.0 --post-buffer 2.0
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--pre-buffer` | 1.5s | 敌人出现前保留画面 |
| `--post-buffer` | 1.5s | 敌人消失后保留画面 |
| `--smooth-frames` | 5 | 连续 N 帧无敌人才算消失 |
| `--min-duration` | 1.0s | 片段最短时长 |
| `--merge-gap` | 1.0s | 相邻片段间隔小于此值则合并 |

### Q5: 如何评估模型效果？

```powershell
# 多模型对比
python -m cv_engine.evaluate --models model1.pt model2.pt --data data/xxx.yaml --output outputs/eval.json

# 绘制对比图
python -m cv_engine.plot_eval --cs2 outputs/eval_cs2.json --valorant outputs/eval_valorant.json --output outputs/eval_comparison.png
```

### Q6: 如何训练新模型？

```powershell
# CS2
python -m cv_engine.train --data data/custom.yaml --epochs 150 --imgsz 640 --batch 16 --device 0 --name custom_fps_v6

# Valorant
python -m cv_engine.train --data data/valorant.yaml --epochs 150 --imgsz 640 --batch 8 --device 0 --name valorant_v3
```

---

## 6. 文件清单

```
cv_engine/
├── README.md                # 本文档
├── yolo_detector.py         # YOLO 检测器封装
├── video_detector.py        # 视频检测（支持 --track）
├── highlight_extractor.py   # 精彩片段提取
├── highlight_scorer.py      # 通用评分器（供 AnalysisService）
├── model_registry.py        # 模型注册表
├── video_processor.py       # 视频采样
├── tracking.py              # ByteTrack 跟踪独立模块
├── train.py                 # 训练脚本
├── evaluate.py              # 多模型评估
└── plot_eval.py             # 评估对比图
```

详细技术报告见 [docs/CV_REPORT.md](../docs/CV_REPORT.md)。

## 7. 联系方式

CV 模块由 **CV/数据工程师** 维护。如需新增功能、调整接口或报告问题，请在团队群内 @CV工程师。
