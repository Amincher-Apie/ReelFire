# CV 模块技术报告

## 1. 概述

本项目 CV 模块负责 FPS 游戏视频的目标检测、目标跟踪与精彩片段提取，支持 CS2 和 Valorant 两款游戏。模块基于 YOLO11n 自定义训练，结合 ByteTrack 目标跟踪，通过"敌人出现/消失"事件驱动的方式提取精彩片段，为后端粗剪服务和 Agent 内容理解提供结构化数据。

## 2. 数据集

### 2.1 CS2 数据集

| 项目 | 数值 |
|---|---|
| 总图片数 | 77 张 |
| 总标注数 | 160 个 |
| 类别数 | 4 类 |
| 训练集 | 62 张 |
| 验证集 | 15 张 |
| 标注工具 | LabelNazuki |
| 标注格式 | YOLO TXT |

**类别定义**：

| 类别 ID | 类别名 | 标注数 | 说明 |
|---|---|---|---|
| 0 | character_ct | 50 | CT 阵营角色（反恐精英）|
| 1 | character_t | 46 | T 阵营角色（恐怖分子）|
| 2 | weapon_rifle | 49 | 步枪（AK-47/M4A4/AWP 等）|
| 3 | weapon_pistol | 15 | 手枪（USP/Glock 等）|

**数据来源**：抖音平台创作者（匿名化处理）+ 9game.cn，详见 [data/source_list.md](../data/source_list.md)。所有素材标注为"合理使用（非商业用途）"。

### 2.2 Valorant 数据集

| 项目 | 数值 |
|---|---|
| 总图片数 | 30 张 |
| 总标注数 | 65 个 |
| 类别数 | 2 类 |
| 训练集 | 26 张 |
| 验证集 | 4 张 |
| 标注工具 | LabelNazuki |

**类别定义**：

| 类别 ID | 类别名 | 标注数 | 说明 |
|---|---|---|---|
| 0 | enemy | 32 | 敌方角色 |
| 1 | weapon | 33 | 武器（枪/刀等）|

**数据来源**：抖音平台创作者（匿名化处理，每 10 张一个创作者代号），详见 [data/valorant_source_list.md](../data/valorant_source_list.md)。

## 3. 模型训练

### 3.1 训练环境

| 项目 | 配置 |
|---|---|
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU (8GB) |
| 框架 | Ultralytics YOLO11n + PyTorch 2.6.0 + CUDA 12.4 |
| Python | 3.13.9 |

### 3.2 CS2 模型训练记录

| 版本 | 训练图片 | 标注数 | Epochs | 关键参数 | mAP50 | mAP50-95 | 说明 |
|---|---|---|---|---|---|---|---|
| v3 | 50 张 | 104 | 150 | mixup=0.1, patience=30 | 0.791 | 0.502 | 初版，mixup 干扰 CT/T 区分 |
| v4 | 50 张 | 104 | 150 | mixup=0, patience=30 | - | - | 过拟合，未采用 |
| v5 | 77 张 | 160 | 150 | mixup=0, mosaic=1.0, patience=30 | 0.783 | 0.584 | 补充 CT 素材，Recall 提升至 0.800 |

**关键经验**：
- mixup=0.1 会干扰 CT/T 角色区分（外观相似），禁用后改善
- 补充 CT 标注从 17→50 个，Recall 从 0.333 提升至 1.000
- 每个类别至少 30 个标注样本才能保证基本检测效果

### 3.3 Valorant 模型训练记录

| 版本 | 训练图片 | 标注数 | Epochs | mAP50 | mAP50-95 | 说明 |
|---|---|---|---|---|---|---|
| v1 | 13 张 | 26 | 150 | 0.995 | 0.846 | 验证集仅 2 张图，指标虚高（过拟合）|
| v2 | 26 张 | 65 | 150 | 0.796 | 0.617 | 补充数据后 weapon Precision 提升至 0.917 |

**关键经验**：
- 小数据集（验证集 < 5 张）的指标不可信，需结合实际视频效果评估
- v2 实际视频检测效果优于 v1（weapon 误检减少 20%，片段更精准）

### 3.4 多模型评估对比

详细对比图见 [outputs/eval_comparison.png](../outputs/eval_comparison.png)，评估 JSON 见：
- CS2：`outputs/eval_cs2_comparison.json`
- Valorant：`outputs/eval_valorant_comparison.json`

| 模型 | Precision | Recall | mAP50 | mAP50-95 |
|---|---|---|---|---|
| CS2 v3 | 0.919 | 0.760 | 0.850 | 0.718 |
| CS2 v5 | 0.720 | 0.800 | 0.783 | 0.584 |
| Valorant v1 | 0.841 | 0.790 | 0.796 | 0.582 |
| Valorant v2 | 0.917 | 0.791 | 0.796 | 0.617 |

## 4. 评分与精彩片段提取逻辑

### 4.1 设计决策

**未采用通用评分逻辑的原因**：

通用 FPS 评分逻辑（画面变化 + 运动幅度 + 目标数量 + 击杀提示）适用于通用场景，但在我们选取的游戏（CS2/Valorant）中存在以下问题：
- 画面变化大 ≠ 精彩（跑步、转视角也会导致画面变化大）
- 运动幅度大 ≠ 精彩（被攻击、移动时运动幅度也大）
- 击杀提示检测依赖 OCR，鲁棒性不足

**采用"敌人出现/消失"事件驱动逻辑**：

| 信号 | 可靠度 | 说明 |
|---|---|---|
| 敌人出现 | ⭐⭐⭐⭐⭐ | 交火开始的强信号 |
| 敌人消失 | ⭐⭐⭐⭐⭐ | 击杀完成/转移的强信号 |
| 峰值敌人数 | ⭐⭐⭐⭐ | 交火激烈程度指标 |

### 4.2 算法实现

核心模块：[cv_engine/highlight_extractor.py](../cv_engine/highlight_extractor.py)

**流程**：
```
逐帧检测 → 标记敌人存在状态 → 平滑抖动 → 检测出现/消失事件 → 生成片段（加缓冲）→ 合并重叠 → 输出
```

**关键参数**：

| 参数 | 默认值 | 说明 |
|---|---|---|
| pre_buffer | 1.5s | 敌人出现前保留的画面（跑位/瞄准）|
| post_buffer | 1.5s | 敌人消失后保留的画面（击杀反馈/转场）|
| smooth_frames | 5 帧 | 连续 N 帧无敌人才算消失（避免遮挡/漏检误判）|
| min_duration | 1.0s | 片段最短时长，过短则丢弃 |
| merge_gap | 1.0s | 相邻片段间隔小于此值则合并 |

### 4.3 验证结果

| 视频 | 类型 | 原时长 | 精彩时长 | 占比 | 片段数 |
|---|---|---|---|---|---|
| test_04 | 剪辑过 | 34.84s | 20.45s | 58.7% | 4 |
| test_06 | 未剪辑 | 66.57s | 27.07s | 40.7% | 4 |
| test_07 | 未剪辑 | 53.10s | 26.33s | 49.6% | 4 |

**结论**：未剪辑视频精彩占比 40-50%，剪辑过的视频占比更高（58.7%），符合预期。算法正确识别了跑位/等待阶段的冗余画面。

## 5. 模块架构

### 5.1 CV 模块文件清单

```
cv_engine/
├── yolo_detector.py        # YOLO 检测器封装
├── video_detector.py       # 视频检测（支持 --track 启用 ByteTrack）
├── highlight_extractor.py  # 精彩片段提取（敌人出现/消失逻辑）
├── highlight_scorer.py     # 通用评分器（保留，供 AnalysisService 使用）
├── model_registry.py       # 模型注册表（支持 official/custom_v3/custom_v5/valorant_v1/valorant_v2）
├── video_processor.py      # 视频采样处理
├── tracking.py             # ByteTrack 跟踪独立模块
├── train.py                # 训练脚本
├── evaluate.py             # 多模型评估对比
└── plot_eval.py            # 评估对比图绘制
```

### 5.2 数据流

```
原始视频
    │
    ▼
┌──────────────────────────┐
│ video_detector.py        │  YOLO 检测 + (可选) ByteTrack 跟踪
│ --track 启用跟踪          │  输出: {video}_detection.json
└──────────────────────────┘  输出: {video}_trajectory.json (轨迹)
    │
    ▼
┌──────────────────────────┐
│ highlight_extractor.py   │  敌人出现/消失事件提取
│                          │  输出: {video}_highlights.json
└──────────────────────────┘  输出: {video}_highlights.mp4 (粗剪视频)
    │
    ▼
┌──────────────────────────┐
│ AnalysisService          │  Web 端集成（采样模式，快速响应）
│ + ModelRegistry          │  输出: analysis_report.json
└──────────────────────────┘
    │
    ▼
┌──────────────────────────┐
│ Agent (姚博)             │  基于 highlights.json 做内容理解
└──────────────────────────┘
```

## 6. 模型卡

### 6.1 CS2 模型 (custom_v5)

| 项目 | 内容 |
|---|---|
| 模型 ID | `custom_v5` |
| 权重路径 | `runs/detect/custom_fps_v5/weights/best.pt` |
| 基础架构 | YOLO11n |
| 类别数 | 4 (character_ct, character_t, weapon_rifle, weapon_pistol) |
| 训练数据 | 77 张图片，160 个标注 |
| 训练参数 | epochs=150, imgsz=640, batch=16, mixup=0, mosaic=1.0, patience=30 |
| 验证指标 | mAP50=0.783, mAP50-95=0.584, Precision=0.720, Recall=0.800 |
| 输入尺寸 | 640×640 |
| 推理速度 | 6.7ms/张 (GPU) |
| 适用场景 | CS2 第一人称视角，右手持枪 |

### 6.2 Valorant 模型 (valorant_v2)

| 项目 | 内容 |
|---|---|
| 模型 ID | `valorant_v2` |
| 权重路径 | `runs/detect/valorant_v2/weights/best.pt` |
| 基础架构 | YOLO11n |
| 类别数 | 2 (enemy, weapon) |
| 训练数据 | 26 张图片，65 个标注 |
| 训练参数 | epochs=150, imgsz=640, batch=8, patience=30 |
| 验证指标 | mAP50=0.796, mAP50-95=0.617, Precision=0.917, Recall=0.791 |
| 输入尺寸 | 640×640 |
| 推理速度 | 2.7ms/张 (GPU) |
| 适用场景 | Valorant 第一人称视角，右手持枪 |

## 7. 局限性

1. **左手持枪漏检**：训练数据全部为右手持枪视角，左手持枪时 weapon 检测失败（不影响精彩片段提取，因逻辑基于敌人出现/消失）
2. **enemy 置信度偏低**：Valorant enemy 平均置信度 0.55-0.64，低于 weapon 的 0.77-0.87，因 enemy 外观差异大且训练样本不足
3. **远距离小目标漏检**：训练数据以中近景为主，远处小目标（<50 像素）漏检率高
4. **CT/T 类别混淆**：CT 和 T 角色外观相似，远距离时特征不明显，存在误检
5. **小数据集验证指标失真**：Valorant v1 验证集仅 2 张图，mAP50=0.995 虚高，实际效果不如 v2

## 8. 复现命令

### 8.1 训练

```powershell
# CS2 v5
python -m cv_engine.train --data data/custom.yaml --epochs 150 --imgsz 640 --batch 16 --device 0 --name custom_fps_v5

# Valorant v2
python -m cv_engine.train --data data/valorant.yaml --epochs 150 --imgsz 640 --batch 8 --device 0 --name valorant_v2
```

### 8.2 视频检测（带跟踪）

```powershell
python -m cv_engine.video_detector --video test_videos/test_06.mp4 --model runs/detect/valorant_v2/weights/best.pt --output outputs/video_detect_track_v2 --conf 0.35 --track
```

### 8.3 精彩片段提取

```powershell
python -m cv_engine.highlight_extractor --json outputs/video_detect_track_v2/test_06_detection.json --video test_videos/test_06.mp4 --output outputs/highlights/test_06
```

### 8.4 多模型评估对比

```powershell
# CS2 对比
python -m cv_engine.evaluate --models runs/detect/custom_fps_v3/weights/best.pt runs/detect/custom_fps_v5/weights/best.pt --data data/custom.yaml --output outputs/eval_cs2_comparison.json

# Valorant 对比
python -m cv_engine.evaluate --models runs/detect/valorant_v1/weights/best.pt runs/detect/valorant_v2/weights/best.pt --data data/valorant.yaml --output outputs/eval_valorant_comparison.json

# 绘制对比图
python -m cv_engine.plot_eval --cs2 outputs/eval_cs2_comparison.json --valorant outputs/eval_valorant_comparison.json --output outputs/eval_comparison.png
```

### 8.5 批量检测（PowerShell 脚本）

```powershell
.\detect.ps1                              # 批量检测 test_videos/ 下所有视频
.\detect.ps1 -Video test_06.mp4           # 检测单个视频
.\detect.ps1 -Conf 0.25                   # 调整置信度阈值
```

## 9. 测试覆盖

详见 [docs/test_cases.md](test_cases.md)。

| 游戏 | 模型版本 | 成功案例 | 失败案例 | 测试视频 |
|---|---|---|---|---|
| CS2 | custom_fps_v5 | 5 | 3 | test_01, test_02 |
| Valorant | valorant_v2 | 5 | 3 | test_04, test_06, test_07 |
| **合计** | - | **10** | **6** | **5 个视频** |

## 10. Agent 数据接口

Agent 同学通过以下 JSON 获取 CV 模块产出：

| 文件 | 用途 | 关键字段 |
|---|---|---|
| `{video}_highlights.json` | 精彩片段列表 | `segments[].{start, end, detected_classes, enemy_classes_in_segment, detections_summary}` |
| `{video}_trajectory.json` | 目标轨迹 | `{track_id: [{frame, timestamp, center, bbox, class, confidence}]}` |
| `{video}_detection.json` | 逐帧检测 | `frames[].{frame_id, timestamp, detections[].{class, confidence, bbox, track_id}}` |

**每个 segment 的 `detections_summary` 结构**：

```json
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
```
