# CV 算法参数说明

## 1. 评分权重参数

### 1.1 默认权重配置

| 参数名 | 默认值 | 说明 | 对应指标 |
|--------|--------|------|---------|
| object_weight | 0.45 | 目标检测权重 | object_score |
| scene_change_weight | 0.35 | 画面变化权重 | scene_change_score |
| motion_weight | 0.20 | 运动强度权重 | motion_score |

### 1.2 评分公式

```
highlight_score = object_score * 0.45 + scene_change_score * 0.35 + motion_score * 0.20
```

### 1.3 参数可调说明

支持通过 API 请求传入自定义权重：

```
POST /api/jobs/{job_id}/analyze
Content-Type: multipart/form-data

参数：
- object_weight: float (默认 0.45)
- scene_change_weight: float (默认 0.35)
- motion_weight: float (默认 0.20)
```

权重值会保存到分析报告的 `scoring_weights` 字段中。

---

## 2. 采样参数

| 参数名 | 默认值 | 说明 | 位置 |
|--------|--------|------|------|
| interval | 1 | 采样间隔（秒） | app.py 第137行 |
| fps | 视频原始帧率 | 帧率（默认30） | video_processor.py 第17行 |

### 采样逻辑
- 按时间间隔读取视频帧
- 每隔 `interval` 秒采样一帧
- 记录每帧的时间戳

---

## 3. 评分指标计算说明

### 3.1 object_score（目标检测分数）

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| max_objects | 5 | 目标数量归一化上限 |

**计算方式：**
```python
count = 检测到的目标数量
score = min(count / max_objects, 1.0)
```

- 检测到 0 个目标：返回 0.1
- 检测到 5 个及以上目标：返回 1.0

### 3.2 scene_change_score（画面变化分数）

**计算方式：**
```python
gray1 = 上一帧灰度图
gray2 = 当前帧灰度图
diff = cv2.absdiff(gray1, gray2)
mean_diff = np.mean(diff)
score = min(mean_diff / 20.0, 1.0)
```

- 无上一帧（首帧）：返回 0.3
- 归一化阈值：20.0

### 3.3 motion_score（运动强度分数）

**计算方式：**
```python
flow = cv2.calcOpticalFlowFarneback(gray1, gray2, ...)
magnitude = np.sqrt(flow[..., 0]**2 + flow[..., 1]**2)
mean_magnitude = np.mean(magnitude)
score = min(mean_magnitude / 5.0, 1.0)
```

- 无上一帧（首帧）：返回 0.2
- 光流参数：pyr_scale=0.5, levels=3, winsize=15, iterations=3, poly_n=5, poly_sigma=1.2
- 归一化阈值：5.0

---

## 4. 片段选择参数

| 参数名 | 默认值 | 说明 | 位置 |
|--------|--------|------|------|
| target_duration | 60.0 | 目标片段总时长（秒） | highlight_scorer.py |
| min_segment_length | 3.0 | 最小片段长度（秒） | highlight_scorer.py |
| shot_interval | 8.0 | 同一镜头判断间隔（秒） | highlight_scorer.py |

### 片段选择逻辑

1. 按分数从高到低排序关键帧
2. 遍历关键帧，为每个生成片段（前后各扩展 min_segment_length/2）
3. 跳过与已选片段重叠的帧
4. 跳过同一镜头内的帧（时间差 < shot_interval）
5. 达到 target_duration 后停止
6. 合并重叠片段

### 边界处理

| 场景 | 处理方式 |
|------|---------|
| 关键帧靠近开头 | start=0, end=min(video_duration, min_segment_length) |
| 关键帧靠近结尾 | end=video_duration, start=max(0, video_duration-min_segment_length) |
| 目标时长 > 视频时长 | target_duration = video_duration |
| 关键帧不足 | 取视频中段作为兜底片段 |
| 单片段未达目标时长 | 优先向后扩展，不足再向前扩展 |

---

## 5. 视频输出参数

### 5.1 多规格输出

| 规格 | 分辨率 | FFmpeg 滤镜 |
|------|--------|-------------|
| 横屏 16:9 | 1920×1080 | scale=1920:1080:force_original_aspect_ratio=decrease |
| 竖屏 9:16 | 720×1280 | scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280 |
| 方形 1:1 | 1080×1080 | scale=1080:1080:force_original_aspect_ratio=decrease,pad=1080:1080 |

### 5.2 FFmpeg 编码参数

| 参数 | 值 | 说明 |
|------|-----|------|
| vcodec | libx264 | 视频编码器 |
| acodec | aac | 音频编码器 |
| strict | experimental | 允许实验性编码 |

### 5.3 音频处理

- 优先保留原音频
- 无音频轨道时自动使用 `-an` 参数

---

## 6. 击杀提示检测参数（守望先锋优化，保留未启用）

| 参数名 | 值 | 说明 |
|--------|-----|------|
| roi_y_start | 0.55 | ROI 区域 Y 起始比例 |
| roi_y_end | 0.75 | ROI 区域 Y 结束比例 |
| roi_x_start | 0.25 | ROI 区域 X 起始比例 |
| roi_x_end | 0.75 | ROI 区域 X 结束比例 |
| red_ratio_min | 0.005 | 红色像素最小比例 |
| contour_area_min | 50 | 轮廓最小面积 |
| aspect_ratio_min | 1.0 | 矩形宽高比最小值 |
| aspect_ratio_max | 8.0 | 矩形宽高比最大值 |
| white_pixels_min | 15 | 白色文字像素最小值 |
| text_ratio_min | 0.02 | 文字比例最小值 |

---

## 7. JSON 报告字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| job_id | string | 任务ID |
| total_frames | int | 采样帧总数 |
| sample_interval | int | 采样间隔（秒） |
| keyframes | array | 所有关键帧数据 |
| top_keyframes | array | Top 10 关键帧 |
| recommended_segments | array | 推荐片段列表 |
| segment_tags | object | 片段标签统计 |
| ai_cover_prompt | string | AI 封面描述 |
| scoring_weights | object | 评分权重配置 |
| video_info | object | 视频元信息 |
