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
  if (payload.contract_version !== "1.0") {
    throw new Error("剪辑预览数据契约版本不受支持。");
  }
  if (!payload.job || !payload.video || !Array.isArray(payload.highlights)) {
    throw new Error("剪辑预览数据缺少必要字段。");
  }

  return {
    job_id: payload.job.job_id,
    status: payload.job.status,
    video: {
      duration: Number(payload.video.duration),
      filename: payload.video.filename || "",
      path: payload.video.url || null,
    },
    segments: payload.highlights.map(function (highlight) {
      return {
        id: highlight.id,
        order: highlight.order,
        start: Number(highlight.start),
        end: Number(highlight.end),
        score: highlight.score,
        source_keyframes: highlight.source_keyframes || [],
      };
    }),
    agent_comments: payload.highlights.map(function (highlight) {
      var status =
        highlight.agent_comment_status === "ready"
          ? "completed"
          : highlight.agent_comment_status;
      return {
        segment_id: highlight.id,
        status: status || "pending",
        summary: highlight.agent_comment || "",
        tags: [],
        suggestions: [],
        review: {
          recommendation: "needs_review",
          confidence: 0,
          reasons: [],
        },
        evidence_refs: (highlight.agent_evidence_refs || []).map(function (ref) {
          return {
            ref_id: String(ref),
            type: "evidence",
            source_id: String(ref),
          };
        }),
        knowledge_refs: [],
      };
    }),
    keyframes: [],
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

  // 默认选中第一个片段
  if (state.segments.length > 0) {
    selectSegment(state.segments[0].id);
  }
}

// ── JSON 报告弹窗 ────────────────────────────────────────────────────
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

  // 按钮事件
  byId("editor-retry-button").addEventListener("click", function () {
    loadEditorData(jobId);
  });
  byId("save-review-button").addEventListener("click", function () {
    saveReview();
  });
  byId("rough-cut-button").addEventListener("click", function () {
    createRoughCut();
  });
  byId("view-report-button").addEventListener("click", showReportDialog);
  byId("close-report-button").addEventListener("click", function () {
    byId("report-dialog").close();
  });
  byId("report-dialog").addEventListener("click", function (e) {
    if (e.target === byId("report-dialog")) byId("report-dialog").close();
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
  };
  api.patch("/api/jobs/" + encodeURIComponent(state.jobId) + "/review", body).then(
    function (payload) {
      showToast("审核结果已保存", "success");
      if (payload.report) {
        state.segments = Array.isArray(payload.report.segments)
          ? payload.report.segments.map(function (s) { return Object.assign({}, s); })
          : state.segments;
        renderSegmentList();
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
