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
}

export function findAgentComment(segmentId) {
  return (
    editorState.agentComments.find((c) => c.segment_id === segmentId) || null
  );
}

export function renderAgentComment(segmentComment) {
  const agent = editorState.agentReport;
  const avail = agent ? agent.availability : null;
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
      ? "Agent 已完成"
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

  // 证据引用：来自 agent.evidence_refs
  const evidenceContainer = byId("agent-evidence");
  clearChildren(evidenceContainer);
  (agent.evidence_refs || []).forEach((ref) => {
    const item = createElement("div", "agent-evidence-item");
    item.append(
      createElement("span", "agent-evidence-type", ref.type || "ref"),
      createElement("span", "agent-evidence-source", ref.source_id || ref.ref_id || "")
    );
    evidenceContainer.append(item);
  });
  if (!agent.evidence_refs || !agent.evidence_refs.length) {
    evidenceContainer.append(
      createElement("p", "agent-field-value", "无证据引用。")
    );
  }

  // 知识库引用：来自 agent.knowledge_refs
  const knowledgeContainer = byId("agent-knowledge");
  clearChildren(knowledgeContainer);
  (agent.knowledge_refs || []).forEach((ref) => {
    const item = createElement("div", "agent-evidence-item");
    item.append(
      createElement("span", "agent-evidence-type", "知识库"),
      createElement("span", "agent-evidence-source", ref.title || ref.knowledge_id || "")
    );
    knowledgeContainer.append(item);
  });
  if (!agent.knowledge_refs || !agent.knowledge_refs.length) {
    knowledgeContainer.append(
      createElement("p", "agent-field-value", "无知识库引用。")
    );
  }
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

  // per-segment evidence_refs — 字符串数组，不做 ref.type/ref.source_id 解构
  if (segmentComment.evidence_refs && segmentComment.evidence_refs.length) {
    const refsHtml = segmentComment.evidence_refs.map((ref) =>
      '<span class="agent-evidence-item">' + escapeHtml(typeof ref === "string" ? ref : String(ref)) + '</span>'
    ).join("");
    parts.push(
      '<div class="agent-field"><span class="agent-field-label">相关证据</span>' +
      '<div class="agent-evidence-list">' + refsHtml + '</div></div>'
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
  if (!jobId) return;

  api.get("/api/jobs/" + encodeURIComponent(jobId) + "/report-data").then(
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
    },
    (error) => {
      // Agent 报告不可用不阻塞编辑 — 面板显示 pending 状态
      editorState.agentReport = null;
      editorState.agentComments = [];
      if (editorState.selectedSegmentId) {
        renderSegmentDetail(editorState.selectedSegmentId);
      }
    }
  );
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
        // /editor 内嵌的 Agent 预览（/report-data 加载前用于快速展示）
        _agentPreview: {
          comment: seg.agent_comment || null,
          commentStatus: seg.agent_comment_status || null,
          reviewStatus: seg.agent_review_status || null,
          evidenceRefs: Array.isArray(seg.agent_evidence_refs) ? seg.agent_evidence_refs : [],
        },
      };
    });

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
      // 新后端：video.url 直接可用；旧后端：video.path 需拼接
      url: videoUrl,
      path: videoPath,
    },
    segments: segments,
    // agent_comments 不再从 /editor 聚合数据中读取 — 由 /report-data 独立加载
    agent_comments: [],
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
  editorState.agentReport = null;
  editorState.agentComments = [];
  editorState.keyframes = [];
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

  // 独立加载完整 Agent 报告（新后端 /report-data，不再从 /editor 聚合数据中内嵌）
  loadAgentReport(editorState.jobId);

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
