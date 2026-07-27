// ReelFire — editor segment list, detail, agent comments
import { editorState } from "../state/editor-state.js";
import api from "../api/client.js";
import { byId, clearChildren, createElement } from "../utils/dom.js";
import { formatTime, formatDuration, formatNumber } from "../utils/format.js";
import { setEditorView, renderVideo, renderTimeline, bindTimelineEvents, seekTo } from "./editor-video.js";
import { renderReviewEditor, renderBoundaryEditor, renderSortButtons } from "./editor-review.js";
import { renderStatsDashboard, renderTrajectoryPanel } from "./editor-stats.js";
import { updateDirtyIndicator } from "./editor-review.js";
import { checkDraft } from "./editor-actions.js";

// ── segment selection ─────────────────────────────────────────────────

export function selectSegment(segmentId) {
  editorState.selectedSegmentId = segmentId;

  const rows = document.querySelectorAll(".segment-row");
  rows.forEach((row) => {
    const selected = row.dataset.segmentId === segmentId;
    row.classList.toggle("selected", selected);
    row.setAttribute("aria-current", selected ? "true" : "false");
  });

  const markers = document.querySelectorAll(".timeline-segment-marker");
  const idx = editorState.segments.findIndex((s) => s.id === segmentId);
  markers.forEach((m, i) => {
    m.classList.toggle("active", i === idx);
  });

  renderSegmentDetail(segmentId);
  renderReviewEditor(segmentId);
  renderBoundaryEditor(segmentId);
  renderSortButtons(segmentId);
}

// ── segment list ──────────────────────────────────────────────────────

export function renderSegmentList() {
  const container = byId("highlight-list");
  clearChildren(container);
  byId("segments-count").textContent = editorState.segments.length + " 个片段";

  if (!editorState.segments.length) {
    container.append(
      createElement("p", "segment-table-empty", "YOLO 未产出精彩片段。")
    );
    return;
  }

  editorState.segments.forEach((seg, idx) => {
    const comment = findAgentComment(seg.id);
    const status = comment ? comment.status : "pending";
    const displayStatus = status === "completed" ? "ready" : status;
    const row = createElement("div", "segment-row");
    row.dataset.segmentId = seg.id;
    const rev = editorState.reviews[seg.id];
    if (rev && rev.recommendation) {
      row.dataset.review = rev.recommendation;
    }
    row.setAttribute("role", "row");
    row.setAttribute("tabindex", "0");
    row.setAttribute(
      "aria-label",
      "片段 " + (idx + 1) + "，" + formatTime(seg.start) + " 到 " + formatTime(seg.end)
    );

    const timeCell = createElement(
      "span",
      "segment-time-cell",
      formatTime(seg.start) + " : " + formatTime(seg.end)
    );
    timeCell.setAttribute("role", "cell");
    timeCell.append(
      createElement("small", "", formatNumber(seg.end - seg.start, 1) + " 秒")
    );

    const commentText =
      displayStatus === "ready" && comment && comment.summary
        ? comment.summary
        : displayStatus === "pending"
        ? "Agent 分析尚未完成"
        : "Agent 最终评论不可用";
    const commentCell = createElement(
      "span",
      "segment-comment-cell " + displayStatus,
      commentText
    );
    commentCell.setAttribute("role", "cell");
    row.append(timeCell, commentCell);

    row.addEventListener("click", () => {
      selectSegment(seg.id);
      seekTo(seg.start);
    });
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        selectSegment(seg.id);
        seekTo(seg.start);
      }
    });

    container.append(row);
  });
}

export function findAgentComment(segmentId) {
  return (
    editorState.agentComments.find((c) => c.segment_id === segmentId) || null
  );
}

// ── segment detail + agent comment ────────────────────────────────────

export function renderSegmentDetail(segmentId) {
  if (!segmentId) return;

  const seg = editorState.segments.find((s) => s.id === segmentId);
  if (!seg) return;

  const comment = findAgentComment(segmentId);

  byId("detail-placeholder").hidden = true;
  byId("detail-content").hidden = false;
  byId("detail-title").textContent = "片段 " + seg.id;
  byId("detail-score").textContent = formatNumber(Number(seg.score) * 100, 0) + " 分";
  byId("detail-time").textContent = formatTime(seg.start) + " – " + formatTime(seg.end);
  byId("detail-duration").textContent = formatNumber(seg.end - seg.start, 1) + " 秒";
  byId("detail-keyframes").textContent = (seg.source_keyframes || []).join("、");

  const agentStatus = comment ? comment.status : "pending";
  renderAgentComment(agentStatus, comment);
}

export function renderAgentComment(status, comment) {
  const badge = byId("agent-status-badge");
  badge.className = "agent-status-badge " + status;
  const badgeText =
    status === "completed"
      ? "Agent 已完成"
      : status === "pending"
      ? "待 Agent 分析"
      : "Agent 不可用";
  badge.textContent = badgeText;

  byId("agent-completed-content").hidden = true;
  byId("agent-pending-content").hidden = true;
  byId("agent-unavailable-content").hidden = true;

  if (status === "completed" && comment) {
    renderAgentCompleted(comment);
    byId("agent-completed-content").hidden = false;
  } else if (status === "pending") {
    byId("agent-pending-content").hidden = false;
  } else {
    const msg =
      comment && comment.error
        ? comment.error
        : "Agent 服务当前不可用，以下为基于 CV 检测的规则输出。";
    byId("agent-unavailable-message").textContent = msg;
    byId("agent-unavailable-content").hidden = false;
  }
}

export function renderAgentCompleted(comment) {
  byId("agent-summary").textContent = comment.summary || "Agent 未生成摘要。";

  const tagsContainer = byId("agent-tags");
  clearChildren(tagsContainer);
  (comment.tags || []).forEach((tag) => {
    const t = createElement("span", "agent-tag", tag.name);
    t.title = tag.description || "";
    tagsContainer.append(t);
  });
  if (!comment.tags || !comment.tags.length) {
    tagsContainer.append(createElement("span", "agent-tag", "无标签"));
  }

  const suggestionsContainer = byId("agent-suggestions");
  clearChildren(suggestionsContainer);
  (comment.suggestions || []).forEach((sug) => {
    const item = createElement("div", "agent-suggestion-item");
    const titleSpan = createElement("strong");
    titleSpan.textContent = sug.title;
    const prioritySpan = createElement(
      "span",
      "agent-suggestion-priority " + (sug.priority || "low"),
      sug.priority === "high" ? "高" : sug.priority === "medium" ? "中" : "低"
    );
    titleSpan.append(prioritySpan);
    const actionP = createElement("p", "", sug.action || "");
    item.append(titleSpan, actionP);
    suggestionsContainer.append(item);
  });
  if (!comment.suggestions || !comment.suggestions.length) {
    suggestionsContainer.append(
      createElement("p", "agent-field-value", "无建议。")
    );
  }

  const reviewContainer = byId("agent-review");
  clearChildren(reviewContainer);
  if (comment.review) {
    const rec = comment.review.recommendation || "needs_review";
    const recLabel =
      rec === "pass" ? "通过" : rec === "reject" ? "不通过" : "待复核";
    const recSpan = createElement("span", "agent-review-rec " + rec, recLabel);
    const confSpan = createElement(
      "span",
      "agent-review-confidence",
      "置信度 " + formatNumber(Number(comment.review.confidence) * 100, 0) + "%"
    );
    reviewContainer.append(recSpan, confSpan);

    if (comment.review.reasons && comment.review.reasons.length) {
      const reasonsList = createElement("ul", "agent-review-reasons");
      comment.review.reasons.forEach((r) => {
        reasonsList.append(createElement("li", "", r));
      });
      reviewContainer.append(reasonsList);
    }
  }

  const evidenceContainer = byId("agent-evidence");
  clearChildren(evidenceContainer);
  (comment.evidence_refs || []).forEach((ref) => {
    const item = createElement("div", "agent-evidence-item");
    item.append(
      createElement("span", "agent-evidence-type", ref.type || "ref"),
      createElement("span", "agent-evidence-source", ref.source_id || ref.ref_id || "")
    );
    evidenceContainer.append(item);
  });
  if (!comment.evidence_refs || !comment.evidence_refs.length) {
    evidenceContainer.append(
      createElement("p", "agent-field-value", "无证据引用。")
    );
  }

  const knowledgeContainer = byId("agent-knowledge");
  clearChildren(knowledgeContainer);
  (comment.knowledge_refs || []).forEach((ref) => {
    const item = createElement("div", "agent-evidence-item");
    item.append(
      createElement("span", "agent-evidence-type", "知识库"),
      createElement("span", "agent-evidence-source", ref.title || ref.knowledge_id || "")
    );
    knowledgeContainer.append(item);
  });
  if (!comment.knowledge_refs || !comment.knowledge_refs.length) {
    knowledgeContainer.append(
      createElement("p", "agent-field-value", "无知识库引用。")
    );
  }
}

// ── data loading ──────────────────────────────────────────────────────

export function loadEditorData(jobId) {
  editorState.jobId = jobId;
  setEditorView("loading");

  api.get("/api/jobs/" + encodeURIComponent(jobId) + "/editor").then(
    (payload) => {
      applyEditorData(payload);
    },
    (error) => {
      setEditorView("error");
      byId("editor-error-message").textContent =
        error.message || "剪辑预览数据读取失败。";
    }
  );
}

export function normalizeEditorData(payload) {
  if (!payload.job_id || !payload.video) {
    throw new Error("剪辑预览数据缺少必要字段。");
  }

  const agentComments = Array.isArray(payload.agent_comments)
    ? payload.agent_comments.map((c) => Object.assign({}, c))
    : [];

  const segments = (Array.isArray(payload.segments) ? payload.segments : []).map((seg) => {
    return {
      id: seg.id || "",
      order: seg.order != null ? Number(seg.order) : 0,
      start: Number(seg.start),
      end: Number(seg.end),
      score: seg.score != null ? Number(seg.score) : 0,
      source_keyframes: Array.isArray(seg.source_keyframes) ? seg.source_keyframes : [],
    };
  });

  return {
    job_id: payload.job_id,
    status: payload.status || "unknown",
    video: {
      duration: Number(payload.video.duration) || 0,
      filename: payload.video.filename || "",
      path: payload.video.path || null,
    },
    segments: segments,
    agent_comments: agentComments,
    keyframes: Array.isArray(payload.keyframes) ? payload.keyframes : [],
    output: payload.output || {},
  };
}

export function applyEditorData(payload) {
  let data;
  try {
    data = normalizeEditorData(payload);
  } catch (error) {
    setEditorView("error");
    byId("editor-error-message").textContent = error.message;
    return;
  }
  editorState.editorData = data;
  editorState.video = data.video || null;
  editorState.segments = Array.isArray(data.segments) ? data.segments : [];
  editorState.agentComments = Array.isArray(data.agent_comments) ? data.agent_comments : [];
  editorState.keyframes = Array.isArray(data.keyframes) ? data.keyframes : [];
  editorState.output = data.output || null;
  editorState.reviews = {};
  editorState.dirty = false;
  editorState.selectedSegmentId = null;
  editorState.undoStack = [];
  editorState.redoStack = [];

  byId("header-job-id").textContent = data.job_id || editorState.jobId || "—";
  byId("header-meta").textContent =
    (data.video ? formatDuration(data.video.duration) + " · " : "") +
    editorState.segments.length +
    " 个片段";

  setEditorView("content");

  renderVideo();
  renderTimeline();
  renderSegmentList();
  bindTimelineEvents();
  renderStatsDashboard();
  renderTrajectoryPanel();
  updateDirtyIndicator();

  // P2: check for auto-saved draft
  checkDraft();

  if (editorState.segments.length > 0) {
    selectSegment(editorState.segments[0].id);
  }
}
