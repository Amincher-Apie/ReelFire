// ReelFire — editor segment list, detail, agent comments
import { editorState } from "../state/editor-state.js";
import api from "../api/client.js";
import { byId, clearChildren, createElement } from "../utils/dom.js";
import { formatTime, formatDuration, formatNumber } from "../utils/format.js";
import {
  pageForIndex,
  paginate,
  renderPagination,
} from "../utils/pagination.js";
import { setEditorView, renderVideo, renderTimeline, bindTimelineEvents, seekTo } from "./editor-video.js";
import { renderReviewEditor, renderBoundaryEditor, renderSortButtons } from "./editor-review.js";
import { renderStatsDashboard, renderTrajectoryPanel } from "./editor-stats.js";
import { updateDirtyIndicator } from "./editor-review.js";
import { checkDraft } from "./editor-actions.js";
import { deleteSegment, playSegment, adoptSegment, ignoreSegment, initDragReorder } from "./segment-ops.js";

let segmentPage = 1;
let segmentPageSize = 5;

// ── segment selection ─────────────────────────────────────────────────

export function selectSegment(segmentId) {
  editorState.selectedSegmentId = segmentId;
  const reviewCard = byId("segment-review-card");
  if (reviewCard) reviewCard.hidden = false;
  const idx = editorState.segments.findIndex((segment) => (
    segment.id === segmentId
  ));
  const targetPage = pageForIndex(idx, segmentPageSize);
  if (idx >= 0 && targetPage !== segmentPage) {
    segmentPage = targetPage;
    renderSegmentList();
  }

  const cards = document.querySelectorAll(".segment-card");
  cards.forEach((card) => {
    const selected = card.dataset.segmentId === segmentId;
    card.classList.toggle("selected", selected);
    card.setAttribute("aria-current", selected ? "true" : "false");
  });

  const markers = document.querySelectorAll(".timeline-segment-marker");
  const timelineIndex = editorState.segments.findIndex(
    (segment) => segment.id === segmentId,
  );
  markers.forEach((m, i) => {
    m.classList.toggle("active", i === timelineIndex);
  });

  renderSegmentDetail(segmentId);
  renderReviewEditor(segmentId);
  renderBoundaryEditor(segmentId);
  renderSortButtons(segmentId);
  renderTrajectoryPanel();

  // Show segment ops bar
  const opsBar = byId("segment-ops-bar");
  if (opsBar) opsBar.hidden = false;
}

// ── segment card list ──────────────────────────────────────────────────

export function renderSegmentList() {
  const container = byId("highlight-list");
  if (!container) return;
  clearChildren(container);
  byId("segments-count").textContent = editorState.segments.length + " 个片段";

  if (!editorState.segments.length) {
    const reviewCard = byId("segment-review-card");
    if (reviewCard) reviewCard.hidden = true;
    container.append(
      createElement("p", "segment-table-empty", "YOLO 未产出精彩片段。点击「添加片段」手动创建。")
    );
    renderPagination(byId("highlight-pagination"), {
      total: 0,
      page: 1,
      pageSize: segmentPageSize,
    });
    renderClipSequence(null);
    return;
  }

  const pagination = paginate(
    editorState.segments,
    segmentPage,
    segmentPageSize,
  );
  segmentPage = pagination.page;
  pagination.items.forEach((seg, localIndex) => {
    const card = renderSegmentCard(seg, pagination.startIndex + localIndex);
    container.append(card);
  });
  renderPagination(byId("highlight-pagination"), {
    total: pagination.total,
    page: pagination.page,
    pageSize: pagination.pageSize,
    itemLabel: "个片段",
    ariaLabel: "精彩片段分页",
    onPageChange: (page) => {
      segmentPage = page;
      renderSegmentList();
    },
    onPageSizeChange: (pageSize) => {
      segmentPageSize = pageSize;
      segmentPage = editorState.selectedSegmentId
        ? pageForIndex(
            editorState.segments.findIndex(
              (segment) => segment.id === editorState.selectedSegmentId,
            ),
            segmentPageSize,
          )
        : 1;
      renderSegmentList();
    },
  });
  renderClipSequence(pagination);

  // Init drag reorder
  initDragReorder(container, pagination.startIndex);
}

function renderClipSequence(pagination) {
  const container = byId("clip-sequence");
  if (!container) return;
  clearChildren(container);
  const visibleSegments = pagination?.items || [];
  visibleSegments.forEach((segment, localIndex) => {
    const index = (pagination?.startIndex || 0) + localIndex;
    const item = createElement("div", "clip-sequence-item");
    item.setAttribute("role", "listitem");
    item.dataset.segmentId = segment.id;
    item.append(
      createElement("strong", "", String(index + 1)),
      createElement("span", "", segment.id),
      createElement(
        "span",
        "clip-sequence-time",
        `${formatTime(segment.start)} - ${formatTime(segment.end)}`
      )
    );
    container.append(item);
  });
  const state = byId("sequence-save-state");
  if (state) {
    const range = pagination?.total
      ? ` · 当前 ${pagination.startIndex + 1}-${pagination.endIndex}`
      : "";
    state.textContent =
      (editorState.dirty ? "顺序尚未保存" : "顺序已同步") + range;
  }
}

function renderSegmentCard(seg, idx) {
  const card = createElement("div", "segment-card");
  card.dataset.segmentId = seg.id;
  card.draggable = true;
  card.setAttribute("role", "listitem");
  card.setAttribute("tabindex", "0");
  const selected = seg.id === editorState.selectedSegmentId;
  card.classList.toggle("selected", selected);
  card.setAttribute("aria-current", selected ? "true" : "false");

  // Review status classes
  const rev = editorState.reviews[seg.id];
  if (rev && rev.recommendation) {
    card.dataset.review = rev.recommendation;
  }

  // Thumbnail placeholder
  const thumb = createElement("div", "segment-card-thumb");
  thumb.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="13" height="14" rx="2"/><path d="m16 10 5-3v10l-5-3z"/></svg>`;
  // Try to load keyframe thumbnail
  const firstKf = (seg.source_keyframes || [])[0];
  if (firstKf) {
    const img = document.createElement("img");
    img.className = "segment-thumb-img";
    img.loading = "lazy";
    img.alt = "片段缩略图";
    img.src = "/outputs/" + encodeURIComponent(editorState.jobId) + "/keyframes/" + encodeURIComponent(firstKf + ".jpg");
    img.onerror = () => { img.hidden = true; };
    img.onload = () => { thumb.innerHTML = ""; thumb.append(img); };
    thumb.append(img);
  }

  // Card body
  const body = createElement("div", "segment-card-body");

  // Header: type badge + confidence
  const header = createElement("div", "segment-card-header");
  const segSource = seg.source || seg.type || "cv";
  const typeLabel = segSource === "manual" ? "手动" : segSource === "merged" ? "合并" : segSource === "split" ? "拆分" : "自动";
  const typeBadge = createElement("span", "segment-type-badge " + segSource, typeLabel);
  const confidence = createElement("span", "segment-confidence " + confidenceClass(seg.score), formatNumber(Number(seg.score) * 100, 0) + "%");
  header.append(typeBadge, confidence);

  // Time range
  const timeRow = createElement("div", "segment-card-time");
  timeRow.append(
    createElement("span", "", formatTime(seg.start) + " – " + formatTime(seg.end)),
    createElement("span", "segment-duration", formatDuration(seg.end - seg.start))
  );

  // Keyframes info
  const kfRow = createElement("div", "segment-card-keyframes");
  const kfList = (seg.source_keyframes || []).slice(0, 3).join(", ");
  kfRow.textContent = kfList ? "关键帧: " + kfList : "";

  body.append(header, timeRow, kfRow);

  // Actions
  const actions = createElement("div", "segment-card-actions");
  const playBtn = createElement("button", "seg-action play", "▶ 播放");
  playBtn.type = "button";
  playBtn.title = "播放此片段";
  playBtn.addEventListener("click", (e) => { e.stopPropagation(); playSegment(seg.id); });

  const adoptBtn = createElement("button", "seg-action adopt", "采用");
  adoptBtn.type = "button";
  adoptBtn.addEventListener("click", (e) => { e.stopPropagation(); adoptSegment(seg.id); });

  const ignoreBtn = createElement("button", "seg-action ignore", "忽略");
  ignoreBtn.type = "button";
  ignoreBtn.addEventListener("click", (e) => { e.stopPropagation(); ignoreSegment(seg.id); });

  const delBtn = createElement("button", "seg-action delete", "删除");
  delBtn.type = "button";
  delBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (window.confirm("确定删除片段「" + seg.id + "」吗？")) {
      deleteSegment(seg.id);
    }
  });

  actions.append(playBtn, adoptBtn, ignoreBtn, delBtn);

  card.append(thumb, body, actions);

  // Click to select
  card.addEventListener("click", () => {
    selectSegment(seg.id);
    seekTo(seg.start);
  });
  card.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      selectSegment(seg.id);
      seekTo(seg.start);
    }
  });

  return card;
}

function confidenceClass(score) {
  const s = Number(score);
  if (s >= 0.8) return "high";
  if (s >= 0.5) return "medium";
  return "low";
}

// ── segment detail + agent comment ────────────────────────────────────

export function renderSegmentDetail(segmentId) {
  if (!segmentId) return;

  const seg = editorState.segments.find((s) => s.id === segmentId);
  if (!seg) return;

  // 逐片段评论 — 按 segment_id 匹配
  const segmentComment = findAgentComment(segmentId);

  byId("detail-placeholder").hidden = true;
  byId("detail-content").hidden = false;
  byId("detail-title").textContent = "片段 " + seg.id;
  byId("detail-score").textContent = formatNumber(Number(seg.score) * 100, 0) + " 分";
  byId("detail-time").textContent = formatTime(seg.start) + " – " + formatTime(seg.end);
  byId("detail-duration").textContent = formatDuration(seg.end - seg.start);
  byId("detail-keyframes").textContent = (seg.source_keyframes || []).join("、");
  const src = seg.source || seg.type || "cv";
  byId("detail-type").textContent = src === "manual" ? "手动添加" : src === "merged" ? "合并片段" : src === "split" ? "拆分片段" : "自动检测";
  byId("detail-confidence").textContent = formatNumber(Number(seg.score) * 100, 0) + "%";

  // Agent 状态来自整体 agentReport，不再从单条 segmentComment.status 读取
  renderAgentComment(segmentComment);
  renderSelectedSegmentEvidence(seg, segmentComment);
}

export function findAgentComment(segmentId) {
  return (
    editorState.agentComments.find((c) => c.segment_id === segmentId) || null
  );
}

export function renderAgentComment(segmentComment) {
  const agent = editorState.agentReport;
  const avail = agent ? agent.availability : null;
  const degraded = agent?.status === "degraded";
  const streaming = agent?.status === "streaming";
  // availability 值域：ready | unavailable | invalid | pending（无 agent 对象视为 pending）
  const agentStatus = !agent
    ? "pending"
    : (avail === "unavailable" || avail === "invalid")
      ? "unavailable"
      : "completed";

  // ── 状态徽标 ──
  const badge = byId("agent-status-badge");
  badge.className = "agent-status-badge " + agentStatus;
  const badgeText =
    agentStatus === "completed"
      ? degraded
        ? "规则降级结果"
        : streaming
          ? "Agent 分片输出"
        : "Agent 已完成"
      : agentStatus === "pending"
      ? "待 Agent 分析"
      : avail === "invalid"
        ? "Agent 结果无效"
        : "Agent 不可用";
  badge.textContent = badgeText;

  // ── 切换内容区 ──
  byId("agent-completed-content").hidden = true;
  byId("agent-pending-content").hidden = true;
  byId("agent-unavailable-content").hidden = true;

  if (agentStatus === "completed" && agent) {
    // 整体 Agent 面板 — 读取 agentReport（summary/tags/suggestions/review/evidences/knowledges）
    renderAgentOverall(agent);
    // 逐片段评论 — 读取 segmentComment（comment/review_status/action_recommendation/explanation/boundary_suggestion/evidence_refs）
    renderSegmentCommentDetail(segmentComment);
    byId("agent-completed-content").hidden = false;
  } else if (agentStatus === "pending") {
    byId("agent-pending-content").hidden = false;
  } else {
    const msg =
      agent && agent.error
        ? agent.error
        : avail === "invalid"
          ? "Agent 返回了无效结果，请检查分析参数或联系管理员。"
          : "Agent 服务当前不可用，以下为基于 CV 检测的规则输出。";
    byId("agent-unavailable-message").textContent = msg;
    byId("agent-unavailable-content").hidden = false;
  }
}

// ── 整体 Agent 报告（agent-level） ──

function renderAgentOverall(agent) {
  // 摘要：来自 agent.summary
  byId("agent-summary").textContent = agent.summary || "Agent 未生成摘要。";

  // 标签：来自 agent.tags
  const tagsContainer = byId("agent-tags");
  clearChildren(tagsContainer);
  (agent.tags || []).forEach((tag) => {
    const tagName = typeof tag === "string" ? tag : (tag.name || tag.label || "");
    const tagDesc = typeof tag === "object" ? (tag.description || "") : "";
    const t = createElement("span", "agent-tag", tagName);
    if (tagDesc) t.title = tagDesc;
    tagsContainer.append(t);
  });
  if (!agent.tags || !agent.tags.length) {
    tagsContainer.append(createElement("span", "agent-tag", "无标签"));
  }

  // 建议：来自 agent.suggestions
  const suggestionsContainer = byId("agent-suggestions");
  clearChildren(suggestionsContainer);
  (agent.suggestions || []).forEach((sug) => {
    const item = createElement("div", "agent-suggestion-item");
    const titleSpan = createElement("strong");
    titleSpan.textContent = sug.title || sug.action || "";
    const prioritySpan = createElement(
      "span",
      "agent-suggestion-priority " + (sug.priority || "low"),
      sug.priority === "high" ? "高" : sug.priority === "medium" ? "中" : "低"
    );
    titleSpan.append(prioritySpan);
    const actionP = createElement("p", "", sug.action || sug.description || "");
    item.append(titleSpan, actionP);
    suggestionsContainer.append(item);
  });
  if (!agent.suggestions || !agent.suggestions.length) {
    suggestionsContainer.append(
      createElement("p", "agent-field-value", "无建议。")
    );
  }

  // 审核意见：来自 agent.review
  const reviewContainer = byId("agent-review");
  clearChildren(reviewContainer);
  if (agent.review) {
    const rec = agent.review.recommendation || "needs_review";
    const recLabel =
      rec === "pass" ? "通过" : rec === "reject" ? "不通过" : "待复核";
    const recSpan = createElement("span", "agent-review-rec " + rec, recLabel);
    const confSpan = createElement(
      "span",
      "agent-review-confidence",
      "置信度 " + formatNumber(Number(agent.review.confidence) * 100, 0) + "%"
    );
    reviewContainer.append(recSpan, confSpan);

    if (agent.review.reasons && agent.review.reasons.length) {
      const reasonsList = createElement("ul", "agent-review-reasons");
      agent.review.reasons.forEach((r) => {
        reasonsList.append(createElement("li", "", r));
      });
      reviewContainer.append(reasonsList);
    }
  }

}

function evidenceValue(ref) {
  if (typeof ref === "string") return ref;
  if (!ref || typeof ref !== "object") return String(ref || "");
  return (
    ref.source_id
    || ref.ref_id
    || ref.title
    || ref.knowledge_id
    || ref.id
    || JSON.stringify(ref)
  );
}

function renderEvidenceGroup(container, entries, emptyText) {
  clearChildren(container);
  entries.forEach(({ type, value }) => {
    const item = createElement("div", "agent-evidence-item");
    item.append(
      createElement("span", "agent-evidence-type", type),
      createElement("span", "agent-evidence-source", value),
    );
    container.append(item);
  });
  if (!entries.length) {
    container.append(createElement("p", "agent-field-value", emptyText));
  }
}

function renderSelectedSegmentEvidence(segment, segmentComment) {
  const frameEntries = [];
  (segment.source_keyframes || []).forEach((keyframeId) => {
    frameEntries.push({ type: "关键帧", value: String(keyframeId) });
  });
  (segment.source_segment_ids || []).forEach((sourceId) => {
    frameEntries.push({ type: "来源片段", value: String(sourceId) });
  });

  const explanation = segmentComment?.explanation;
  if (explanation && typeof explanation === "object") {
    (explanation.detection_box_refs || []).forEach((ref) => {
      frameEntries.push({ type: "检测框", value: evidenceValue(ref) });
    });
  }

  const agentEntries = (segmentComment?.evidence_refs || []).map((ref) => ({
    type: "Agent",
    value: evidenceValue(ref),
  }));
  const knowledgeEntries = (editorState.agentReport?.knowledge_refs || []).map(
    (ref) => ({
      type: "知识库",
      value: evidenceValue(ref),
    }),
  );

  renderEvidenceGroup(
    byId("segment-frame-evidence"),
    frameEntries,
    "该片段暂时没有可显示的视觉证据。",
  );
  renderEvidenceGroup(
    byId("segment-agent-evidence"),
    agentEntries,
    "该片段的 Agent 引用仍在生成或未返回。",
  );
  renderEvidenceGroup(
    byId("segment-knowledge-evidence"),
    knowledgeEntries,
    "当前没有关联的审核知识。",
  );

  const total = frameEntries.length + agentEntries.length + knowledgeEntries.length;
  byId("segment-evidence-count").textContent = `${total} 项`;
  byId("segment-evidence-summary").textContent =
    `片段 ${segment.id} · ${formatTime(segment.start)}–${formatTime(segment.end)}，仅展示当前选中片段的证据。`;
}

// ── 逐片段 Agent 评论（per-segment） ──

function renderSegmentCommentDetail(segmentComment) {
  const container = byId("agent-segment-comment");
  if (!container) return;

  if (!segmentComment) {
    container.innerHTML = '<p class="agent-field-value">该片段暂无 Agent 评论。</p>';
    return;
  }

  const parts = [];

  // review_status
  if (segmentComment.review_status) {
    const statusMap = { pass: "通过", reject: "不通过", needs_review: "待复核" };
    parts.push(
      '<div class="agent-field"><span class="agent-field-label">审核决策</span>' +
      '<span class="agent-review-rec ' + segmentComment.review_status + '">' +
      (statusMap[segmentComment.review_status] || segmentComment.review_status) +
      '</span></div>'
    );
  }

  // action_recommendation
  if (segmentComment.action_recommendation) {
    parts.push(
      '<div class="agent-field"><span class="agent-field-label">操作建议</span>' +
      '<p class="agent-field-value">' + escapeHtml(segmentComment.action_recommendation) + '</p></div>'
    );
  }

  // comment
  if (segmentComment.comment) {
    parts.push(
      '<div class="agent-field"><span class="agent-field-label">评论</span>' +
      '<p class="agent-field-value">' + escapeHtml(segmentComment.comment) + '</p></div>'
    );
  }

  // explanation — 结构化对象 { highlight_type, trigger_rule, time_range, detections, keyframe_refs, detection_box_refs }
  if (segmentComment.explanation) {
    let explanationHtml = "";
    if (typeof segmentComment.explanation === "object") {
      const ex = segmentComment.explanation;
      if (ex.highlight_type || ex.trigger_rule) {
        explanationHtml += '<p class="agent-field-value">' +
          '<strong>' + escapeHtml(ex.highlight_type || "") + '</strong>' +
          (ex.trigger_rule ? ' · 触发规则: ' + escapeHtml(ex.trigger_rule) : '') +
          '</p>';
      }
      if (ex.time_range && typeof ex.time_range === "object") {
        explanationHtml += '<p class="agent-field-value">时间区间: ' +
          (ex.time_range.start != null ? ex.time_range.start + 's' : '—') +
          ' – ' + (ex.time_range.end != null ? ex.time_range.end + 's' : '—') +
          '</p>';
      }
      if (ex.detections && ex.detections.length) {
        explanationHtml += '<p class="agent-field-value">检测目标: ' +
          ex.detections.map(function(d) {
            return escapeHtml(d.class_name || "unknown") + " (置信度 " +
              (d.average_confidence != null ? (d.average_confidence * 100).toFixed(0) + "%)" : "—)");
          }).join("、") + '</p>';
      }
      if (ex.keyframe_refs && ex.keyframe_refs.length) {
        explanationHtml += '<p class="agent-field-value">关键帧引用: ' +
          escapeHtml(ex.keyframe_refs.slice(0, 5).join(", ")) +
          (ex.keyframe_refs.length > 5 ? " …" : "") + '</p>';
      }
    } else {
      explanationHtml = '<p class="agent-field-value">' + escapeHtml(String(segmentComment.explanation)) + '</p>';
    }
    parts.push(
      '<div class="agent-field"><span class="agent-field-label">解释</span>' + explanationHtml + '</div>'
    );
  }

  // boundary_suggestion — 字段为 suggested_start / suggested_end
  if (segmentComment.boundary_suggestion && typeof segmentComment.boundary_suggestion === "object") {
    const bs = segmentComment.boundary_suggestion;
    parts.push(
      '<div class="agent-field"><span class="agent-field-label">边界建议</span>' +
      '<p class="agent-field-value">起始: ' + (bs.suggested_start != null ? bs.suggested_start + 's' : '—') +
      ' · 结束: ' + (bs.suggested_end != null ? bs.suggested_end + 's' : '—') + '</p></div>'
    );
  }

  container.innerHTML = parts.length ? parts.join("") : '<p class="agent-field-value">该片段暂无 Agent 评论。</p>';
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text);
  return div.innerHTML;
}

// ── Agent report loading (independent from /editor) ───────────────────

export function loadAgentReport(jobId) {
  if (!jobId) return Promise.resolve(null);

  return api.get("/api/jobs/" + encodeURIComponent(jobId) + "/report-data").then(
    (payload) => {
      // 新后端契约：payload.report_data.agent.{segment_comments, summary, tags, ...}
      const reportData = payload.report_data || {};
      const agent = reportData.agent || {};

      // 整体 Agent 数据（availability/status/summary/tags/suggestions/review/evidences/knowledges）
      editorState.agentReport = agent;

      // 逐片段评论（segment_id/comment/review_status/action_recommendation/explanation/boundary_suggestion/evidence_refs）
      editorState.agentComments = Array.isArray(agent.segment_comments)
        ? agent.segment_comments.map((c) => Object.assign({}, c))
        : [];

      // 刷新当前选中片段的 Agent 面板
      if (editorState.selectedSegmentId) {
        renderSegmentDetail(editorState.selectedSegmentId);
      }
      return agent;
    },
    (error) => {
      // Agent 报告不可用不阻塞编辑 — 面板显示 pending 状态
      editorState.agentReport = null;
      editorState.agentComments = [];
      if (editorState.selectedSegmentId) {
        renderSegmentDetail(editorState.selectedSegmentId);
      }
      return null;
    }
  );
}

// ── Agent call polling ─────────────────────────────────────────────────

export function stopAgentPolling() {
  if (editorState.agentPollTimer) {
    window.clearTimeout(editorState.agentPollTimer);
  }
  editorState.agentPollTimer = null;
}

function setAgentProgress(status, detail, call = null) {
  const badge = byId("agent-run-badge");
  const retry = byId("agent-retry-button");
  const queued = byId("agent-step-queued");
  const running = byId("agent-step-running");
  const result = byId("agent-step-result");
  const steps = [queued, running, result].filter(Boolean);
  steps.forEach((step) => {
    step.classList.remove("active", "complete", "failed");
  });

  if (badge) badge.className = "agent-run-badge " + status;
  if (retry) retry.hidden = true;

  if (status === "waiting") {
    if (badge) badge.textContent = "等待 YOLO";
    queued?.classList.add("active");
  } else if (status === "queued" || status === "pending") {
    if (badge) badge.textContent = status === "queued" ? "排队中" : "检查中";
    queued?.classList.add("active");
  } else if (status === "running") {
    if (badge) badge.textContent = "分析中";
    queued?.classList.add("complete");
    running?.classList.add("active");
  } else if (status === "completed") {
    if (badge) badge.textContent = "Agent 已完成";
    steps.forEach((step) => step.classList.add("complete"));
  } else if (status === "degraded") {
    if (badge) badge.textContent = "规则降级结果";
    queued?.classList.add("complete");
    running?.classList.add("failed");
    result?.classList.add("complete");
    if (retry) retry.hidden = false;
  } else {
    if (badge) badge.textContent = "Agent 失败";
    queued?.classList.add("complete");
    running?.classList.add("failed");
    result?.classList.add("failed");
    if (retry) retry.hidden = false;
  }

  const provider = call?.model_name ? " · " + call.model_name : "";
  const detailElement = byId("agent-run-detail");
  if (detailElement) detailElement.textContent = detail + provider;
}

function isDegradedAgentCall(call) {
  const flags = Array.isArray(call?.result?.risk_flags)
    ? call.result.risk_flags
    : [];
  return (
    flags.includes("model_generation_failed") ||
    flags.includes("model_provider_not_configured") ||
    flags.includes("knowledge_retrieval_degraded") ||
    call?.result?.status === "degraded"
  );
}

export async function pollAgentCall(agentCallId) {
  stopAgentPolling();
  try {
    const payload = await api.get(
      "/api/agent-calls/" + encodeURIComponent(agentCallId),
    );
    const call = payload.agent_call;
    editorState.agentCallId = call.id;
    editorState.agentCallStatus = call.status;

    if (call.status === "queued") {
      setAgentProgress(
        "queued",
        "Agent 调用已创建，正在等待后台执行器。",
        call,
      );
    } else if (call.status === "running") {
      setAgentProgress(
        "running",
        "正在解析视觉报告、检索知识并生成逐片段评论。",
        call,
      );
    } else if (call.status === "completed") {
      setAgentProgress(
        "completed",
        "在线 Agent 结果和逐片段评论已保存。",
        call,
      );
      await loadAgentReport(editorState.jobId);
      return call;
    } else if (call.status === "needs_review") {
      const degraded = isDegradedAgentCall(call);
      setAgentProgress(
        degraded ? "degraded" : "completed",
        degraded
          ? "在线模型或知识检索不可用，当前已展示完整的规则降级评论；可修正配置后重试。"
          : "Agent 已完成逐片段输出，结果需要人工复核。",
        call,
      );
      await loadAgentReport(editorState.jobId);
      return call;
    } else {
      setAgentProgress(
        "failed",
        call.error_message || "Agent 执行失败，请检查服务配置后重试。",
        call,
      );
      return call;
    }

    editorState.agentPollTimer = window.setTimeout(
      () => pollAgentCall(agentCallId),
      1400,
    );
    return call;
  } catch (error) {
    editorState.agentCallStatus = "failed";
    setAgentProgress(
      "failed",
      (error.message || "无法读取 Agent 调用状态。") + " 请点击重试。",
    );
    return null;
  }
}

export async function startAgentRun(forceNew = false) {
  stopAgentPolling();
  setAgentProgress("pending", "正在检查 Agent 调用记录。");
  try {
    let call = null;
    if (!forceNew) {
      const history = await api.get(
        "/api/jobs/" + encodeURIComponent(editorState.jobId) + "/agent-calls",
      );
      call = Array.isArray(history.agent_calls)
        ? history.agent_calls[0] || null
        : null;
    }
    if (!call) {
      const created = await api.post(
        "/api/jobs/" + encodeURIComponent(editorState.jobId) + "/agent-calls",
        { prompt_version: "v2", force: forceNew },
      );
      call = created.agent_call;
    }
    editorState.agentCallId = call.id;
    editorState.agentCallStatus = call.status;
    return pollAgentCall(call.id);
  } catch (error) {
    editorState.agentCallStatus = "failed";
    setAgentProgress(
      "failed",
      (error.message || "Agent 调用无法启动。") + " 请检查配置后重试。",
    );
    return null;
  }
}

export async function ensureAgentRun() {
  const data = editorState.editorData;
  if (!data || data.status !== "completed") {
    if (editorState.agentComments.length > 0) {
      setAgentProgress(
        "running",
        `已收到 ${editorState.agentComments.length} 个片段的 Agent 输出；后续片段会继续追加。`,
      );
    } else {
      setAgentProgress(
        "waiting",
        "YOLO 发现首个精彩片段后会立即送入 Agent 队列。",
      );
    }
    return null;
  }

  const expected = editorState.segments.length;
  if (expected > 0 && editorState.agentComments.length >= expected) {
    editorState.agentStreamPollAttempts = 0;
    setAgentProgress(
      editorState.agentReport?.status === "degraded"
        ? "degraded"
        : "completed",
      `已收到全部 ${expected} 个片段的 Agent 输出。`,
    );
    return null;
  }

  if (
    editorState.agentCallId &&
    (editorState.agentCallStatus === "queued" ||
      editorState.agentCallStatus === "running")
  ) {
    return pollAgentCall(editorState.agentCallId);
  }

  if (expected > 0 && editorState.agentStreamPollAttempts < 10) {
    editorState.agentStreamPollAttempts += 1;
    setAgentProgress(
      "running",
      `正在接收逐片段 Agent 输出：${editorState.agentComments.length} / ${expected}。`,
    );
    stopAgentPolling();
    editorState.agentPollTimer = window.setTimeout(async () => {
      await loadAgentReport(editorState.jobId);
      ensureAgentRun();
    }, 1400);
    return null;
  }
  return startAgentRun(false);
}

// ── data loading ──────────────────────────────────────────────────────

let loadRetries = 0;
const MAX_LOAD_RETRIES = 2;

function stopLiveAnalysisPolling() {
  if (editorState.analysisPollTimer) {
    window.clearTimeout(editorState.analysisPollTimer);
  }
  editorState.analysisPollTimer = null;
}

function scheduleLiveAnalysisPolling() {
  stopLiveAnalysisPolling();
  editorState.analysisPollTimer = window.setTimeout(
    pollLiveAnalysis,
    1600,
  );
}

function pollLiveAnalysis() {
  stopLiveAnalysisPolling();
  if (!editorState.jobId) return;
  api.get(
    "/api/jobs/" + encodeURIComponent(editorState.jobId) + "/editor"
  ).then(
    (payload) => {
      const data = applyEditorData(payload, { refresh: true });
      if (
        data &&
        data.status !== "completed" &&
        data.status !== "failed" &&
        !(data.live_analysis && data.live_analysis.final)
      ) {
        scheduleLiveAnalysisPolling();
      }
    },
    (error) => {
      const detail = byId("live-analysis-detail");
      if (detail) {
        detail.textContent =
          "增量状态暂时读取失败，将自动重试：" + error.message;
      }
      scheduleLiveAnalysisPolling();
    },
  );
}

export function loadEditorData(jobId) {
  if (editorState.jobId !== jobId) {
    stopAgentPolling();
    editorState.agentCallId = null;
    editorState.agentCallStatus = null;
    editorState.agentStreamPollAttempts = 0;
    segmentPage = 1;
    segmentPageSize = 5;
  }
  editorState.jobId = jobId;
  stopLiveAnalysisPolling();
  setEditorView("loading");
  const headerMeta = byId("header-meta");
  if (headerMeta) headerMeta.textContent = "正在请求编辑数据…";

  api.get("/api/jobs/" + encodeURIComponent(jobId) + "/editor").then(
    (payload) => {
      loadRetries = 0;
      const data = applyEditorData(payload);
      if (
        data &&
        data.status !== "completed" &&
        data.status !== "failed" &&
        !(data.live_analysis && data.live_analysis.final)
      ) {
        scheduleLiveAnalysisPolling();
      }
    },
    (error) => {
      if (loadRetries < MAX_LOAD_RETRIES && (error.status === 0 || error.status >= 500)) {
        loadRetries++;
        const retryMsg = "加载失败，正在重试（" + loadRetries + "/" + MAX_LOAD_RETRIES + "）…";
        setEditorView("error");
        byId("editor-error-message").textContent = retryMsg;
        setTimeout(() => loadEditorData(jobId), 1500);
        return;
      }
      loadRetries = 0;
      setEditorView("error");
      const code = error.status || 0;
      if (code === 404) {
        byId("editor-error-message").textContent =
          "任务 " + jobId + " 不存在或已被删除。请从工作台重新进入。";
      } else if (code === 0) {
        byId("editor-error-message").textContent =
          "无法连接服务器，请检查网络后重试。";
      } else {
        byId("editor-error-message").textContent =
          error.message || "剪辑预览数据读取失败。";
      }
    }
  );
}

export function normalizeEditorData(payload) {
  if (!payload || typeof payload !== "object") {
    throw new Error("服务端返回了无法识别的数据格式。");
  }
  // ── 新后端契约（project-lifecycle）：payload.job.{job_id,status}, payload.highlights[], payload.video.url ──
  // ── 旧后端契约（feature/frontend）：payload.{job_id,status,segments,agent_comments,keyframes} ──
  const jobContainer = payload.job || payload;
  const jobId = jobContainer.job_id;
  if (!jobId) {
    throw new Error("剪辑预览数据缺少任务编号。");
  }
  const status = jobContainer.status || "unknown";

  // video：新后端返回 video.url（直接可用）+ video.duration_seconds，旧后端返回 video.path + video.duration
  const rawVideo = payload.video || {};
  const videoUrl = rawVideo.url || null;
  const videoPath = rawVideo.path || null;
  const videoDuration = Number(rawVideo.duration_seconds || rawVideo.duration) || 0;

  // highlights → segments（新后端）；segments → segments（旧后端回退）
  const rawSegments = Array.isArray(payload.highlights)
    ? payload.highlights
    : Array.isArray(payload.segments)
      ? payload.segments
      : [];

  const segments = rawSegments
    .filter((seg) => seg && typeof seg === "object")
    .map((seg) => {
      const start = Number(seg.start);
      const end = Number(seg.end);
      return {
        id: seg.id || "",
        order: seg.order != null ? Number(seg.order) : 0,
        start: Number.isFinite(start) && start >= 0 ? start : 0,
        end: Number.isFinite(end) && end >= start ? end : start,
        duration: seg.duration != null ? Number(seg.duration) : (Number.isFinite(end) ? end - start : 0),
        score: seg.score != null ? Number(seg.score) : 0,
        source_keyframes: Array.isArray(seg.source_keyframes) ? seg.source_keyframes : [],
        source: seg.source || seg.type || "cv",
        source_segment_ids: Array.isArray(seg.source_segment_ids) ? seg.source_segment_ids : [],
        review: seg.review || "",
        review_note: seg.review_note || "",
        evidence: seg.evidence && typeof seg.evidence === "object"
          ? seg.evidence
          : null,
        tracking: seg.tracking && typeof seg.tracking === "object"
          ? seg.tracking
          : null,
        // /editor 内嵌的 Agent 预览（/report-data 加载前用于快速展示）
        _agentPreview: {
          comment: seg.agent_comment || null,
          commentStatus: seg.agent_comment_status || null,
          reviewStatus: seg.agent_review_status || null,
          evidenceRefs: Array.isArray(seg.agent_evidence_refs) ? seg.agent_evidence_refs : [],
        },
      };
    });
  const agentComments = segments
    .filter((segment) => segment._agentPreview.comment)
    .map((segment) => ({
      segment_id: segment.id,
      comment: segment._agentPreview.comment,
      review_status:
        segment._agentPreview.reviewStatus || "needs_review",
      action_recommendation:
        segment._agentPreview.reviewStatus === "pass"
          ? "adopt"
          : segment._agentPreview.reviewStatus === "reject"
            ? "reject"
            : "needs_review",
      evidence_refs: segment._agentPreview.evidenceRefs,
    }));

  // Restore saved reviews from server-side segment/highlight data
  const reviews = {};
  rawSegments
    .filter((seg) => seg && typeof seg === "object" && seg.review)
    .forEach((seg) => {
      reviews[seg.id] = {
        recommendation: seg.review || "",
        note: seg.review_note || "",
      };
    });

  return {
    job_id: jobId,
    status: status,
    video: {
      duration: videoDuration,
      filename: rawVideo.filename || "",
      fps: Number(rawVideo.fps) || 0,
      // 新后端：video.url 直接可用；旧后端：video.path 需拼接
      url: videoUrl,
      path: videoPath,
    },
    segments: segments,
    // agent_comments 不再从 /editor 聚合数据中读取 — 由 /report-data 独立加载
    agent_comments: agentComments,
    output: payload.output || {},
    reviews: reviews,
    actions_enabled: payload.actions_enabled !== false,
    live_analysis: payload.live_analysis || null,
  };
}

export function applyEditorData(payload, options = {}) {
  let data;
  try {
    data = normalizeEditorData(payload);
  } catch (error) {
    setEditorView("error");
    byId("editor-error-message").textContent = error.message;
    return null;
  }
  const refresh = options.refresh === true;
  const previousSelection = editorState.selectedSegmentId;
  const existingSegments = editorState.segments.slice();
  editorState.editorData = data;
  editorState.video = data.video || null;
  if (refresh && editorState.dirty) {
    const existingIds = new Set(existingSegments.map((segment) => segment.id));
    editorState.segments = existingSegments.concat(
      data.segments.filter((segment) => !existingIds.has(segment.id)),
    );
  } else {
    editorState.segments = Array.isArray(data.segments) ? data.segments : [];
  }
  const addedSegmentCount = Math.max(
    0,
    editorState.segments.length - existingSegments.length,
  );
  editorState.output = data.output || null;
  if (!refresh) {
    editorState.agentReport = null;
    editorState.agentComments = [];
    editorState.keyframes = [];
    editorState.reviews = data.reviews || {};
    editorState.dirty = false;
    editorState.undoStack = [];
    editorState.redoStack = [];
    editorState.saveStatus = "saved";
  }
  const incomingComments = Array.isArray(data.agent_comments)
    ? data.agent_comments
    : [];
  if (incomingComments.length > 0) {
    const commentsById = new Map(
      editorState.agentComments.map((comment) => [
        comment.segment_id,
        comment,
      ]),
    );
    incomingComments.forEach((comment) => {
      commentsById.set(comment.segment_id, comment);
    });
    editorState.agentComments = [...commentsById.values()];
    if (data.status !== "completed" || !editorState.agentReport) {
      editorState.agentReport = {
        availability: "ready",
        status: "streaming",
        summary: `已完成 ${editorState.agentComments.length} 个候选片段的 Agent 分析。`,
        tags: [],
        suggestions: [],
        review: null,
        evidence_refs: [],
        knowledge_refs: [],
      };
    }
  }
  editorState.selectedSegmentId = editorState.segments.some(
    (segment) => segment.id === previousSelection,
  ) ? previousSelection : null;

  const actionsEnabled = data.actions_enabled !== false;
  [
    "save-review-button",
    "rough-cut-button",
    "open-export-button",
    "export-selected-segment-button",
  ].forEach((id) => {
    const button = byId(id);
    if (button) button.disabled = !actionsEnabled;
  });
  const live = data.live_analysis || {};
  const percent = Math.max(0, Math.min(100, Number(live.percent) || 0));
  const progress = byId("live-analysis-progress");
  if (progress) {
    progress.value = percent;
    progress.textContent = `${Math.round(percent)}%`;
  }
  const count = byId("live-analysis-count");
  if (count) {
    count.textContent =
      `${Number(live.completed_chunks) || 0} / ${Number(live.total_chunks) || 0} 个窗口`;
  }
  const detail = byId("live-analysis-detail");
  if (detail) detail.textContent = live.message || "";
  const badge = byId("live-analysis-badge");
  if (badge) {
    badge.className = `live-analysis-badge ${live.final ? "completed" : "running"}`;
    badge.textContent = live.final ? "分析完成" : "后台分析中";
  }

  byId("header-job-id").textContent = data.job_id || editorState.jobId || "—";
  byId("header-meta").textContent =
    (data.video ? formatDuration(data.video.duration) + " · " : "") +
    editorState.segments.length +
    " 个片段";

  setEditorView("content");

  if (!refresh) renderVideo();
  renderTimeline();
  renderSegmentList();
  bindTimelineEvents();
  renderStatsDashboard();
  renderTrajectoryPanel();
  updateDirtyIndicator();
  updateAutoSaveIndicator();

  // Show auto-save indicator
  byId("auto-save-indicator").hidden = false;

  if (!refresh) {
    // Check for auto-saved draft
    checkDraft();
  }

  if (data.status === "completed") {
    // 最终报告就绪后刷新完整 Agent 报告并同步调用终态。
    loadAgentReport(editorState.jobId).finally(() => ensureAgentRun());
  } else {
    ensureAgentRun();
  }

  if (editorState.segments.length > 0) {
    selectSegment(
      editorState.selectedSegmentId || editorState.segments[0].id,
    );
  }
  if (refresh && addedSegmentCount > 0) {
    const live = byId("sequence-live");
    if (live) {
      live.textContent =
        `后台分析新增 ${addedSegmentCount} 个片段，已追加到剪辑序列。`;
    }
  }
  return data;
}

// ── auto-save indicator helper ─────────────────────────────────────────

function updateAutoSaveIndicator() {
  const indicator = byId("auto-save-indicator");
  if (!indicator) return;

  const status = editorState.saveStatus;
  indicator.className = "auto-save-indicator " + status;
  byId("save-status-text").textContent =
    status === "saving" ? "保存中…" :
    status === "saved" ? "已保存" :
    status === "error" ? "保存失败" : "未保存";

  byId("save-retry-button").hidden = status !== "error";

  if (status === "error") {
    byId("save-retry-button").onclick = () => {
      import("./editor-actions.js").then((m) => m.saveReview());
    };
  }
}
