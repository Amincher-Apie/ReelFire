# CV 侧 segments\[] 格式回复

***

## 1. 数据流模式：选 A（CV 直接输出统一标准格式）

CV 已经按统一格式输出 `segments[]`，**后端不需要做适配器转换**，直接读取 `analysis_report.json.segments[]` 即可。

```text
CV 输出 analysis_report.json.segments[]
→ Agent 按 segments[].id 生成 segment_comments[]
→ 后端聚合
→ Editor API 返回 highlights[]
```

***

## 2. 本地验证方式

真实运行 JSON 可能包含素材路径、运行耗时和大量逐帧数据，因此不直接提交到公开仓库。可使用项目内素材按以下方式生成并验证：

```powershell
# 1. 逐帧检测（含 ByteTrack 跟踪）
python -m cv_engine.video_detector `
    --video test_videos/test_06.mp4 `
    --model runs/detect/valorant_v2/weights/best.pt `
    --output outputs/video_detect_track_v2 `
    --conf 0.35 --track

# 2. 提取精彩片段
python -m cv_engine.highlight_extractor `
    --json outputs/video_detect_track_v2/test_06_detection.json `
    --video test_videos/test_06.mp4 `
    --output outputs/highlights_track/test_06 --no-cut
```

***

## 3. 对 6 个问题的逐条回答

### Q1. 最终写入 `analysis_report.json` 的 `segments[]` 实际长什么样？

每个 segment 包含以下字段：

| 字段                         | 类型     | 说明                         |
| -------------------------- | ------ | -------------------------- |
| `id`                       | string | 片段 ID，格式 `seg_XXX`         |
| `order`                    | int    | 片段顺序，从 1 递增                |
| `start`                    | float  | 片段起始时间（秒）                  |
| `end`                      | float  | 片段结束时间（秒）                  |
| `score`                    | float  | 片段评分（0.3\~1.0）             |
| `source_keyframes`         | array  | 关联的关键帧 ID 列表（可为空数组）        |
| `duration`                 | float  | 片段时长（秒）                    |
| `peak_enemy_count`         | int    | 峰值敌人数（交火激烈程度）              |
| `detected_classes`         | array  | 片段内检测到的所有类别（去重）            |
| `enemy_classes_in_segment` | array  | 触发该片段的敌人类别                 |
| `detections_summary`       | array  | 每个 track\_id 的检测汇总         |
| `reason`                   | string | 片段生成原因（`enemy_engagement`） |

`detections_summary` 中每个元素的结构：

| 字段                | 类型        | 说明              |
| ----------------- | --------- | --------------- |
| `track_id`        | int\|null | ByteTrack 轨迹 ID |
| `class`           | string    | 检测类别            |
| `confidence`      | float     | 平均置信度           |
| `confidence_max`  | float     | 最大置信度           |
| `confidence_min`  | float     | 最小置信度           |
| `first_seen`      | float     | 首次出现时间（秒）       |
| `last_seen`       | float     | 最后出现时间（秒）       |
| `detection_count` | int       | 检测次数            |

### Q2. 能否提供一份真实输出 JSON？

可以由上述命令在本地生成。对外共享前必须移除素材绝对路径、机器信息和不必要的逐帧数据。

### Q3. 每个片段是否会稳定提供以下字段？

```json
{
  "id": "seg_001",
  "order": 1,
  "start": 1.0,
  "end": 5.0,
  "score": 0.8,
  "source_keyframes": []
}
```

✅ **必有这 6 个字段**，所有 segment 都稳定输出。

### Q4. `id` 是 CV 生成并保证重复运行稳定，还是准备让后端生成？

**CV 生成**，格式 `seg_XXX`（如 `seg_001`/`seg_002`/`seg_003`）。

- 按时间顺序递增（`order` 字段同步递增）
- 同一视频重复运行结果稳定（只要检测和片段提取逻辑不变）
- 后端可直接使用，无需重新生成

### Q5. `score`、`source_keyframes` 暂时没有时，是返回 `null`/空数组，还是不返回字段？

| 字段                 | 缺失时的处理                              |
| ------------------ | ----------------------------------- |
| `score`            | 必有值，不会缺失（基于峰值敌人数归一化，范围 0.3\~1.0）    |
| `source_keyframes` | 返回**空数组** **`[]`**，不返回 `null`，不省略字段 |

**原则**：字段不会省略，缺失值统一用空数组（数组类型）或 0（数值类型）。
唯一例外是检测器没有可用轨迹编号时，`detections_summary[].track_id` 返回
`null`；Agent 与后端必须保留该事实，不能伪造轨迹编号。

### Q6. 重叠、相邻片段以及排序规则现在怎么处理？

| 规则           | 说明                            |
| ------------ | ----------------------------- |
| **重叠处理**     | 片段不会重叠（基于敌人出现/消失事件生成，事件本身不重叠） |
| **相邻合并**     | 相邻片段间隔 < 1.0 秒则合并为一个片段（避免碎片化） |
| **排序规则**     | 按 `start` 升序排序                |
| **order 字段** | 从 1 递增，与 `start` 顺序一致         |
| **最短时长**     | 片段时长 < 1.0 秒则丢弃（避免无意义碎片）      |

***

## 4. 数据流说明

```text
CV 输出 analysis_report.json.segments[]
  ↓
Agent 按 segments[].id 生成 segment_comments[]
  ↓
后端聚合（segment + segment_comment → highlight）
  ↓
Editor API 返回 highlights[]
```

- CV 的 `segment_id` 就是 `seg_001`/`seg_002`/`seg_003`
- Agent 可直接用 `segments[].id` 关联评论
- 后端聚合时以 `segment_id` 为 key

***

## 5. 相关文件

| 文件 | 说明 |
| --- | --- |
| `cv_engine/highlight_extractor.py` | 多精彩片段提取与统一字段生成 |
| `services/analysis_service.py` | Web 分析通路的多片段接入 |
| `docs/CV_segments.md` | 本契约说明 |

***

## 6. 后续协作

- 后端可按此 Schema 做校验、聚合、写回、多片段导出
- 如需调整字段（如增加 `tags`/`thumbnail`），请告知，CV 侧可快速补充
- Agent 同学可直接读取 `segments[].detections_summary` 获取 track\_id/置信度/类别信息
