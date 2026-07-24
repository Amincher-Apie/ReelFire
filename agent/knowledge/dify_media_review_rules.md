# ReelFire 媒体审核知识库 v1

本文档是 Dify 知识库的上传源文件。每个二级标题对应一个独立知识条目；建议按标题或 `---` 分段，条目之间不合并。完整来源映射见 `SOURCES.md`。

---

## KB-CORE-001 检测事实引用边界

- 知识条目 ID：KB-CORE-001
- 分类：evidence_boundary
- 来源：SRC-PROJECT-001、SRC-COURSE-001、SRC-RULES-001
- 关键词：事实、证据、引用、hallucination、grounding
- 审核建议：needs_review
- 规则：只描述 CV 报告中真实存在的类别、置信度、时间戳和分数。每个关键结论至少附带一个 evidence_ref；不得把击杀、爆头、残局、胜负或武器名称写成检测事实；证据不足时标记为待复核。
- 所需证据：timestamp、source_id
- 局限：当前通用 YOLO 类别不能直接证明 FPS 专用事件。

---

## KB-QUALITY-001 空检测结果处理

- 知识条目 ID：KB-QUALITY-001
- 分类：evidence_quality
- 来源：SRC-PROJECT-001、SRC-RULES-001
- 关键词：空检测、无目标、no detection、empty
- 审核建议：needs_review
- 规则：可以描述运动或画面变化，但必须明确没有可靠目标类别证据。人工检查关键帧是否过暗、模糊或与模型类别不匹配；不要生成目标类别标签；可依据真实分数建议重新采样或调整阈值。
- 触发条件：total_detections 等于 0
- 所需证据：highlight_score、timestamp
- 局限：空检测不等于画面没有内容，只能说明当前模型未给出可靠目标。

---

## KB-QUALITY-002 低置信度目标处理

- 知识条目 ID：KB-QUALITY-002
- 分类：evidence_quality
- 来源：SRC-PROJECT-001、SRC-RULES-001
- 关键词：低置信度、低可信、low confidence、uncertain
- 审核建议：needs_review
- 规则：检测到的类别可以作为复核线索，但不能作为自动通过依据。保留类别、置信度和时间戳；优先建议人工检查检测框；不要用低置信度目标扩展出未检测事件。
- 触发条件：max_confidence 小于 0.45
- 所需证据：class_name、confidence、timestamp
- 局限：阈值会随模型和素材变化，0.45 是课程 MVP 的初始审核阈值。

---

## KB-QUALITY-003 高置信度目标处理

- 知识条目 ID：KB-QUALITY-003
- 分类：evidence_quality
- 来源：SRC-PROJECT-001、SRC-RULES-001
- 关键词：高置信度、高可信、high confidence
- 审核建议：pass
- 规则：可以确认报告中的目标类别，但仍不能扩展为未检测事件。优先选用高置信度且精彩度较高的关键帧；标签中保留真实类别名称。
- 触发条件：max_confidence 大于等于 0.75
- 所需证据：class_name、confidence、timestamp
- 局限：高置信度只证明类别检测，不证明剧情或比赛事件。

---

## KB-SCORE-001 高运动强度片段

- 知识条目 ID：KB-SCORE-001
- 分类：highlight_score
- 来源：SRC-PROJECT-001、SRC-RULES-001
- 关键词：运动、动作、motion、dynamic
- 审核建议：pass
- 规则：可描述为高运动强度或动态变化明显的候选片段。优先保留动作连续且边界完整的片段；剪辑时避免在运动峰值中间硬切。
- 触发条件：max_motion_score 大于等于 0.65
- 所需证据：motion_score、timestamp
- 局限：运动强度高不等于发生击杀或胜负事件。

---

## KB-SCORE-002 高画面变化片段

- 知识条目 ID：KB-SCORE-002
- 分类：highlight_score
- 来源：SRC-PROJECT-001、SRC-RULES-001
- 关键词：转场、画面变化、scene change、transition
- 审核建议：needs_review
- 规则：可描述为画面变化明显，应检查它是有效转场还是抖动、闪屏。人工确认转场前后语义是否连续；避免仅因闪屏或菜单切换判定为精彩内容。
- 触发条件：max_scene_change_score 大于等于 0.65
- 所需证据：scene_change_score、timestamp
- 局限：高画面变化可能来自 UI 切换、抖动或黑场。

---

## KB-SCORE-003 目标密集片段

- 知识条目 ID：KB-SCORE-003
- 分类：highlight_score
- 来源：SRC-PROJECT-001、SRC-RULES-001
- 关键词：目标密集、多人、object density、crowded
- 审核建议：pass
- 规则：可描述为目标较密集的画面，并列出真实类别和数量。选择目标清晰且遮挡较少的关键帧；标签数量必须来自对应时间戳的检测结果。
- 触发条件：max_object_count 大于等于 4
- 所需证据：object_count、timestamp
- 局限：目标密集不代表多人对战或团战。

---

## KB-CLASS-001 人物类目标审核

- 知识条目 ID：KB-CLASS-001
- 分类：detected_class
- 来源：SRC-PROJECT-001、SRC-RULES-001
- 关键词：人物、角色、person、human
- 审核建议：pass
- 规则：可以描述人物目标的数量、置信度和出现时间。人物标签只使用 person，不推断玩家身份或阵营；多人画面优先检查遮挡和重复框。
- 匹配类别：person
- 所需证据：class_name、confidence、timestamp
- 局限：person 类别不能证明真人、游戏角色、敌我关系或击杀事件。

---

## KB-CLASS-002 交通工具类目标审核

- 知识条目 ID：KB-CLASS-002
- 分类：detected_class
- 来源：SRC-PROJECT-001、SRC-RULES-001
- 关键词：车辆、交通、vehicle、car、truck
- 审核建议：pass
- 规则：列出报告中的真实交通工具类别，不推断追逐、碰撞或驾驶行为。优先选择主体完整、检测框稳定的画面；多个车辆类别同时出现时按置信度和数量排序。
- 匹配类别：bicycle、car、motorcycle、bus、train、truck、boat
- 所需证据：class_name、confidence、timestamp
- 局限：类别检测不证明具体行为或事件。

---

## KB-CLASS-003 运动器材类目标审核

- 知识条目 ID：KB-CLASS-003
- 分类：detected_class
- 来源：SRC-PROJECT-001、SRC-RULES-001
- 关键词：运动、球类、sports、sports ball、skateboard
- 审核建议：needs_review
- 规则：只描述检测到的器材类别，体育项目和动作需要人工确认。结合人物和器材的真实检测证据进行复核；不要仅凭器材类别确定比赛项目。
- 匹配类别：frisbee、skis、snowboard、sports ball、kite、baseball bat、baseball glove、skateboard、surfboard、tennis racket
- 所需证据：class_name、confidence、timestamp
- 局限：器材类别不能单独证明体育项目或动作。

---

## KB-SEGMENT-001 候选片段边界检查

- 知识条目 ID：KB-SEGMENT-001
- 分类：segment_quality
- 来源：SRC-PROJECT-001、SRC-RULES-001
- 关键词：片段、边界、segment、clip
- 审核建议：needs_review
- 规则：片段建议必须引用合法的 start、end 和 source_keyframes。确认 start 小于 end 且不超出视频时长；确认 source_keyframes 在报告中真实存在；边界异常时拒绝自动通过。
- 所需证据：segment_id、start、end
- 局限：Agent 不直接修改视频，只提供边界建议。

---

## KB-REVIEW-001 证据冲突与知识库未命中

- 知识条目 ID：KB-REVIEW-001
- 分类：review_policy
- 来源：SRC-COURSE-001、SRC-RULES-001
- 关键词：冲突、未命中、unknown、conflict、knowledge miss
- 审核建议：needs_review
- 规则：当证据之间冲突或没有适用知识条目时，保留事实摘要并转人工复核。记录 knowledge_miss 或 evidence_conflict；不要临时编造知识规则；输出可复核的原始证据引用。
- 所需证据：source_id
- 局限：待复核不是失败，不能丢弃原 CV 报告。
