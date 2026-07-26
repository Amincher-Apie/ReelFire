"use strict";

/* ===================================================================
   ReelFire Editor — 剪辑预览工作台
   所有动态文本使用 textContent；不通过评分伪造 Agent 评论。
   =================================================================== */

// ── 状态 ─────────────────────────────────────────────────────────────
const state = {
  jobId: null,
  editorData: null,
  segments: [],
  agentComments: [],
  keyframes: [],
  video: null,
  selectedSegmentId: null,
  videoElement: null,
  timelineBound: false,
  dirty: false,
  reviews: {},       // { segmentId: { recommendation: "pass"|"needs_review"|"reject", note: "" } }
  output: null,      // { video, contact_sheet, ... }
};

// ── 工具函数 ─────────────────────────────────────────────────────────
function byId(id) {
  return document.getElementById(id);
}

function clearChildren(element) {
  if (element) element.replaceChildren();
}

function createElement(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = String(text);
  return el;
}

function formatTime(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s) || s < 0) return "00:00";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

function formatDuration(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s)) return "—";
  if (s < 60) return `${s.toFixed(1)} 秒`;
  const m = Math.floor(s / 60);
  return `${m} 分 ${(s % 60).toFixed(0)} 秒`;
}

function formatNumber(value, digits = 1) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

function safeOn(id, event, handler) {
  var el = byId(id);
  if (el) el.addEventListener(event, handler);
}

function showToast(message, type) {
  const container = byId("toast-container");
  if (!container) return;
  const toast = createElement("div", `toast ${type || "info"}`, message);
  container.append(toast);
  window.setTimeout(function () {
    toast.remove();
  }, 4200);
}

// ── API 封装 ─────────────────────────────────────────────────────────
const api = {
  request: function (url, options) {
    return fetch(url, options || {}).then(function (response) {
      return response.json().then(
        function (payload) {
          if (!response.ok || payload.ok === false) {
            throw new Error(payload.error || "请求失败（HTTP " + response.status + "）");
          }
          return payload;
        },
        function () {
          throw new Error("服务返回了无法解析的响应（HTTP " + response.status + "）");
        }
      );
    });
  },
  get: function (url) {
    return this.request(url);
  },
  post: function (url, body) {
    return this.request(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  },
  patch: function (url, body) {
    return this.request(url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
};

// ── 认证 ─────────────────────────────────────────────────────────────
function loadUser() {
  api.get("/api/auth/me").then(
    function (payload) {
      byId("user-name").textContent = payload.user.display_name || payload.user.username;
      byId("user-info").hidden = false;
      byId("login-link").hidden = true;
    },
    function () {
      byId("user-info").hidden = true;
      byId("login-link").hidden = false;
    }
  );
}

// ── 主题 ─────────────────────────────────────────────────────────────
function initTheme() {
  var allowed = ["dark", "light", "ocean", "forest"];
  var saved = localStorage.getItem("reelfire-theme");
  var theme = allowed.indexOf(saved) !== -1 ? saved : "dark";
  document.body.dataset.theme = theme;
  var buttons = document.querySelectorAll("[data-theme-value]");
  buttons.forEach(function (button) {
    var active = button.dataset.themeValue === theme;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
    button.addEventListener("click", function () {
      var next = button.dataset.themeValue;
      if (allowed.indexOf(next) === -1) return;
      document.body.dataset.theme = next;
      localStorage.setItem("reelfire-theme", next);
      buttons.forEach(function (item) {
        var sel = item.dataset.themeValue === next;
        item.classList.toggle("active", sel);
        item.setAttribute("aria-pressed", String(sel));
      });
    });
  });
}

// ── 状态视图切换 ─────────────────────────────────────────────────────
function setView(view) {
  ["loading", "error", "empty", "content"].forEach(function (name) {
    byId("editor-" + name).hidden = name !== view;
  });
}

// ── 视频播放器 ───────────────────────────────────────────────────────
function renderVideo() {
  var videoEl = byId("editor-video");
  var placeholder = byId("video-placeholder");
  var status = byId("video-status");
  var video = state.video;

  if (video && video.path) {
    videoEl.src = video.path;
    videoEl.hidden = false;
    placeholder.hidden = true;
    videoEl.onloadedmetadata = function () {
      var actualDuration = Number(videoEl.duration);
      if (Number.isFinite(actualDuration) && actualDuration > 0) {
        state.video.duration = actualDuration;
        byId("timeline-duration").textContent = formatTime(actualDuration);
        renderTimeline();
      }
    };
    videoEl.onerror = function () {
      videoEl.hidden = true;
      placeholder.hidden = false;
      status.textContent = "当前视频加载失败，请检查源文件格式或任务输出是否完整。";
    };
    videoEl.load();
  } else {
    videoEl.hidden = true;
    placeholder.hidden = false;
    status.textContent = "当前任务没有可预览的视频源。";
  }

  if (video) {
    byId("timeline-duration").textContent = formatTime(video.duration);
  }

  state.videoElement = videoEl;
}

// ── 时间轴 ───────────────────────────────────────────────────────────
function renderTimeline() {
  if (!state.video) return;
  var duration = Number(state.video.duration);
  if (!Number.isFinite(duration) || duration <= 0) duration = 0;
  var scrubber = byId("timeline-scrubber");
  var track = byId("timeline-track");
  scrubber.max = String(duration);
  scrubber.value = "0";
  track.setAttribute("aria-valuemax", String(duration));

  // 片段标记条
  var segmentsBar = byId("timeline-segments-bar");
  clearChildren(segmentsBar);
  state.segments.forEach(function (seg, idx) {
    var left = duration > 0 ? (seg.start / duration) * 100 : 0;
    var width =
      duration > 0
        ? Math.max(((seg.end - seg.start) / duration) * 100, 0.5)
        : 0;
    var marker = createElement("div", "timeline-segment-marker seg-" + idx);
    marker.style.left = left + "%";
    marker.style.width = width + "%";
    marker.title =
      "片段 " +
      seg.id +
      ": " +
      formatTime(seg.start) +
      " – " +
      formatTime(seg.end) +
      " (评分 " +
      formatNumber(Number(seg.score) * 100, 0) +
      ")";
    marker.setAttribute("role", "button");
    marker.setAttribute("aria-label", marker.title);
    marker.setAttribute("tabindex", "0");
    marker.addEventListener("click", function (e) {
      e.stopPropagation();
      selectSegment(seg.id);
      seekTo(seg.start);
    });
    marker.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        selectSegment(seg.id);
        seekTo(seg.start);
      }
    });
    segmentsBar.append(marker);
  });

  updatePlayhead(0);
}

function updatePlayhead(currentTime) {
  if (!state.video) return;
  var duration = state.video.duration;
  var pct = duration > 0 ? Math.min((currentTime / duration) * 100, 100) : 0;
  var playhead = byId("timeline-playhead");
  playhead.style.left = pct + "%";

  var track = byId("timeline-track");
  track.setAttribute("aria-valuenow", String(Math.round(currentTime)));

  byId("timeline-current").textContent = formatTime(currentTime);
  byId("timeline-scrubber").value = String(currentTime);

  // 高亮当前所在片段
  highlightSegmentAtTime(currentTime);
}

function seekTo(time) {
  var duration = state.video ? Number(state.video.duration) : 0;
  var target = Number(time);
  if (!Number.isFinite(target)) return;
  target = Math.max(0, duration > 0 ? Math.min(target, duration) : target);
  if (state.videoElement && state.videoElement.src) {
    state.videoElement.currentTime = target;
  }
  updatePlayhead(target);
}

function highlightSegmentAtTime(time) {
  var found = null;
  state.segments.forEach(function (seg) {
    if (time >= seg.start && time <= seg.end) {
      found = seg.id;
    }
  });

  // 更新片段标记条高亮
  var markers = document.querySelectorAll(".timeline-segment-marker");
  markers.forEach(function (marker) {
    marker.classList.remove("active");
  });

  // 更新卡片高亮（如果与当前选中的不同）
  if (found && found !== state.selectedSegmentId) {
    var idx = state.segments.findIndex(function (s) {
      return s.id === found;
    });
    if (idx >= 0) {
      var target = markers[idx];
      if (target) target.classList.add("active");
    }
  }
}

function bindTimelineEvents() {
  if (state.timelineBound) return;
  state.timelineBound = true;
  var track = byId("timeline-track");
  var scrubber = byId("timeline-scrubber");
  var playButton = byId("timeline-play");
  var videoEl = state.videoElement;
  var isDragging = false;

  // 播放/暂停按钮
  playButton.addEventListener("click", function () {
    if (videoEl && videoEl.src) {
      if (videoEl.paused) {
        videoEl.play();
        playButton.setAttribute("aria-label", "暂停");
      } else {
        videoEl.pause();
        playButton.setAttribute("aria-label", "播放");
      }
    }
  });

  // 时间轴点击
  track.addEventListener("click", function (e) {
    if (!state.video) return;
    var rect = track.getBoundingClientRect();
    var pct = (e.clientX - rect.left) / rect.width;
    seekTo(pct * state.video.duration);
  });

  // 时间轴拖动
  track.addEventListener("mousedown", function (e) {
    isDragging = true;
    document.body.style.userSelect = "none";
  });

  document.addEventListener("mousemove", function (e) {
    if (!isDragging || !state.video) return;
    var rect = track.getBoundingClientRect();
    var pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    seekTo(pct * state.video.duration);
  });

  document.addEventListener("mouseup", function () {
    if (isDragging) {
      isDragging = false;
      document.body.style.userSelect = "";
    }
  });

  // 时间轴键盘
  track.addEventListener("keydown", function (e) {
    if (!state.video) return;
    var step = state.video.duration / 100;
    if (e.key === "ArrowRight") {
      e.preventDefault();
      seekTo(Math.min((state.videoElement ? state.videoElement.currentTime : 0) + step, state.video.duration));
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      seekTo(Math.max((state.videoElement ? state.videoElement.currentTime : 0) - step, 0));
    }
  });

  scrubber.addEventListener("input", function () {
    if (videoEl && !videoEl.paused) videoEl.pause();
    seekTo(Number(scrubber.value));
  });

  // 视频 timeupdate 同步
  if (videoEl) {
    videoEl.addEventListener("timeupdate", function () {
      if (!isDragging) {
        updatePlayhead(videoEl.currentTime);
      }
    });
  }
}

// ── 片段列表 ─────────────────────────────────────────────────────────
function selectSegment(segmentId) {
  state.selectedSegmentId = segmentId;

  var rows = document.querySelectorAll(".segment-row");
  rows.forEach(function (row) {
    var selected = row.dataset.segmentId === segmentId;
    row.classList.toggle("selected", selected);
    row.setAttribute("aria-current", selected ? "true" : "false");
  });

  // 片段标记高亮
  var markers = document.querySelectorAll(".timeline-segment-marker");
  var idx = state.segments.findIndex(function (s) {
    return s.id === segmentId;
  });
  markers.forEach(function (m, i) {
    m.classList.toggle("active", i === idx);
  });

  renderSegmentDetail(segmentId);
  renderReviewEditor(segmentId);
  renderBoundaryEditor(segmentId);
  renderSortButtons(segmentId);
}

function renderSegmentList() {
  var container = byId("highlight-list");
  clearChildren(container);
  byId("segments-count").textContent = state.segments.length + " 个片段";

  if (!state.segments.length) {
    container.append(
      createElement("p", "segment-table-empty", "YOLO 未产出精彩片段。")
    );
    return;
  }

  state.segments.forEach(function (seg, idx) {
    var comment = findAgentComment(seg.id);
    var status = comment ? comment.status : "pending";
    var displayStatus = status === "completed" ? "ready" : status;
    var row = createElement("div", "segment-row");
    row.dataset.segmentId = seg.id;
    var rev = state.reviews[seg.id];
    if (rev && rev.recommendation) {
      row.dataset.review = rev.recommendation;
    }
    row.setAttribute("role", "row");
    row.setAttribute("tabindex", "0");
    row.setAttribute(
      "aria-label",
      "片段 " + (idx + 1) + "，" + formatTime(seg.start) + " 到 " + formatTime(seg.end)
    );

    var timeCell = createElement(
      "span",
      "segment-time-cell",
      formatTime(seg.start) + " : " + formatTime(seg.end)
    );
    timeCell.setAttribute("role", "cell");
    timeCell.append(
      createElement("small", "", formatNumber(seg.end - seg.start, 1) + " 秒")
    );

    var commentText =
      displayStatus === "ready" && comment && comment.summary
        ? comment.summary
        : displayStatus === "pending"
        ? "Agent 分析尚未完成"
        : "Agent 最终评论不可用";
    var commentCell = createElement(
      "span",
      "segment-comment-cell " + displayStatus,
      commentText
    );
    commentCell.setAttribute("role", "cell");
    row.append(timeCell, commentCell);

    row.addEventListener("click", function () {
      selectSegment(seg.id);
      seekTo(seg.start);
    });
    row.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        selectSegment(seg.id);
        seekTo(seg.start);
      }
    });

    container.append(row);
  });
}

function findAgentComment(segmentId) {
  return (
    state.agentComments.find(function (c) {
      return c.segment_id === segmentId;
    }) || null
  );
}

// ── 片段详情 + Agent 评论 ────────────────────────────────────────────
function renderSegmentDetail(segmentId) {
  if (!segmentId) return;

  var seg = state.segments.find(function (s) {
    return s.id === segmentId;
  });
  if (!seg) return;

  var comment = findAgentComment(segmentId);

  byId("detail-placeholder").hidden = true;
  byId("detail-content").hidden = false;
  byId("detail-title").textContent = "片段 " + seg.id;
  byId("detail-score").textContent = formatNumber(Number(seg.score) * 100, 0) + " 分";
  byId("detail-time").textContent = formatTime(seg.start) + " – " + formatTime(seg.end);
  byId("detail-duration").textContent = formatNumber(seg.end - seg.start, 1) + " 秒";
  byId("detail-keyframes").textContent = (seg.source_keyframes || []).join("、");

  // Agent 评论状态
  var agentStatus = comment ? comment.status : "pending";
  renderAgentComment(agentStatus, comment);
}

function renderAgentComment(status, comment) {
  var badge = byId("agent-status-badge");
  badge.className = "agent-status-badge " + status;
  var badgeText =
    status === "completed"
      ? "Agent 已完成"
      : status === "pending"
      ? "待 Agent 分析"
      : "Agent 不可用";
  badge.textContent = badgeText;

  // 隐藏所有状态内容
  byId("agent-completed-content").hidden = true;
  byId("agent-pending-content").hidden = true;
  byId("agent-unavailable-content").hidden = true;

  if (status === "completed" && comment) {
    renderAgentCompleted(comment);
    byId("agent-completed-content").hidden = false;
  } else if (status === "pending") {
    byId("agent-pending-content").hidden = false;
  } else {
    var msg =
      comment && comment.error
        ? comment.error
        : "Agent 服务当前不可用，以下为基于 CV 检测的规则输出。";
    byId("agent-unavailable-message").textContent = msg;
    byId("agent-unavailable-content").hidden = false;
  }
}

function renderAgentCompleted(comment) {
  // 摘要 — 使用 textContent
  byId("agent-summary").textContent = comment.summary || "Agent 未生成摘要。";

  // 标签
  var tagsContainer = byId("agent-tags");
  clearChildren(tagsContainer);
  (comment.tags || []).forEach(function (tag) {
    var t = createElement("span", "agent-tag", tag.name);
    t.title = tag.description || "";
    tagsContainer.append(t);
  });
  if (!comment.tags || !comment.tags.length) {
    tagsContainer.append(createElement("span", "agent-tag", "无标签"));
  }

  // 建议
  var suggestionsContainer = byId("agent-suggestions");
  clearChildren(suggestionsContainer);
  (comment.suggestions || []).forEach(function (sug) {
    var item = createElement("div", "agent-suggestion-item");
    var titleSpan = createElement("strong");
    titleSpan.textContent = sug.title;
    var prioritySpan = createElement(
      "span",
      "agent-suggestion-priority " + (sug.priority || "low"),
      sug.priority === "high" ? "高" : sug.priority === "medium" ? "中" : "低"
    );
    titleSpan.append(prioritySpan);
    var actionP = createElement("p", "", sug.action || "");
    item.append(titleSpan, actionP);
    suggestionsContainer.append(item);
  });
  if (!comment.suggestions || !comment.suggestions.length) {
    suggestionsContainer.append(
      createElement("p", "agent-field-value", "无建议。")
    );
  }

  // 审核意见
  var reviewContainer = byId("agent-review");
  clearChildren(reviewContainer);
  if (comment.review) {
    var rec = comment.review.recommendation || "needs_review";
    var recLabel =
      rec === "pass" ? "通过" : rec === "reject" ? "不通过" : "待复核";
    var recSpan = createElement("span", "agent-review-rec " + rec, recLabel);
    var confSpan = createElement(
      "span",
      "agent-review-confidence",
      "置信度 " + formatNumber(Number(comment.review.confidence) * 100, 0) + "%"
    );
    reviewContainer.append(recSpan, confSpan);

    if (comment.review.reasons && comment.review.reasons.length) {
      var reasonsList = createElement("ul", "agent-review-reasons");
      comment.review.reasons.forEach(function (r) {
        reasonsList.append(createElement("li", "", r));
      });
      reviewContainer.append(reasonsList);
    }
  }

  // 证据引用
  var evidenceContainer = byId("agent-evidence");
  clearChildren(evidenceContainer);
  (comment.evidence_refs || []).forEach(function (ref) {
    var item = createElement("div", "agent-evidence-item");
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

  // 知识库引用
  var knowledgeContainer = byId("agent-knowledge");
  clearChildren(knowledgeContainer);
  (comment.knowledge_refs || []).forEach(function (ref) {
    var item = createElement("div", "agent-evidence-item");
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

// ── 数据加载 ─────────────────────────────────────────────────────────
function loadEditorData(jobId) {
  state.jobId = jobId;
  setView("loading");

  api.get("/api/jobs/" + encodeURIComponent(jobId) + "/editor").then(
    function (payload) {
      applyEditorData(payload);
    },
    function (error) {
      setView("error");
      byId("editor-error-message").textContent =
        error.message || "剪辑预览数据读取失败。";
    }
  );
}

function normalizeEditorData(payload) {
  // 映射后端 GET /api/jobs/{job_id}/editor 实际响应（1.0 契约）
  // 响应字段：job_id, status, video{duration,path,...}, segments[], agent_comments[], keyframes[]
  if (!payload.job_id || !payload.video) {
    throw new Error("剪辑预览数据缺少必要字段。");
  }

  var videoPath = payload.video.path || null;

  // 将 agent_comments 数组转换为按 segment_id 索引的查找
  var agentComments = Array.isArray(payload.agent_comments)
    ? payload.agent_comments.map(function (c) { return Object.assign({}, c); })
    : [];

  var segments = (Array.isArray(payload.segments) ? payload.segments : []).map(function (seg) {
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
      path: videoPath,
    },
    segments: segments,
    agent_comments: agentComments,
    keyframes: Array.isArray(payload.keyframes) ? payload.keyframes : [],
    output: payload.output || {},
  };
}

function applyEditorData(payload) {
  var data;
  try {
    data = normalizeEditorData(payload);
  } catch (error) {
    setView("error");
    byId("editor-error-message").textContent = error.message;
    return;
  }
  state.editorData = data;
  state.video = data.video || null;
  state.segments = Array.isArray(data.segments) ? data.segments : [];
  state.agentComments = Array.isArray(data.agent_comments) ? data.agent_comments : [];
  state.keyframes = Array.isArray(data.keyframes) ? data.keyframes : [];
  state.output = data.output || null;
  state.reviews = {};
  state.dirty = false;
  state.selectedSegmentId = null;

  // 更新头部任务信息
  byId("header-job-id").textContent = data.job_id || state.jobId || "—";
  byId("header-meta").textContent =
    (data.video ? formatDuration(data.video.duration) + " · " : "") +
    state.segments.length +
    " 个片段";

  setView("content");

  renderVideo();
  renderTimeline();
  renderSegmentList();
  bindTimelineEvents();
  renderStatsDashboard();
  renderTrajectoryPanel();
  updateDirtyIndicator();

  // 默认选中第一个片段
  if (state.segments.length > 0) {
    selectSegment(state.segments[0].id);
  }
}

// ── 三态审核编辑 ──────────────────────────────────────────────────────
function renderReviewEditor(segmentId) {
  var container = byId("review-editor");
  if (!container) return;
  container.hidden = false;

  var review = state.reviews[segmentId];
  var recommendation = review ? review.recommendation : "";
  var note = review ? review.note || "" : "";

  // 三态按钮
  var buttons = container.querySelectorAll(".review-option");
  buttons.forEach(function (btn) {
    var active = btn.dataset.reviewValue === recommendation;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", String(active));
  });

  // 备注
  var noteField = container.querySelector(".review-note-field");
  if (noteField) noteField.value = note;
}

function setReviewStatus(segmentId, value) {
  if (!segmentId) return;
  if (!state.reviews[segmentId]) {
    state.reviews[segmentId] = { recommendation: "", note: "" };
  }
  state.reviews[segmentId].recommendation = value;
  markDirty();
  renderReviewEditor(segmentId);
  renderSegmentList();
  renderStatsDashboard();
}

function setReviewNote(segmentId, note) {
  if (!segmentId) return;
  if (!state.reviews[segmentId]) {
    state.reviews[segmentId] = { recommendation: "", note: "" };
  }
  state.reviews[segmentId].note = note;
  markDirty();
}

// ── 片段边界编辑 ──────────────────────────────────────────────────────
function renderBoundaryEditor(segmentId) {
  var container = byId("boundary-editor");
  if (!container) return;

  var seg = state.segments.find(function (s) { return s.id === segmentId; });
  if (!seg) { container.hidden = true; return; }
  container.hidden = false;

  var startInput = container.querySelector(".boundary-start");
  var endInput = container.querySelector(".boundary-end");
  if (startInput) startInput.value = seg.start;
  if (endInput) endInput.value = seg.end;

  var duration = state.video ? state.video.duration : 0;
  if (startInput) startInput.max = String(duration);
  if (endInput) endInput.max = String(duration);
}

function applyBoundaryChange(segmentId, field, rawValue) {
  var seg = state.segments.find(function (s) { return s.id === segmentId; });
  if (!seg) return;

  var value = Number(rawValue);
  if (!Number.isFinite(value) || value < 0) return;

  var duration = state.video ? state.video.duration : Infinity;
  if (field === "start") {
    if (value >= seg.end) return;
    if (value > duration) return;
    seg.start = value;
  } else if (field === "end") {
    if (value <= seg.start) return;
    if (value > duration) return;
    seg.end = value;
  }

  markDirty();
  renderTimeline();
  renderSegmentList();
  renderBoundaryEditor(segmentId);
  renderStatsDashboard();
}

// ── 片段排序 ──────────────────────────────────────────────────────────
function renderSortButtons(segmentId) {
  var container = byId("sort-buttons");
  if (!container) return;
  container.hidden = false;

  var idx = state.segments.findIndex(function (s) { return s.id === segmentId; });
  var upBtn = container.querySelector(".sort-up");
  var downBtn = container.querySelector(".sort-down");
  if (upBtn) upBtn.disabled = idx <= 0;
  if (downBtn) downBtn.disabled = idx < 0 || idx >= state.segments.length - 1;
}

function reorderSegment(segmentId, direction) {
  var idx = state.segments.findIndex(function (s) { return s.id === segmentId; });
  if (idx < 0) return;
  var swapIdx = direction === "up" ? idx - 1 : idx + 1;
  if (swapIdx < 0 || swapIdx >= state.segments.length) return;

  // 交换 order
  var tmp = state.segments[idx].order;
  state.segments[idx].order = state.segments[swapIdx].order;
  state.segments[swapIdx].order = tmp;

  // 重排数组
  state.segments.sort(function (a, b) { return a.order - b.order; });

  markDirty();
  renderTimeline();
  renderSegmentList();
  renderSortButtons(segmentId);
  var newIdx = state.segments.findIndex(function (s) { return s.id === segmentId; });
  if (newIdx >= 0) selectSegment(state.segments[newIdx].id);
}

// ── Canvas 工具 ───────────────────────────────────────────────────────
function canvasColors() {
  var style = getComputedStyle(document.body);
  return {
    bg: style.getPropertyValue("--bg").trim() || "#080b14",
    panel: style.getPropertyValue("--panel-soft").trim() || "#101727",
    text: style.getPropertyValue("--text").trim() || "#f7f8fc",
    textMuted: style.getPropertyValue("--text-muted").trim() || "#9ba6bc",
    textFaint: style.getPropertyValue("--text-faint").trim() || "#6e7890",
    border: style.getPropertyValue("--border").trim() || "rgba(255,255,255,0.1)",
    primary: style.getPropertyValue("--primary").trim() || "#ff4d70",
    accent: style.getPropertyValue("--accent").trim() || "#66a6ff",
    success: style.getPropertyValue("--success").trim() || "#35d399",
    warning: style.getPropertyValue("--warning").trim() || "#f5bd4f",
    danger: style.getPropertyValue("--danger").trim() || "#ff667d",
  };
}

function setupHiDPI(canvas, width, height) {
  var dpr = window.devicePixelRatio || 1;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = width + "px";
  canvas.style.height = height + "px";
  var ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  return ctx;
}

// ── Statistics Dashboard ──────────────────────────────────────────────
function renderStatsDashboard() {
  var dash = byId("stats-dashboard");
  if (!dash) return;
  dash.hidden = false;

  // 计数
  var counts = { pass: 0, needs_review: 0, reject: 0, unset: 0 };
  state.segments.forEach(function (seg) {
    var r = state.reviews[seg.id];
    var rec = r ? r.recommendation : "";
    if (rec === "pass") counts.pass++;
    else if (rec === "needs_review") counts.needs_review++;
    else if (rec === "reject") counts.reject++;
    else counts.unset++;
  });

  // 更新页面上的四个统计按钮
  ["pass", "needs-review", "reject", "unset"].forEach(function (key) {
    var el = byId("stat-" + key);
    if (el) el.textContent = String(counts[key.replace("-", "_")] || counts[key] || 0);
  });
}

function showStatsDialog() {
  var dialog = byId("stats-dialog");
  if (!dialog) return;

  // 刷新弹窗内的计数
  var counts = { pass: 0, needs_review: 0, reject: 0, unset: 0 };
  state.segments.forEach(function (seg) {
    var r = state.reviews[seg.id];
    var rec = r ? r.recommendation : "";
    if (rec === "pass") counts.pass++;
    else if (rec === "needs_review") counts.needs_review++;
    else if (rec === "reject") counts.reject++;
    else counts.unset++;
  });

  var dlgPass = byId("dlg-stat-pass");
  var dlgNeeds = byId("dlg-stat-needs-review");
  var dlgReject = byId("dlg-stat-reject");
  var dlgUnset = byId("dlg-stat-unset");
  if (dlgPass) dlgPass.textContent = String(counts.pass);
  if (dlgNeeds) dlgNeeds.textContent = String(counts.needs_review);
  if (dlgReject) dlgReject.textContent = String(counts.reject);
  if (dlgUnset) dlgUnset.textContent = String(counts.unset);

  // 绘制弹窗内的图表
  drawScoreDistribution(byId("chart-score-dist"));
  drawDurationChart(byId("chart-duration"));
  drawReviewPieChart(byId("chart-review-pie"), counts);

  dialog.showModal();
}

function drawScoreDistribution(canvas) {
  if (!canvas) return;
  var W = canvas.parentElement ? canvas.parentElement.clientWidth - 32 : 380;
  var H = 200;
  var ctx = setupHiDPI(canvas, W, H);
  var colors = canvasColors();
  var segs = state.segments;
  if (!segs.length) {
    ctx.fillStyle = colors.textFaint;
    ctx.font = "12px " + getComputedStyle(document.body).fontFamily;
    ctx.textAlign = "center";
    ctx.fillText("无片段数据", W / 2, H / 2);
    return;
  }

  var barMaxW = Math.min(40, (W - 80) / segs.length);
  var gap = Math.max(4, (W - 80 - barMaxW * segs.length) / (segs.length + 1));
  var chartBottom = H - 28;
  var chartTop = 20;

  segs.forEach(function (seg, i) {
    var x = 40 + gap + i * (barMaxW + gap);
    var barH = ((chartBottom - chartTop) * (Number(seg.score) || 0));
    var y = chartBottom - barH;

    ctx.fillStyle = colors.accent;
    ctx.fillRect(x, y, barMaxW, barH);

    // 标签
    ctx.fillStyle = colors.textFaint;
    ctx.font = "9px " + getComputedStyle(document.body).fontFamily;
    ctx.textAlign = "center";
    ctx.fillText(seg.id || ("#" + (i + 1)), x + barMaxW / 2, chartBottom + 14);

    // 分值
    ctx.fillStyle = colors.textMuted;
    ctx.font = "600 9px " + getComputedStyle(document.body).fontFamily;
    ctx.fillText(Math.round((Number(seg.score) || 0) * 100), x + barMaxW / 2, y - 4);
  });

  // 基线
  ctx.strokeStyle = colors.border;
  ctx.beginPath();
  ctx.moveTo(35, chartBottom);
  ctx.lineTo(W - 10, chartBottom);
  ctx.stroke();
}

function drawDurationChart(canvas) {
  if (!canvas) return;
  var W = canvas.parentElement ? canvas.parentElement.clientWidth - 32 : 380;
  var H = 200;
  var ctx = setupHiDPI(canvas, W, H);
  var colors = canvasColors();
  var segs = state.segments;
  if (!segs.length) {
    ctx.fillStyle = colors.textFaint;
    ctx.font = "12px " + getComputedStyle(document.body).fontFamily;
    ctx.textAlign = "center";
    ctx.fillText("无片段数据", W / 2, H / 2);
    return;
  }

  var durations = segs.map(function (s) { return Math.max(0, s.end - s.start); });
  var maxDur = Math.max.apply(null, durations);
  if (maxDur <= 0) maxDur = 1;

  var barMaxW = Math.min(40, (W - 80) / segs.length);
  var gap = Math.max(4, (W - 80 - barMaxW * segs.length) / (segs.length + 1));
  var chartBottom = H - 28;
  var chartTop = 20;

  segs.forEach(function (seg, i) {
    var x = 40 + gap + i * (barMaxW + gap);
    var barH = ((chartBottom - chartTop) * (durations[i] / maxDur));
    var y = chartBottom - barH;

    ctx.fillStyle = colors.primary;
    ctx.fillRect(x, y, barMaxW, barH);

    ctx.fillStyle = colors.textFaint;
    ctx.font = "9px " + getComputedStyle(document.body).fontFamily;
    ctx.textAlign = "center";
    ctx.fillText(seg.id || ("#" + (i + 1)), x + barMaxW / 2, chartBottom + 14);

    ctx.fillStyle = colors.textMuted;
    ctx.font = "600 9px " + getComputedStyle(document.body).fontFamily;
    ctx.fillText(durations[i].toFixed(1) + "s", x + barMaxW / 2, y - 4);
  });

  ctx.strokeStyle = colors.border;
  ctx.beginPath();
  ctx.moveTo(35, chartBottom);
  ctx.lineTo(W - 10, chartBottom);
  ctx.stroke();
}

function drawReviewPieChart(canvas, counts) {
  if (!canvas) return;
  var size = 180;
  var ctx = setupHiDPI(canvas, size, size);
  var colors = canvasColors();
  var cx = size / 2, cy = size / 2, radius = Math.min(cx, cy) - 16;
  var total = counts.pass + counts.needs_review + counts.reject + counts.unset;

  if (total === 0) {
    ctx.fillStyle = colors.textFaint;
    ctx.font = "12px " + getComputedStyle(document.body).fontFamily;
    ctx.textAlign = "center";
    ctx.fillText("暂无审核数据", cx, cy);
    return;
  }

  var slices = [
    { value: counts.pass, color: colors.success },
    { value: counts.needs_review, color: colors.warning },
    { value: counts.reject, color: colors.danger },
    { value: counts.unset, color: colors.textFaint },
  ];

  var angle = -Math.PI / 2;
  slices.forEach(function (slice) {
    if (slice.value <= 0) return;
    var sliceAngle = (slice.value / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, angle, angle + sliceAngle);
    ctx.closePath();
    ctx.fillStyle = slice.color;
    ctx.fill();
    angle += sliceAngle;
  });

  // 中心白色圆（甜甜圈效果）
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.55, 0, Math.PI * 2);
  ctx.fillStyle = colors.bg;
  ctx.fill();

  ctx.fillStyle = colors.textMuted;
  ctx.font = "bold 14px " + getComputedStyle(document.body).fontFamily;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(String(total), cx, cy);
}

// ── 轨迹可视化 ─────────────────────────────────────────────────────────
function renderTrajectoryPanel() {
  var panel = byId("trajectory-panel");
  if (!panel) return;

  var hasTrajectory = state.keyframes.some(function (kf) {
    return Array.isArray(kf.trajectory) && kf.trajectory.length > 0;
  });

  panel.hidden = false;
  var placeholder = byId("trajectory-placeholder");
  var canvas = byId("trajectory-canvas");

  if (!hasTrajectory) {
    if (placeholder) placeholder.hidden = false;
    if (canvas) canvas.hidden = true;
    return;
  }

  if (placeholder) placeholder.hidden = true;
  if (canvas) {
    canvas.hidden = false;
    drawTrajectory(canvas);
  }
}

function drawTrajectory(canvas) {
  if (!canvas) return;
  var W = canvas.parentElement ? canvas.parentElement.clientWidth - 32 : 500;
  var H = 280;
  var ctx = setupHiDPI(canvas, W, H);
  var colors = canvasColors();

  // 背景
  ctx.fillStyle = colors.bg;
  ctx.fillRect(0, 0, W, H);

  // 收集所有轨迹点
  var allBoxes = [];
  state.keyframes.forEach(function (kf) {
    var traj = kf.trajectory;
    if (!Array.isArray(traj)) return;
    traj.forEach(function (box) {
      allBoxes.push({
        trackId: box.track_id || 0,
        x: Number(box.x) || 0,
        y: Number(box.y) || 0,
        w: Number(box.w) || 0,
        h: Number(box.h) || 0,
        timestamp: Number(kf.timestamp) || 0,
      });
    });
  });

  if (!allBoxes.length) return;

  // 计算边界
  var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  allBoxes.forEach(function (b) {
    if (b.x < minX) minX = b.x;
    if (b.y < minY) minY = b.y;
    if (b.x + b.w > maxX) maxX = b.x + b.w;
    if (b.y + b.h > maxY) maxY = b.y + b.h;
  });

  var rangeX = maxX - minX || 1;
  var rangeY = maxY - minY || 1;
  var margin = 20;
  var scaleX = (W - margin * 2) / rangeX;
  var scaleY = (H - margin * 2) / rangeY;
  var sc = Math.min(scaleX, scaleY);

  // 按 track_id 分组并绘制
  var tracks = {};
  allBoxes.forEach(function (b) {
    var key = String(b.trackId);
    if (!tracks[key]) tracks[key] = [];
    tracks[key].push(b);
  });

  var trackColors = [colors.accent, colors.primary, colors.success, colors.warning];
  var trackIdx = 0;
  Object.keys(tracks).forEach(function (key) {
    var boxes = tracks[key];
    var color = trackColors[trackIdx % trackColors.length];
    trackIdx++;

    // 连线
    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.5;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    boxes.forEach(function (b, i) {
      var cx = margin + (b.x + b.w / 2 - minX) * sc;
      var cy = margin + (b.y + b.h / 2 - minY) * sc;
      if (i === 0) ctx.moveTo(cx, cy);
      else ctx.lineTo(cx, cy);
    });
    ctx.stroke();
    ctx.globalAlpha = 1;

    // 框
    boxes.forEach(function (b) {
      var rx = margin + (b.x - minX) * sc;
      var ry = margin + (b.y - minY) * sc;
      var rw = b.w * sc;
      var rh = b.h * sc;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(rx, ry, rw, rh);
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.12;
      ctx.fillRect(rx, ry, rw, rh);
      ctx.globalAlpha = 1;
    });
  });
}

// ── 脏状态追踪 ────────────────────────────────────────────────────────
function markDirty() {
  state.dirty = true;
  updateDirtyIndicator();
}

function updateDirtyIndicator() {
  var button = byId("save-review-button");
  if (!button) return;
  var original = button.dataset.originalLabel || "保存审核";
  button.dataset.originalLabel = original;
  button.textContent = state.dirty ? "● " + original : original;
  button.setAttribute(
    "aria-label",
    state.dirty ? original + "（有未保存修改）" : original
  );
}

// ── JSON 报告弹窗 ────────────────────────────────────────────────────
function exportReview() {
  var exportData = {
    job_id: state.jobId,
    exported_at: new Date().toISOString(),
    segments: state.segments.map(function (seg) {
      var review = state.reviews[seg.id] || {};
      return {
        id: seg.id,
        start: seg.start,
        end: seg.end,
        score: seg.score,
        source_keyframes: seg.source_keyframes || [],
        review: review.recommendation || null,
        review_note: review.note || null,
      };
    }),
  };
  var blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
  var url = URL.createObjectURL(blob);
  var a = document.createElement("a");
  a.href = url;
  a.download = "review_" + state.jobId + ".json";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast("审核数据已导出", "success");
}

function showReportDialog() {
  byId("report-content").textContent = JSON.stringify(
    {
      job_id: state.jobId,
      video: state.video,
      segments: state.segments,
      agent_comments: state.agentComments,
      keyframes: state.keyframes,
    },
    null,
    2
  );
  byId("report-dialog").showModal();
}

// ── 入口 ─────────────────────────────────────────────────────────────
function initEditor() {
  initTheme();
  loadUser();

  // 从 URL 提取 job_id: /jobs/<job_id>/editor
  var pathParts = window.location.pathname.split("/").filter(Boolean);
  var jobId = pathParts.length >= 2 ? pathParts[1] : null;

  if (!jobId) {
    setView("error");
    byId("editor-error-message").textContent = "URL 缺少任务编号。请从工作台进入编辑页。";
    return;
  }

  // 按钮事件（全部加 null guard，防御模板未更新场景）
  safeOn("editor-retry-button", "click", function () {
    loadEditorData(jobId);
  });
  safeOn("save-review-button", "click", saveReview);
  safeOn("rough-cut-button", "click", createRoughCut);
  safeOn("view-report-button", "click", showReportDialog);
  safeOn("close-report-button", "click", function () {
    byId("report-dialog").close();
  });
  safeOn("report-dialog", "click", function (e) {
    if (e.target === byId("report-dialog")) byId("report-dialog").close();
  });
  safeOn("export-review-button", "click", exportReview);

  // 统计按钮 → 弹窗
  document.querySelectorAll(".stat-tile").forEach(function (tile) {
    tile.addEventListener("click", showStatsDialog);
  });
  safeOn("close-stats-button", "click", function () {
    byId("stats-dialog").close();
  });

  // 三态审核按钮事件
  document.querySelectorAll(".review-option").forEach(function (btn) {
    btn.addEventListener("click", function () {
      setReviewStatus(state.selectedSegmentId, btn.dataset.reviewValue);
    });
  });

  // 审核备注输入事件
  var reviewNoteInput = byId("review-note-input");
  if (reviewNoteInput) {
    reviewNoteInput.addEventListener("input", function () {
      setReviewNote(state.selectedSegmentId, reviewNoteInput.value);
    });
  }

  // 边界编辑事件
  ["boundary-start", "boundary-end"].forEach(function (id) {
    var input = byId(id);
    if (!input) return;
    input.addEventListener("change", function () {
      applyBoundaryChange(
        state.selectedSegmentId,
        id === "boundary-start" ? "start" : "end",
        input.value
      );
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        applyBoundaryChange(
          state.selectedSegmentId,
          id === "boundary-start" ? "start" : "end",
          input.value
        );
      }
    });
  });

  // 排序按钮事件
  var sortUp = document.querySelector(".sort-up");
  var sortDown = document.querySelector(".sort-down");
  if (sortUp) sortUp.addEventListener("click", function () { reorderSegment(state.selectedSegmentId, "up"); });
  if (sortDown) sortDown.addEventListener("click", function () { reorderSegment(state.selectedSegmentId, "down"); });

  // 脏状态 - 离开页面提醒
  window.addEventListener("beforeunload", function (e) {
    if (state.dirty) {
      e.preventDefault();
      e.returnValue = "您有未保存的审核修改，确定要离开吗？";
      return e.returnValue;
    }
  });

  // 加载数据
  loadEditorData(jobId);
}

// ── 保存审核 ───────────────────────────────────────────────────────────
function saveReview() {
  if (!state.jobId || !state.segments.length) return;
  var button = byId("save-review-button");
  setButtonLoading(button, true, "保存中…");
  var body = {
    status: "pending",
    segments: state.segments.map(function (seg) {
      var rev = state.reviews[seg.id] || {};
      return {
        id: seg.id,
        start: seg.start,
        end: seg.end,
        order: seg.order,
        score: seg.score,
        source_keyframes: seg.source_keyframes || [],
        review: rev.recommendation || "",
        review_note: rev.note || "",
      };
    }),
  };
  api.patch("/api/jobs/" + encodeURIComponent(state.jobId) + "/review", body).then(
    function (payload) {
      state.dirty = false;
      updateDirtyIndicator();
      showToast("审核结果已保存", "success");
      if (payload.report) {
        state.segments = Array.isArray(payload.report.segments)
          ? payload.report.segments.map(function (s) { return Object.assign({}, s); })
          : state.segments;
        renderTimeline();
        renderSegmentList();
        renderStatsDashboard();
        if (state.selectedSegmentId) selectSegment(state.selectedSegmentId);
      }
      setButtonLoading(button, false);
    },
    function (error) {
      showToast(error.message, "error");
      setButtonLoading(button, false);
    }
  );
}

// ── 生成粗剪 ───────────────────────────────────────────────────────────
function createRoughCut() {
  if (!state.jobId) return;
  var button = byId("rough-cut-button");
  setButtonLoading(button, true, "生成中…");
  // 先保存审核再生成粗剪
  api.patch("/api/jobs/" + encodeURIComponent(state.jobId) + "/review", {
    status: "approved",
    segments: state.segments.map(function (seg) {
      return {
        id: seg.id,
        start: seg.start,
        end: seg.end,
        order: seg.order,
        score: seg.score,
        source_keyframes: seg.source_keyframes || [],
      };
    }),
  }).then(
    function () {
      return api.post("/api/jobs/" + encodeURIComponent(state.jobId) + "/rough-cut", {});
    },
    function (error) {
      // 即使保存审核失败也尝试生成粗剪
      showToast("审核保存失败：" + error.message + "，继续尝试生成粗剪…", "info");
      return api.post("/api/jobs/" + encodeURIComponent(state.jobId) + "/rough-cut", {});
    }
  ).then(
    function () {
      showToast("粗剪视频已生成", "success");
      setButtonLoading(button, false);
      // 重新加载数据以获取最新的输出文件
      loadEditorData(state.jobId);
    },
    function (error) {
      showToast(error.message, "error");
      setButtonLoading(button, false);
    }
  );
}

// ── 按钮加载态 ─────────────────────────────────────────────────────────
function setButtonLoading(button, loading, label) {
  if (!button) return;
  var originalLabel = button.dataset.originalLabel;
  if (!originalLabel) {
    button.dataset.originalLabel = button.textContent.trim();
  }
  button.disabled = loading;
  button.classList.toggle("is-loading", loading);
  button.textContent = loading ? label : button.dataset.originalLabel;
}

document.addEventListener("DOMContentLoaded", initEditor);
