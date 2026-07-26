"use strict";

/* ===================================================================
   ReelFire Editor — 剪辑预览工作台 (Day 3)
   三态审核 · 边界编辑 · 片段排序 · 统计图 · 轨迹 · 导出
   所有动态文本使用 textContent；不通过评分伪造 Agent 评论。
   =================================================================== */

// ── Mock 数据（符合 editor 聚合接口 + Agent 输出 Schema）──────────────
const EDITOR_MOCK = {
  job_id: "mock_20260725_143000_a1b2c3d4",
  status: "completed",
  video: {
    duration: 95.5,
    width: 1920,
    height: 1080,
    fps: 60.0,
    has_audio: true,
    path: null,
  },
  segments: [
    {
      id: "seg_001",
      start: 18.5,
      end: 48.5,
      order: 1,
      score: 0.82,
      source_keyframes: ["kf_003", "kf_004"],
      label: "多人混战",
    },
    {
      id: "seg_002",
      start: 52.0,
      end: 82.0,
      order: 2,
      score: 0.74,
      source_keyframes: ["kf_007", "kf_008"],
      label: "残局反杀",
    },
    {
      id: "seg_003",
      start: 8.0,
      end: 38.0,
      order: 3,
      score: 0.61,
      source_keyframes: ["kf_001", "kf_002"],
      label: "开局交火",
    },
  ],
  agent_comments: [
    {
      segment_id: "seg_001",
      status: "completed",
      summary:
        "该片段包含多次击杀事件，画面中出现多个人物目标，运动强度较高。从关键帧 kf_003 可见至少 3 名交战角色，场景变化剧烈。建议保留为开场高潮或集锦核心片段。",
      tags: [
        { name: "多人交战", description: "同时出现 3+ 角色目标", evidence_refs: ["ref_det_003"] },
        { name: "高运动强度", description: "连续帧运动强度 > 0.6", evidence_refs: ["ref_score_001"] },
      ],
      suggestions: [
        {
          suggestion_id: "sug_001",
          title: "保留为核心片段",
          action: "保留并标记为开场高潮，建议置于粗剪最前。",
          priority: "high",
          evidence_refs: ["ref_det_003", "ref_score_001"],
          knowledge_refs: ["KB-FPS-001"],
        },
        {
          suggestion_id: "sug_002",
          title: "检查边界准确性",
          action: "片段起始 18.5s 处画面变化大，建议微调至 18.0s 以包含完整的击杀前画面。",
          priority: "medium",
          evidence_refs: ["ref_scene_002"],
          knowledge_refs: ["KB-FPS-002"],
        },
      ],
      review: {
        recommendation: "pass",
        confidence: 0.78,
        reasons: [
          "目标密度和运动强度双高，置信度较可靠",
          "关键帧检测到多个交战角色类别",
        ],
      },
      evidence_refs: [
        { ref_id: "ref_det_003", type: "detection", source_id: "kf_003", class_name: "person", confidence: 0.72 },
        { ref_id: "ref_score_001", type: "score", source_id: "seg_001", value: { highlight_score: 0.82 } },
        { ref_id: "ref_scene_002", type: "keyframe", source_id: "kf_004", timestamp: 24.0 },
      ],
      knowledge_refs: [
        { knowledge_id: "KB-FPS-001", category: "精彩判定", title: "多人交战事件定义" },
        { knowledge_id: "KB-FPS-002", category: "剪辑规范", title: "片段边界最佳实践" },
      ],
    },
    {
      segment_id: "seg_002",
      status: "pending",
      summary: "",
      tags: [],
      suggestions: [],
      review: { recommendation: "needs_review", confidence: 0, reasons: [] },
      evidence_refs: [],
      knowledge_refs: [],
    },
    {
      segment_id: "seg_003",
      status: "unavailable",
      summary: "",
      tags: [],
      suggestions: [],
      review: { recommendation: "needs_review", confidence: 0, reasons: [] },
      evidence_refs: [],
      knowledge_refs: [],
      error: "Agent 服务连接超时，暂时不可用。",
    },
  ],
  keyframes: [
    { id: "kf_001", timestamp: 14.0, image: null, highlight_score: 0.55 },
    { id: "kf_002", timestamp: 22.5, image: null, highlight_score: 0.61 },
    { id: "kf_003", timestamp: 26.0, image: null, highlight_score: 0.82 },
    { id: "kf_004", timestamp: 42.5, image: null, highlight_score: 0.78 },
    { id: "kf_007", timestamp: 58.5, image: null, highlight_score: 0.74 },
    { id: "kf_008", timestamp: 72.0, image: null, highlight_score: 0.68 },
  ],
};

// ── 状态 ─────────────────────────────────────────────────────────────
const state = {
  jobId: null,
  editorData: null,
  segments: [],
  agentComments: [],
  keyframes: [],
  video: null,
  selectedSegmentId: null,
  useMock: false,
  videoElement: null,
  // Day 3 新增状态
  reviews: {},       // { segmentId: { recommendation: "pass"|"needs_review"|"reject", note: "" } }
  dirty: false,      // 是否有未保存的修改
};

// ── 工具函数 ─────────────────────────────────────────────────────────
function byId(id) { return document.getElementById(id); }

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
  return String(m).padStart(2, "0") + ":" + String(sec).padStart(2, "0");
}

function formatDuration(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s)) return "—";
  if (s < 60) return s.toFixed(1) + " 秒";
  const m = Math.floor(s / 60);
  return m + " 分 " + (s % 60).toFixed(0) + " 秒";
}

function formatNumber(value, digits) {
  if (digits === undefined) digits = 1;
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

function showToast(message, type) {
  const container = byId("toast-container");
  if (!container) return;
  const toast = createElement("div", "toast " + (type || "info"), message);
  container.append(toast);
  window.setTimeout(function () { toast.remove(); }, 4200);
}

// ── API 封装 ─────────────────────────────────────────────────────────
const api = {
  request: function (url, options) {
    options = options || {};
    return fetch(url, options).then(function (response) {
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
  get: function (url) { return this.request(url); },
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
      byId("user-name").textContent = payload.user.username;
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

// ── Dirty 标记 ───────────────────────────────────────────────────────
function markDirty() {
  state.dirty = true;
  updateSaveButton();
}

function markClean() {
  state.dirty = false;
  updateSaveButton();
}

function updateSaveButton() {
  var btn = byId("save-review-button");
  if (!btn) return;
  btn.textContent = state.dirty ? "保存审核 ●" : "保存审核";
  btn.classList.toggle("has-changes", state.dirty);
}

// ── 视频播放器 ───────────────────────────────────────────────────────
function renderVideo() {
  var videoEl = byId("editor-video");
  var placeholder = byId("video-placeholder");
  var video = state.video;

  if (video && video.path) {
    videoEl.src = video.path;
    videoEl.hidden = false;
    placeholder.hidden = true;
    state.videoElement = videoEl;
  } else {
    videoEl.hidden = true;
    placeholder.hidden = false;
  }

  if (video) {
    byId("timeline-duration").textContent = formatTime(video.duration);
  }

  // 更新边界编辑器的 max 值
  var startInput = byId("edit-seg-start");
  var endInput = byId("edit-seg-end");
  if (video && video.duration) {
    if (startInput) startInput.max = String(video.duration);
    if (endInput) endInput.max = String(video.duration);
  }
}

// ── 时间轴 ───────────────────────────────────────────────────────────
function renderTimeline() {
  if (!state.video) return;
  var duration = state.video.duration;

  var segmentsBar = byId("timeline-segments-bar");
  clearChildren(segmentsBar);
  state.segments.forEach(function (seg, idx) {
    var left = (seg.start / duration) * 100;
    var width = Math.max(((seg.end - seg.start) / duration) * 100, 0.5);
    var marker = createElement("div", "timeline-segment-marker seg-" + (idx % 4));
    marker.style.left = left + "%";
    marker.style.width = width + "%";
    marker.title =
      "片段 " + seg.id + ": " + formatTime(seg.start) + " – " + formatTime(seg.end) +
      " (评分 " + formatNumber(Number(seg.score) * 100, 0) + ")";
    marker.setAttribute("role", "button");
    marker.setAttribute("aria-label", marker.title);
    marker.setAttribute("tabindex", "0");
    marker.dataset.segmentId = seg.id;

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
  if (playhead) playhead.style.left = pct + "%";

  var track = byId("timeline-track");
  if (track) track.setAttribute("aria-valuenow", String(Math.round(currentTime)));

  var currentLabel = byId("timeline-current");
  if (currentLabel) currentLabel.textContent = formatTime(currentTime);

  highlightSegmentAtTime(currentTime);
}

function seekTo(time) {
  if (state.videoElement && state.videoElement.src && !state.useMock) {
    state.videoElement.currentTime = time;
  }
  updatePlayhead(time);
}

function highlightSegmentAtTime(time) {
  var found = null;
  state.segments.forEach(function (seg) {
    if (time >= seg.start && time <= seg.end) found = seg.id;
  });

  var markers = document.querySelectorAll(".timeline-segment-marker");
  markers.forEach(function (m) { m.classList.remove("active"); });

  if (found && found !== state.selectedSegmentId) {
    var idx = state.segments.findIndex(function (s) { return s.id === found; });
    if (idx >= 0 && markers[idx]) markers[idx].classList.add("active");
  }
}

function bindTimelineEvents() {
  var track = byId("timeline-track");
  var playButton = byId("timeline-play");
  var isDragging = false;

  playButton.addEventListener("click", function () {
    if (state.videoElement && state.videoElement.src && !state.useMock) {
      if (state.videoElement.paused) {
        state.videoElement.play();
        playButton.setAttribute("aria-label", "暂停");
      } else {
        state.videoElement.pause();
        playButton.setAttribute("aria-label", "播放");
      }
    }
  });

  track.addEventListener("click", function (e) {
    if (!state.video) return;
    var rect = track.getBoundingClientRect();
    var pct = (e.clientX - rect.left) / rect.width;
    seekTo(pct * state.video.duration);
  });

  track.addEventListener("mousedown", function () {
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

  track.addEventListener("keydown", function (e) {
    if (!state.video) return;
    var step = state.video.duration / 100;
    var currentTime = (state.videoElement && state.videoElement.src) ? state.videoElement.currentTime : 0;
    if (e.key === "ArrowRight") {
      e.preventDefault();
      seekTo(Math.min(currentTime + step, state.video.duration));
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      seekTo(Math.max(currentTime - step, 0));
    }
  });

  if (state.videoElement) {
    state.videoElement.addEventListener("timeupdate", function () {
      if (!isDragging) updatePlayhead(state.videoElement.currentTime);
    });
  }
}

// ── 片段列表 + 排序按钮 ──────────────────────────────────────────────
function selectSegment(segmentId) {
  state.selectedSegmentId = segmentId;

  // 卡片高亮
  var cards = document.querySelectorAll(".segment-card");
  cards.forEach(function (card) {
    var selected = card.dataset.segmentId === segmentId;
    card.classList.toggle("selected", selected);
    card.setAttribute("aria-current", selected ? "true" : "false");
  });

  // 时间轴标记高亮
  var markers = document.querySelectorAll(".timeline-segment-marker");
  var idx = state.segments.findIndex(function (s) { return s.id === segmentId; });
  markers.forEach(function (m, i) { m.classList.toggle("active", i === idx); });

  renderSegmentDetail(segmentId);
}

function moveSegmentUp(segmentId) {
  var idx = state.segments.findIndex(function (s) { return s.id === segmentId; });
  if (idx <= 0) return;
  // 交换 order
  var a = state.segments[idx - 1];
  var b = state.segments[idx];
  var tmp = a.order;
  a.order = b.order;
  b.order = tmp;
  // 排序
  state.segments.sort(function (x, y) { return x.order - y.order; });
  markDirty();
  renderSegmentList();
  renderTimeline();
  selectSegment(segmentId);
  showToast("顺序已调整", "info");
}

function moveSegmentDown(segmentId) {
  var idx = state.segments.findIndex(function (s) { return s.id === segmentId; });
  if (idx < 0 || idx >= state.segments.length - 1) return;
  var a = state.segments[idx];
  var b = state.segments[idx + 1];
  var tmp = a.order;
  a.order = b.order;
  b.order = tmp;
  state.segments.sort(function (x, y) { return x.order - y.order; });
  markDirty();
  renderSegmentList();
  renderTimeline();
  selectSegment(segmentId);
  showToast("顺序已调整", "info");
}

function renderSegmentList() {
  var container = byId("segment-list");
  clearChildren(container);
  byId("segments-count").textContent = state.segments.length + " 个片段";

  if (!state.segments.length) return;

  state.segments.forEach(function (seg, idx) {
    var comment = findAgentComment(seg.id);
    var agentStatus = comment ? comment.status : "pending";
    var review = state.reviews[seg.id] || {};
    var reviewRec = review.recommendation || "";

    var card = createElement("article", "segment-card");
    card.dataset.segmentId = seg.id;
    card.setAttribute("role", "listitem");
    card.setAttribute("tabindex", "0");
    card.setAttribute("aria-label",
      "片段 " + (idx + 1) + "，" + formatTime(seg.start) + " 到 " + formatTime(seg.end));

    // 审核状态左边框
    if (reviewRec) {
      card.classList.add("review-" + reviewRec);
    }

    // 排序按钮
    var orderBtns = createElement("div", "segment-order-btns");
    var upBtn = createElement("button", "seg-order-btn up");
    upBtn.title = "上移";
    upBtn.setAttribute("aria-label", "片段 " + seg.id + " 上移");
    upBtn.innerHTML = '<svg viewBox="0 0 16 16"><path d="M8 3 L3 9h10z"/></svg>';
    upBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      moveSegmentUp(seg.id);
    });
    if (idx === 0) upBtn.disabled = true;

    var downBtn = createElement("button", "seg-order-btn down");
    downBtn.title = "下移";
    downBtn.setAttribute("aria-label", "片段 " + seg.id + " 下移");
    downBtn.innerHTML = '<svg viewBox="0 0 16 16"><path d="M8 13 L3 7h10z"/></svg>';
    downBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      moveSegmentDown(seg.id);
    });
    if (idx === state.segments.length - 1) downBtn.disabled = true;

    orderBtns.append(upBtn, downBtn);

    // 顶部
    var top = createElement("div", "segment-card-top");
    top.append(
      createElement("span", "segment-card-order", String(idx + 1).padStart(2, "0"))
    );
    var timeDiv = createElement("div", "segment-card-time");
    timeDiv.append(
      createElement("strong", "", formatTime(seg.start) + " – " + formatTime(seg.end)),
      createElement("small", "", formatNumber(seg.end - seg.start, 1) + " 秒")
    );
    top.append(timeDiv);
    top.append(
      createElement("span", "segment-card-score", formatNumber(Number(seg.score) * 100, 0))
    );
    top.append(orderBtns);

    // 底部
    var bottom = createElement("div", "segment-card-bottom");
    bottom.append(
      createElement("span", "segment-card-keyframes",
        "关键帧 " + (seg.source_keyframes || []).join("、"))
    );

    // 人工审核标记
    if (reviewRec) {
      var reviewBadge = document.createElement("span");
      reviewBadge.className = "segment-review-badge " + reviewRec;
      reviewBadge.textContent = reviewRec === "pass" ? "✓ 通过" :
        reviewRec === "reject" ? "✗ 不通过" : "◎ 待复核";
      bottom.append(reviewBadge);
    }

    var agentBadge = createElement("span", "segment-card-agent " + agentStatus);
    var dot = createElement("span", "agent-status-dot");
    var labelText = agentStatus === "completed" ? "Agent 已完成" :
      agentStatus === "pending" ? "待分析" : "不可用";
    agentBadge.append(dot, document.createTextNode(labelText));
    bottom.append(agentBadge);

    card.append(top, bottom);

    card.addEventListener("click", function () { selectSegment(seg.id); });
    card.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        selectSegment(seg.id);
      }
    });

    container.append(card);
  });
}

function findAgentComment(segmentId) {
  return (state.agentComments.find(function (c) { return c.segment_id === segmentId; }) || null);
}

// ── 片段详情（含三态审核 + 边界编辑）─────────────────────────────────
function renderSegmentDetail(segmentId) {
  if (!segmentId) return;

  var seg = state.segments.find(function (s) { return s.id === segmentId; });
  if (!seg) return;

  var comment = findAgentComment(segmentId);
  var review = state.reviews[segmentId] || {};

  byId("detail-placeholder").hidden = true;
  byId("detail-content").hidden = false;
  byId("detail-title").textContent = "片段 " + seg.id;
  byId("detail-score").textContent = formatNumber(Number(seg.score) * 100, 0) + " 分";

  // 时间范围 — 显示当前值
  byId("detail-time").textContent = formatTime(seg.start) + " – " + formatTime(seg.end);
  byId("detail-duration").textContent = formatNumber(seg.end - seg.start, 1) + " 秒";
  byId("detail-keyframes").textContent = (seg.source_keyframes || []).join("、");

  // 填充边界编辑输入框
  byId("edit-seg-start").value = formatNumber(seg.start, 1);
  byId("edit-seg-end").value = formatNumber(seg.end, 1);
  if (state.video && state.video.duration) {
    byId("edit-seg-start").max = String(state.video.duration);
    byId("edit-seg-end").max = String(state.video.duration);
  }

  // ── 三态审核控件 ────────────────────────────────────────────────
  renderReviewControls(seg, review);

  // ── Agent 评论 ──────────────────────────────────────────────────
  var agentStatus = comment ? comment.status : "pending";
  renderAgentComment(agentStatus, comment);
}

// ── 三态审核控件 ─────────────────────────────────────────────────────
function renderReviewControls(seg, review) {
  var currentRec = review.recommendation || "";
  var currentNote = review.note || "";

  // 三态按钮
  var buttons = [
    { value: "pass", label: "通过", icon: "✓" },
    { value: "needs_review", label: "待复核", icon: "◎" },
    { value: "reject", label: "不通过", icon: "✗" },
  ];

  var btnGroup = byId("review-btn-group");
  clearChildren(btnGroup);
  buttons.forEach(function (btn) {
    var el = createElement("button", "review-btn review-" + btn.value);
    el.setAttribute("type", "button");
    if (currentRec === btn.value) el.classList.add("active");
    el.setAttribute("aria-pressed", String(currentRec === btn.value));
    el.innerHTML = '<span class="review-icon">' + btn.icon + '</span>' + btn.label;
    el.addEventListener("click", function () {
      if (!state.reviews[seg.id]) state.reviews[seg.id] = {};
      state.reviews[seg.id].recommendation = btn.value;
      markDirty();
      // 刷新卡片和详情
      renderSegmentList();
      renderSegmentDetail(seg.id);
      renderStatsDashboard();
    });
    btnGroup.append(el);
  });

  // 备注
  byId("review-note").value = currentNote;
  byId("review-note").oninput = function () {
    if (!state.reviews[seg.id]) state.reviews[seg.id] = {};
    state.reviews[seg.id].note = byId("review-note").value;
    markDirty();
  };

  // AI 建议提示
  var comment = findAgentComment(seg.id);
  var aiSuggestion = byId("review-ai-suggestion");
  if (comment && comment.review && comment.review.recommendation) {
    var aiRec = comment.review.recommendation;
    var aiLabel = aiRec === "pass" ? "通过" : aiRec === "reject" ? "不通过" : "待复核";
    aiSuggestion.textContent = "AI 建议：" + aiLabel + "（置信度 " +
      formatNumber(Number(comment.review.confidence) * 100, 0) + "%）";
    aiSuggestion.hidden = false;
  } else {
    aiSuggestion.hidden = true;
  }
}

// ── 边界编辑 ─────────────────────────────────────────────────────────
function applyBoundaryEdit(segmentId) {
  var seg = state.segments.find(function (s) { return s.id === segmentId; });
  if (!seg) return;

  var startVal = parseFloat(byId("edit-seg-start").value);
  var endVal = parseFloat(byId("edit-seg-end").value);
  var duration = state.video ? state.video.duration : Infinity;

  // 验证
  if (!Number.isFinite(startVal) || !Number.isFinite(endVal)) {
    showToast("起止时间必须是有效数字", "error");
    return;
  }
  if (startVal >= endVal) {
    showToast("起始时间必须小于结束时间", "error");
    return;
  }
  if (startVal < 0 || endVal > duration) {
    showToast("时间范围必须在 0 – " + formatDuration(duration) + " 内", "error");
    return;
  }

  seg.start = startVal;
  seg.end = endVal;
  markDirty();
  renderSegmentList();
  renderTimeline();
  renderSegmentDetail(segmentId);
  renderStatsDashboard();
  showToast("边界已更新 · " + formatTime(startVal) + " – " + formatTime(endVal), "success");
}

// ── Agent 评论渲染 ────────────────────────────────────────────────────
function renderAgentComment(status, comment) {
  var badge = byId("agent-status-badge");
  badge.className = "agent-status-badge " + status;
  var badgeText = status === "completed" ? "Agent 已完成" :
    status === "pending" ? "待 Agent 分析" : "Agent 不可用";
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
    var msg = (comment && comment.error) ? comment.error :
      "Agent 服务当前不可用，以下为基于 CV 检测的规则输出。";
    byId("agent-unavailable-message").textContent = msg;
    byId("agent-unavailable-content").hidden = false;
  }
}

function renderAgentCompleted(comment) {
  byId("agent-summary").textContent = comment.summary || "Agent 未生成摘要。";

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

  var suggestionsContainer = byId("agent-suggestions");
  clearChildren(suggestionsContainer);
  (comment.suggestions || []).forEach(function (sug) {
    var item = createElement("div", "agent-suggestion-item");
    var titleSpan = createElement("strong");
    titleSpan.textContent = sug.title;
    var prioritySpan = createElement(
      "span", "agent-suggestion-priority " + (sug.priority || "low"),
      sug.priority === "high" ? "高" : sug.priority === "medium" ? "中" : "低"
    );
    titleSpan.append(prioritySpan);
    var actionP = createElement("p", "", sug.action || "");
    item.append(titleSpan, actionP);
    suggestionsContainer.append(item);
  });
  if (!comment.suggestions || !comment.suggestions.length) {
    suggestionsContainer.append(createElement("p", "agent-field-value", "无建议。"));
  }

  // 审核意见
  var reviewContainer = byId("agent-review");
  clearChildren(reviewContainer);
  if (comment.review) {
    var rec = comment.review.recommendation || "needs_review";
    var recLabel = rec === "pass" ? "通过" : rec === "reject" ? "不通过" : "待复核";
    var recSpan = createElement("span", "agent-review-rec " + rec, recLabel);
    var confSpan = createElement("span", "agent-review-confidence",
      "置信度 " + formatNumber(Number(comment.review.confidence) * 100, 0) + "%");
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
    if (ref.confidence) {
      item.append(createElement("span", "agent-evidence-confidence",
        formatNumber(Number(ref.confidence) * 100, 0) + "%"));
    }
    evidenceContainer.append(item);
  });
  if (!comment.evidence_refs || !comment.evidence_refs.length) {
    evidenceContainer.append(createElement("p", "agent-field-value", "无证据引用。"));
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
    knowledgeContainer.append(createElement("p", "agent-field-value", "无知识库引用。"));
  }
}

// ── 统计仪表盘 ───────────────────────────────────────────────────────
function renderStatsDashboard() {
  var segs = state.segments;
  if (!segs.length) return;

  // 审核汇总
  var reviewCounts = { pass: 0, needs_review: 0, reject: 0, unset: 0 };
  segs.forEach(function (seg) {
    var r = state.reviews[seg.id];
    if (r && r.recommendation) reviewCounts[r.recommendation] = (reviewCounts[r.recommendation] || 0) + 1;
    else reviewCounts.unset = (reviewCounts.unset || 0) + 1;
  });
  byId("stat-review-pass").textContent = String(reviewCounts.pass || 0);
  byId("stat-review-pending").textContent = String(reviewCounts.needs_review || 0);
  byId("stat-review-reject").textContent = String(reviewCounts.reject || 0);
  byId("stat-review-unset").textContent = String(reviewCounts.unset || 0);

  // 片段分值分布
  byId("stat-segment-count").textContent = String(segs.length);
  var avgScore = segs.reduce(function (s, seg) { return s + Number(seg.score); }, 0) / segs.length;
  byId("stat-avg-score").textContent = formatNumber(avgScore * 100, 0);
  var maxScore = Math.max.apply(null, segs.map(function (s) { return Number(s.score); }));
  byId("stat-max-score").textContent = formatNumber(maxScore * 100, 0);

  // Agent 状态汇总
  var agentCounts = { completed: 0, pending: 0, unavailable: 0 };
  segs.forEach(function (seg) {
    var c = findAgentComment(seg.id);
    var s = c ? c.status : "pending";
    agentCounts[s] = (agentCounts[s] || 0) + 1;
  });
  byId("stat-agent-ok").textContent = String(agentCounts.completed || 0);
  byId("stat-agent-wait").textContent = String(agentCounts.pending || 0);
  byId("stat-agent-fail").textContent = String(agentCounts.unavailable || 0);

  // 总时长
  var totalDur = segs.reduce(function (s, seg) { return s + (seg.end - seg.start); }, 0);
  byId("stat-total-duration").textContent = formatDuration(totalDur);

  // ── 绘制图表 ────────────────────────────────────────────────────
  drawScoreChart(segs);
  drawDurationChart(segs);
  drawReviewPie(reviewCounts);
}

function drawScoreChart(segments) {
  var canvas = byId("stat-score-chart");
  if (!canvas) return;
  var ctx = canvas.getContext("2d");
  var dpr = window.devicePixelRatio || 1;
  var rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = 180 * dpr;
  canvas.style.width = rect.width + "px";
  canvas.style.height = "180px";
  ctx.scale(dpr, dpr);
  var w = rect.width;
  var h = 180;

  ctx.clearRect(0, 0, w, h);

  // 网格
  ctx.strokeStyle = "rgba(158, 154, 176, 0.15)";
  ctx.lineWidth = 1;
  for (var i = 0; i <= 4; i++) {
    var y = 20 + (h - 40) * (i / 4);
    ctx.beginPath();
    ctx.moveTo(40, y);
    ctx.lineTo(w - 20, y);
    ctx.stroke();
  }

  // 柱状图
  var barAreaW = w - 80;
  var barW = Math.min(48, barAreaW / segments.length - 8);
  var barGap = barAreaW / segments.length;
  var maxVal = 1;

  segments.forEach(function (seg, i) {
    var x = 50 + barGap * i + barGap / 2 - barW / 2;
    var barH = (Number(seg.score) / maxVal) * (h - 60);
    var y = h - 30 - barH;

    // 渐变
    var grad = ctx.createLinearGradient(x, y, x, h - 30);
    grad.addColorStop(0, "rgba(255, 70, 85, 0.85)");
    grad.addColorStop(1, "rgba(189, 126, 230, 0.45)");
    ctx.fillStyle = grad;
    ctx.beginPath();
    roundRect(ctx, x, y, barW, barH, 4);
    ctx.fill();

    // 分值标签
    ctx.fillStyle = "#ece8e1";
    ctx.font = "10px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(String(Math.round(Number(seg.score) * 100)), x + barW / 2, y - 6);

    // X 轴标签
    ctx.fillStyle = "#9e9ab0";
    ctx.fillText(seg.id || ("#" + (i + 1)), x + barW / 2, h - 10);
  });

  // Y 轴
  ctx.fillStyle = "#6b6880";
  ctx.font = "9px Inter, sans-serif";
  ctx.textAlign = "right";
  for (i = 0; i <= 4; i++) {
    var val = Math.round((1 - i / 4) * 100);
    ctx.fillText(String(val), 36, 20 + (h - 40) * (i / 4) + 4);
  }
}

function drawDurationChart(segments) {
  var canvas = byId("stat-duration-chart");
  if (!canvas) return;
  var ctx = canvas.getContext("2d");
  var dpr = window.devicePixelRatio || 1;
  var rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = 120 * dpr;
  canvas.style.width = rect.width + "px";
  canvas.style.height = "120px";
  ctx.scale(dpr, dpr);
  var w = rect.width;
  var h = 120;

  ctx.clearRect(0, 0, w, h);

  var maxDur = Math.max.apply(null, segments.map(function (s) { return s.end - s.start; }));
  var barAreaW = w - 80;
  var barH = 28;
  var gap = 8;

  segments.forEach(function (seg, i) {
    var dur = seg.end - seg.start;
    var barW = maxDur > 0 ? (dur / maxDur) * barAreaW : 10;
    var y = 15 + i * (barH + gap);

    // 背景条
    ctx.fillStyle = "rgba(26, 24, 48, 0.6)";
    ctx.fillRect(75, y, barAreaW, barH);

    // 实际条
    var grad = ctx.createLinearGradient(75, 0, 75 + barAreaW, 0);
    grad.addColorStop(0, "rgba(10, 206, 254, 0.75)");
    grad.addColorStop(1, "rgba(32, 176, 110, 0.55)");
    ctx.fillStyle = grad;
    ctx.beginPath();
    roundRect(ctx, 75, y, Math.max(barW, 4), barH, 3);
    ctx.fill();

    // 标签
    ctx.fillStyle = "#ece8e1";
    ctx.font = "11px Inter, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(seg.id || ("#" + (i + 1)), 6, y + barH / 2 + 4);

    // 时长
    ctx.fillStyle = "#9e9ab0";
    ctx.textAlign = "right";
    ctx.fillText(formatNumber(dur, 1) + "s", 75 + Math.max(barW, 4) + 6, y + barH / 2 + 4);
  });
}

function drawReviewPie(counts) {
  var canvas = byId("stat-review-pie");
  if (!canvas) return;
  var ctx = canvas.getContext("2d");
  var dpr = window.devicePixelRatio || 1;
  var size = 150;
  canvas.width = size * dpr;
  canvas.height = size * dpr;
  canvas.style.width = size + "px";
  canvas.style.height = size + "px";
  ctx.scale(dpr, dpr);

  ctx.clearRect(0, 0, size, size);
  var cx = size / 2;
  var cy = size / 2;
  var r = 55;
  var total = (counts.pass || 0) + (counts.needs_review || 0) + (counts.reject || 0) + (counts.unset || 0);
  if (total === 0) {
    ctx.fillStyle = "#6b6880";
    ctx.font = "12px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("无数据", cx, cy);
    return;
  }

  var slices = [
    { value: counts.pass || 0, color: "#20b06e", label: "通过" },
    { value: counts.needs_review || 0, color: "#f0a030", label: "待复核" },
    { value: counts.reject || 0, color: "#ff4655", label: "不通过" },
    { value: counts.unset || 0, color: "#4a4860", label: "未审核" },
  ];

  var angle = -Math.PI / 2;
  slices.forEach(function (slice) {
    if (slice.value === 0) return;
    var sliceAngle = (slice.value / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, angle, angle + sliceAngle);
    ctx.closePath();
    ctx.fillStyle = slice.color;
    ctx.fill();
    angle += sliceAngle;
  });

  // 中心孔
  ctx.beginPath();
  ctx.arc(cx, cy, 25, 0, Math.PI * 2);
  ctx.fillStyle = "#1a1830";
  ctx.fill();

  ctx.fillStyle = "#ece8e1";
  ctx.font = "bold 14px Inter, sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(String(total), cx, cy + 5);
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
}

// ── 轨迹可视化 ────────────────────────────────────────────────────────
function renderTrajectory() {
  var canvas = byId("trajectory-canvas");
  if (!canvas) return;
  var ctx = canvas.getContext("2d");
  var dpr = window.devicePixelRatio || 1;
  var rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = 260 * dpr;
  canvas.style.width = rect.width + "px";
  canvas.style.height = "260px";
  ctx.scale(dpr, dpr);
  var w = rect.width;
  var h = 260;

  ctx.clearRect(0, 0, w, h);

  // 背景
  ctx.fillStyle = "rgba(15, 14, 26, 0.5)";
  ctx.fillRect(0, 0, w, h);

  // 检查是否有轨迹数据
  var hasTrajectory = false;
  state.keyframes.forEach(function (kf) {
    if (kf.trajectory && kf.trajectory.length) hasTrajectory = true;
  });

  if (!hasTrajectory || !state.video) {
    // 空状态
    ctx.fillStyle = "#6b6880";
    ctx.font = "13px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("目标跟踪数据不可用（模型尚未接入或未检测到移动目标）", w / 2, h / 2);
    byId("trajectory-status").textContent = "无跟踪数据";
    byId("trajectory-status").className = "traj-status unavailable";
    return;
  }

  // 绘制轨迹
  var duration = state.video.duration;
  var colors = ["#ff4655", "#0acefe", "#20b06e", "#bd7ee6", "#f0a030"];

  // 时间轴
  ctx.strokeStyle = "#2a2840";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(40, h - 30);
  ctx.lineTo(w - 20, h - 30);
  ctx.stroke();

  // 刻度
  for (var i = 0; i <= 10; i++) {
    var tx = 40 + (w - 60) * (i / 10);
    ctx.fillStyle = "#6b6880";
    ctx.font = "9px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(formatTime(duration * i / 10), tx, h - 12);
  }

  // 片段区域高亮
  state.segments.forEach(function (seg, idx) {
    var sx = 40 + (w - 60) * (seg.start / duration);
    var ex = 40 + (w - 60) * (seg.end / duration);
    ctx.fillStyle = "rgba(255, 70, 85, 0.06)";
    ctx.fillRect(sx, 10, ex - sx, h - 50);
    ctx.fillStyle = "rgba(255, 70, 85, 0.5)";
    ctx.font = "9px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(seg.id, (sx + ex) / 2, 22);
  });

  // 绘制实际轨迹线（从 Mock 数据生成）
  var trackCount = Math.min(3, state.keyframes.length);
  for (var t = 0; t < trackCount; t++) {
    ctx.strokeStyle = colors[t % colors.length];
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 2]);
    ctx.beginPath();
    for (var k = 0; k < state.keyframes.length; k++) {
      var kf = state.keyframes[k];
      var kx = 40 + (w - 60) * (kf.timestamp / duration);
      var ky = 60 + t * 45 + (Math.sin(k * 1.8 + t) * 15);
      if (k === 0) ctx.moveTo(kx, ky);
      else ctx.lineTo(kx, ky);
    }
    ctx.stroke();
    ctx.setLineDash([]);

    // 点
    for (k = 0; k < state.keyframes.length; k++) {
      kf = state.keyframes[k];
      kx = 40 + (w - 60) * (kf.timestamp / duration);
      ky = 60 + t * 45 + (Math.sin(k * 1.8 + t) * 15);
      ctx.fillStyle = colors[t % colors.length];
      ctx.beginPath();
      ctx.arc(kx, ky, 4, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  byId("trajectory-status").textContent = "已生成目标跟踪轨迹";
  byId("trajectory-status").className = "traj-status available";
}

// ── 数据加载 ─────────────────────────────────────────────────────────
function loadEditorData(jobId) {
  state.jobId = jobId;
  setView("loading");

  api.get("/api/jobs/" + encodeURIComponent(jobId) + "/editor").then(
    function (payload) {
      applyEditorData(payload, false);
    },
    function (apiError) {
      // 降级使用 Mock
      console.warn("API 不可用，使用 Mock 数据：", apiError.message);
      applyEditorData(EDITOR_MOCK, true);
      showToast("后端 API 不可用，使用本地 Mock 数据预览", "info");
    }
  );
}

function applyEditorData(data, isMock) {
  state.useMock = isMock;
  state.editorData = data;
  state.video = data.video || null;
  state.segments = Array.isArray(data.segments) ? data.segments.map(function (s) { return Object.assign({}, s); }) : [];
  state.agentComments = Array.isArray(data.agent_comments) ? data.agent_comments : [];
  state.keyframes = Array.isArray(data.keyframes) ? data.keyframes : [];
  state.reviews = {};  // 每次加载重置人工审核
  state.dirty = false;

  // 确保 segments 按 order 排序
  state.segments.sort(function (a, b) { return (a.order || 0) - (b.order || 0); });

  // 更新头部
  byId("header-job-id").textContent = data.job_id || state.jobId || "—";
  var metaParts = [];
  if (data.video) metaParts.push(formatDuration(data.video.duration));
  metaParts.push(state.segments.length + " 个片段");
  if (isMock) metaParts.push("Mock 模式");
  byId("header-meta").textContent = metaParts.join(" · ");

  // 更新导出区域 job_id
  var exportJobId = byId("export-job-id");
  if (exportJobId) exportJobId.textContent = data.job_id || state.jobId || "—";
  var reportLink = byId("export-report-link");
  if (reportLink && data.job_id) {
    reportLink.href = "/api/jobs/" + encodeURIComponent(data.job_id) + "/report";
  }

  if (!state.segments.length) {
    setView("empty");
    return;
  }

  setView("content");
  renderVideo();
  renderTimeline();
  renderSegmentList();
  bindTimelineEvents();
  renderStatsDashboard();
  renderTrajectory();

  updateSaveButton();

  // 默认选中第一个片段
  if (state.segments.length > 0) {
    selectSegment(state.segments[0].id);
  }
}

// ── JSON 报告弹窗 ────────────────────────────────────────────────────
function showReportDialog() {
  var exportData = {
    job_id: state.jobId,
    use_mock: state.useMock,
    video: state.video,
    segments: state.segments,
    agent_comments: state.agentComments,
    keyframes: state.keyframes,
    reviews: state.reviews,
  };
  byId("report-content").textContent = JSON.stringify(exportData, null, 2);
  byId("report-dialog").showModal();
}

// ── 保存审核 ─────────────────────────────────────────────────────────
function saveReview() {
  if (!state.jobId || !state.segments.length) return;
  if (state.useMock) {
    showToast("Mock 模式下无法保存到服务器", "info");
    return;
  }
  var button = byId("save-review-button");
  setButtonLoading(button, true, "保存中…");

  var body = {
    segments: state.segments.map(function (seg) {
      var s = { id: seg.id, start: seg.start, end: seg.end, order: seg.order };
      var review = state.reviews[seg.id];
      if (review) {
        s.review = review.recommendation || "";
        if (review.note) s.review_note = review.note;
      }
      return s;
    }),
  };

  api.patch("/api/jobs/" + encodeURIComponent(state.jobId) + "/review", body).then(
    function (payload) {
      showToast("审核结果已保存", "success");
      if (payload.report) {
        // 同步服务端返回的 segments
        if (Array.isArray(payload.report.segments)) {
          state.segments = payload.report.segments.map(function (s) { return Object.assign({}, s); });
          state.segments.sort(function (a, b) { return (a.order || 0) - (b.order || 0); });
        }
        renderSegmentList();
        renderTimeline();
        renderStatsDashboard();
      }
      markClean();
      updateSaveButton();
      setButtonLoading(button, false);
    },
    function (error) {
      showToast("保存失败：" + error.message, "error");
      setButtonLoading(button, false);
    }
  );
}

// ── 生成粗剪（多片段）─────────────────────────────────────────────────
function createRoughCut() {
  if (!state.jobId) return;
  if (state.useMock) {
    showToast("Mock 模式下无法生成粗剪", "info");
    return;
  }
  var button = byId("rough-cut-button");
  setButtonLoading(button, true, "生成中…");

  // 先保存审核，再生成粗剪
  var saveBody = {
    segments: state.segments.map(function (seg) {
      var s = { id: seg.id, start: seg.start, end: seg.end, order: seg.order };
      var review = state.reviews[seg.id];
      if (review) {
        s.review = review.recommendation || "";
        if (review.note) s.review_note = review.note;
      }
      return s;
    }),
  };

  api.patch("/api/jobs/" + encodeURIComponent(state.jobId) + "/review", saveBody).then(
    function () {
      return api.post("/api/jobs/" + encodeURIComponent(state.jobId) + "/rough-cut", {});
    },
    function (saveErr) {
      showToast("审核保存失败：" + saveErr.message + "，继续尝试生成粗剪…", "info");
      return api.post("/api/jobs/" + encodeURIComponent(state.jobId) + "/rough-cut", {});
    }
  ).then(
    function (result) {
      var msg = "粗剪已生成";
      if (result && result.rough_cut_file) msg += "：" + result.rough_cut_file;
      showToast(msg, "success");
      setButtonLoading(button, false);
      markClean();
      updateSaveButton();
      loadEditorData(state.jobId);
    },
    function (error) {
      showToast("粗剪生成失败：" + error.message, "error");
      setButtonLoading(button, false);
    }
  );
}

// ── 按钮加载态 ─────────────────────────────────────────────────────────
function setButtonLoading(button, loading, label) {
  if (!button) return;
  if (!button.dataset.originalLabel) {
    button.dataset.originalLabel = button.textContent.trim();
  }
  button.disabled = loading;
  button.classList.toggle("is-loading", loading);
  button.textContent = loading ? label : button.dataset.originalLabel;
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

  // 重试按钮
  byId("editor-retry-button").addEventListener("click", function () { loadEditorData(jobId); });

  // 保存审核
  byId("save-review-button").addEventListener("click", saveReview);

  // 粗剪
  byId("rough-cut-button").addEventListener("click", createRoughCut);

  // 报告弹窗
  byId("view-report-button").addEventListener("click", showReportDialog);
  byId("close-report-button").addEventListener("click", function () {
    byId("report-dialog").close();
  });
  byId("report-dialog").addEventListener("click", function (e) {
    if (e.target === byId("report-dialog")) byId("report-dialog").close();
  });

  // 边界编辑 — 应用按钮
  byId("apply-boundary-btn").addEventListener("click", function () {
    if (state.selectedSegmentId) applyBoundaryEdit(state.selectedSegmentId);
  });

  // 边界编辑 — 输入框回车
  byId("edit-seg-start").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && state.selectedSegmentId) applyBoundaryEdit(state.selectedSegmentId);
  });
  byId("edit-seg-end").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && state.selectedSegmentId) applyBoundaryEdit(state.selectedSegmentId);
  });

  // 从选中片段开始播放
  byId("play-from-seg-btn").addEventListener("click", function () {
    if (!state.selectedSegmentId) return;
    var seg = state.segments.find(function (s) { return s.id === state.selectedSegmentId; });
    if (seg) seekTo(seg.start);
  });

  // 导出按钮
  var exportReportBtn = byId("export-report-download");
  if (exportReportBtn) {
    exportReportBtn.addEventListener("click", function () {
      if (state.useMock) {
        showToast("Mock 模式下无法下载报告", "info");
        return;
      }
      window.open("/api/jobs/" + encodeURIComponent(state.jobId) + "/report", "_blank");
    });
  }

  // 未保存提醒
  window.addEventListener("beforeunload", function (e) {
    if (state.dirty) {
      e.preventDefault();
      e.returnValue = "您有未保存的审核修改，确定要离开吗？";
    }
  });

  // 加载数据
  loadEditorData(jobId);
}

document.addEventListener("DOMContentLoaded", initEditor);
