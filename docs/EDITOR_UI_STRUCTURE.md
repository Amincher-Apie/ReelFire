# ReelFire 剪辑预览页结构式说明

## 1. 说明目标

本文只描述信息结构、语义关系、状态和交互，不依赖截图、颜色、坐标或视觉隐喻。没有视觉输入能力的模型可以仅依据本文生成等价页面。

页面名称：`剪辑预览`

页面地址：

```text
/jobs/{job_id}/editor
```

唯一数据源：

```text
GET /api/jobs/{job_id}/editor
```

## 2. 页面职责

页面负责：

1. 播放当前任务的原始视频。
2. 在统一时间轴上表示所有 YOLO/CV 精彩片段。
3. 展示每个片段的时间区间、评分状态和 Agent 最终评论。
4. 允许用户通过片段列表或时间轴定位视频。
5. 为后续人工审核与导出功能预留入口。

页面不负责：

1. 运行 YOLO。
2. 计算精彩度。
3. 根据评分生成 Agent 评论。
4. 修改或猜测后端最终结果。
5. 在浏览器中执行视频切片或拼接。

## 3. 语义组件树

```text
document
├── skip-link
│   └── 目标：main#editor-main
├── header#editor-header
│   ├── link#editor-back-link
│   │   └── 行为：返回分析工作台
│   ├── brand
│   │   ├── 产品名：ReelFire
│   │   └── 页面名：剪辑预览
│   ├── status#editor-job-status
│   └── button#editor-export-button
│       └── 初始状态：disabled
└── main#editor-main
    ├── aside#highlight-sidebar
    │   ├── header
    │   │   ├── h1：精彩片段
    │   │   └── output#highlight-count
    │   ├── table#highlight-table
    │   │   ├── thead
    │   │   │   ├── column：时间区间
    │   │   │   └── column：Agent 评论
    │   │   └── tbody#highlight-list
    │   │       └── row.highlight-row × N
    │   │           ├── button.highlight-seek-button
    │   │           │   ├── start
    │   │           │   ├── end
    │   │           │   └── duration
    │   │           └── agent-comment
    │   └── status#highlight-list-state
    └── section#editor-workspace
        ├── section#video-stage
        │   ├── video#editor-video
        │   └── status#video-state
        ├── section#playback-controls
        │   ├── button#skip-back-button
        │   ├── button#play-toggle-button
        │   ├── button#skip-forward-button
        │   └── output#playback-time
        ├── section#timeline-section
        │   ├── header
        │   │   ├── h2：视频时间轴
        │   │   └── output#timeline-description
        │   ├── div#timeline-track
        │   │   ├── div#highlight-marker-layer
        │   │   │   └── button.timeline-highlight × N
        │   │   └── input#timeline-scrubber[type=range]
        │   └── div#timeline-scale
        │       ├── output#timeline-start
        │       └── output#timeline-end
        └── section#active-highlight-detail
            ├── h2：当前片段
            ├── output#active-highlight-time
            ├── output#active-highlight-score
            └── p#active-highlight-comment
```

## 4. 数据绑定

| 契约字段 | 页面目标 | 绑定规则 |
| --- | --- | --- |
| `job.project_name` | 页面标题辅助文本 | 原样显示 |
| `job.status` | `#editor-job-status` | 映射为中文状态文本 |
| `video.url` | `#editor-video.src` | 原样赋值 |
| `video.duration` | 时间轴最大值 | 设置为 `range.max` |
| `highlights.length` | `#highlight-count` | 显示“共 N 段” |
| `highlights[].start/end` | 第一列表格和时间轴位置 | 文本可格式化，位置按比例计算 |
| `highlights[].score` | 当前片段评分 | 只格式化为百分比 |
| `highlights[].agent_comment` | 第二列 | 仅 `ready` 时显示 |
| `highlights[].agent_comment_status` | 第二列状态 | `pending/unavailable` 显示明确占位状态 |

## 5. 页面状态机

### `loading`

- 页面结构已出现。
- 视频、片段表格和时间轴不可操作。
- `#highlight-list-state` 显示“正在读取剪辑预览数据”。

### `ready`

- 视频地址有效。
- 片段列表已经渲染。
- 时间轴可拖动。
- 点击片段列表或时间轴标记可以定位视频。

### `empty`

- 聚合接口成功，但 `highlights` 为空。
- 视频仍可播放。
- 列表显示“当前报告没有精彩片段”。
- 时间轴不显示精彩片段标记。

### `error`

- 聚合接口失败、契约版本不支持或关键字段缺失。
- 视频和时间轴保持不可操作。
- 显示后端错误信息和返回工作台入口。

## 6. 交互规则

### 播放控制

- 点击 `#play-toggle-button`：
  - 视频暂停时调用 `video.play()`。
  - 视频播放时调用 `video.pause()`。
- 点击前后跳转按钮：
  - 后退 5 秒或前进 5 秒。
  - 结果限制在 `0..duration`。
- 视频播放状态变化时更新按钮可访问名称。

### 时间轴拖动

- `#timeline-scrubber` 使用原生 `input[type=range]`。
- `input` 事件立即设置 `video.currentTime`。
- 视频 `timeupdate` 事件同步滑块值和时间文本。
- 键盘用户可以使用方向键、PageUp、PageDown、Home 和 End。
- 拖动不是唯一操作方式。

### 精彩片段定位

- 点击列表中的片段按钮：
  1. 设置 `video.currentTime = highlight.start`。
  2. 设置当前片段。
  3. 更新详情区。
  4. 将对应行和时间轴标记设置为选中状态。
- 点击时间轴标记执行相同行为。
- 播放头进入某个片段区间时自动更新当前片段。
- 同一时间只能有一个当前片段。

### Agent 评论

- 页面只消费 Editor 聚合接口，不直接请求 Agent 调用日志来生成片段评论。
- Agent 调用日志完成不表示最终评论已经可展示。
- 只有 Editor 接口返回 `agent_comment_status = ready` 时才显示评论。
- `ready`：显示后端给出的最终评论。
- `pending`：显示“Agent 评论尚未生成”。
- `unavailable`：显示“Agent 评论不可用”。
- 禁止把 `score` 在前端转换为自然语言评论。

## 7. DOM 身份与稳定性

- 本文列出的 `id` 是页面与自动化测试之间的稳定接口。
- 动态片段元素使用 `data-highlight-id` 保存后端片段编号。
- 所有动态文本通过 `textContent` 写入，不使用不可信 HTML。
- 每个时间轴标记必须具有包含起止时间的 `aria-label`。
- 当前片段同时使用 `aria-current="true"` 与文本状态，不能只依赖颜色。

## 8. 响应式顺序

### 宽屏

```text
第一列：精彩片段列表
第二列：视频、播放控制、时间轴、当前片段详情
```

### 窄屏

DOM 顺序不变，但布局顺序为：

```text
视频
播放控制
时间轴
当前片段详情
精彩片段列表
```

要求：

- 不产生页面级横向滚动。
- 时间轴可以在自身容器中完整缩放，不要求用户水平拖动画布。
- 所有按钮可点击区域至少 44×44 CSS 像素。
- 视频不自动播放。

## 9. 焦点顺序

```text
跳到主要内容
返回工作台
导出按钮
片段定位按钮（按 order）
视频原生控制
后退 5 秒
播放/暂停
前进 5 秒
时间轴滑块
时间轴片段标记（按 order）
```

动态加载完成后不得强制抢夺用户焦点。接口错误使用 `role="alert"`，普通加载和状态更新使用 `aria-live="polite"`。

## 10. 当前框架与后续实现边界

当前框架包括：

- 独立页面路由和语义模板。
- 聚合接口读取。
- 视频播放。
- 时间轴拖动。
- 精彩片段定位和选中同步。
- Agent 评论状态展示。

后续功能包括：

- 多片段 YOLO 生产逻辑。
- Agent 原生 `segment_comments` 生产。
- 审核状态写回。
- 多片段批量切片、排序、拼接与导出。
- 缩略图精灵或 WebVTT 预览轨道。
