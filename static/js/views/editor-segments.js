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
import { deleteSegment, playSegment, adoptSegment, ignoreSegment, initDragReorder } from "./segment-ops.js";

// ── segment selection ─────────────────────────────────────────────────

export function selectSegment(segmentId) {
  editorState.selectedSegmentId = segmentId;

  const cards = document.querySelectorAll(".segment-card");
  cards.forEach((card) => {
    const selected = card.dataset.segmentId === segmentId;
    card.classList.toggle("selected", selected);
    card.setAttribute("aria-current", selected ? "true" : "false");
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

  // Show segment ops bar
  const opsBar = byId("segment-ops-bar");
  if (opsBar) opsBar.hidden = false;
}

// ── segment card list ──────────────────────────────────────────────────

export function renderSegmentList() {
  const container = byId("highlight-list");
  if (!container) return;
  clearChildren(container);
  renderClipSequence();
  byId("segments-count").textContent = editorState.segments.length + " 个片段";

  if (!editorState.segments.length) {
    container.append(
      createElement("p", "segment-table-empty", "YOLO 未产出精彩片段。点击「添加片段」手动创建。")
    );
    return;
  }

  editorState.segments.forEach((seg, idx) => {
    const card = renderSegmentCard(seg, idx);
    container.append(card);
  });

  // Init drag reorder
  initDragReorder(container);
}

function renderClipSequence() {
  const container = byId("clip-sequence");
  if (!container) return;
  clearChildren(container);
  editorState.segments.forEach((segment, index) => {
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
    state.textContent = editorState.dirty ? "Order not saved" : "Order synced";
  }
}

function renderSegmentCard(seg, idx) {
  const card = createElement("div", "segment-card");
  card.dataset.segmentId = seg.id;
  card.draggable = true;
  card.setAttribute("role", "listitem");
  card.setAttribute("tabindex", "0");

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
  const segType = seg.type || "auto";
  const typeLabel = segType === "manual" ? "手动" : segType === "merged" ? "合并" : segType === "split" ? "拆分" : "自动";
  const typeBadge = createElement("span", "segment-type-badge " + segType, typeLabel);
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

  const comment = findAgentComment(segmentId);

  byId("detail-placeholder").hidden = true;
  byId("detail-content").hidden = false;
  byId("detail-title").textContent = "片段 " + seg.id;
  byId("detail-score").textContent = formatNumber(Number(seg.score) * 100, 0) + " 分";
  byId("detail-time").textContent = formatTime(seg.start) + " – " + formatTime(seg.end);
  byId("detail-duration").textContent = formatDuration(seg.end - seg.start);
  byId("detail-keyframes").textContent = (seg.source_keyframes || []).join("、");
  byId("detail-type").textContent = seg.type === "manual" ? "手动添加" : seg.type === "merged" ? "合并片段" : seg.type === "split" ? "拆分片段" : "自动检测";
  byId("detail-confidence").textContent = formatNumber(Number(seg.score) * 100, 0) + "%";

  const agentStatus = comment ? comment.status : "pending";
  renderAgentComment(agentStatus, comment);
}

export function findAgentComment(segmentId) {
  return (
    editorState.agentComments.find((c) => c.segment_id === segmentId) || null
  );
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

let loadRetries = 0;
const MAX_LOAD_RETRIES = 2;

export function loadEditorData(jobId) {
  editorState.jobId = jobId;
  setEditorView("loading");

  api.get("/api/jobs/" + encodeURIComponent(jobId) + "/editor").then(
    (payload) => {
      loadRetries = 0;
      applyEditorData(payload);
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
  const job = payload.job && typeof payload.job === "object"
    ? payload.job
    : {};
  const jobId = payload.job_id || job.job_id;
  if (!jobId) {
    throw new Error("剪辑预览数据缺少任务编号。");
  }

  const rawSegments = Array.isArray(payload.segments)
    ? payload.segments
    : Array.isArray(payload.highlights)
      ? payload.highlights
      : [];
  const agentComments = Array.isArray(payload.agent_comments)
    ? payload.agent_comments.map((c) => Object.assign({}, c))
    : rawSegments
      .filter((seg) => seg && seg.agent_comment)
      .map((seg) => ({
        segment_id: seg.id,
        comment: seg.agent_comment,
        status: seg.agent_comment_status || "ready",
        review_status: seg.agent_review_status || null,
        evidence_refs: Array.isArray(seg.agent_evidence_refs)
          ? seg.agent_evidence_refs
          : [],
      }));

  const rawVideo = payload.video || {};

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
        score: seg.score != null ? Number(seg.score) : 0,
        source_keyframes: Array.isArray(seg.source_keyframes) ? seg.source_keyframes : [],
        type: seg.type || seg.source || "auto",
      };
    });

  // Restore saved reviews from server-side segment data
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
    status: payload.status || job.status || "unknown",
    video: {
      duration: Number(rawVideo.duration) || 0,
      filename: rawVideo.filename || "",
      path: rawVideo.path || rawVideo.url || null,
    },
    segments: segments,
    agent_comments: agentComments,
    keyframes: Array.isArray(payload.keyframes)
      ? payload.keyframes.filter((kf) => kf && typeof kf === "object")
      : [],
    output: payload.output || {},
    reviews: reviews,
    actions_enabled: payload.actions_enabled !== false,
    live_analysis: payload.live_analysis || null,
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
  editorState.reviews = data.reviews || {};
  editorState.dirty = false;
  editorState.selectedSegmentId = null;
  editorState.undoStack = [];
  editorState.redoStack = [];
  editorState.saveStatus = "saved";

  const actionsEnabled = data.actions_enabled !== false;
  ["save-review-button", "rough-cut-button", "open-export-button"].forEach((id) => {
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
      `${Number(live.completed_chunks) || 0} / ${Number(live.total_chunks) || 0} chunks`;
  }
  const detail = byId("live-analysis-detail");
  if (detail) detail.textContent = live.message || "";
  const badge = byId("live-analysis-badge");
  if (badge) {
    badge.className = `live-analysis-badge ${live.final ? "completed" : "running"}`;
    badge.textContent = live.final ? "Analysis complete" : "Analysis running";
  }

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
  updateAutoSaveIndicator();

  // Show auto-save indicator
  byId("auto-save-indicator").hidden = false;

  // Check for auto-saved draft
  checkDraft();

  if (editorState.segments.length > 0) {
    selectSegment(editorState.segments[0].id);
  }
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
