"use strict";

const state = {
  currentJobId: null,
  currentJob: null,
  currentProjectId: null,
  currentProjectName: null,
  report: null,
  keyframes: [],
  segments: [],
  analysisChunks: [],
  activeKeyframeChunkId: null,
  selectedFile: null,
  previewUrl: null,
  pollTimer: null,
  agentPollTimer: null,
  agentCallId: null,
  toolCalls: [],
};

const statusLabels = {
  created: "已创建",
  queued: "排队中",
  running: "分析中",
  completed: "已完成",
  failed: "失败",
};

const api = {
  async request(url, options = {}) {
    const response = await fetch(url, options);
    let payload;
    try {
      payload = await response.json();
    } catch {
      const error = new Error(`服务返回了无法解析的响应（HTTP ${response.status}）`);
      error.status = response.status;
      throw error;
    }
    if (!response.ok || payload.ok === false) {
      const error = new Error(payload.error || `请求失败（HTTP ${response.status}）`);
      error.status = response.status;
      throw error;
    }
    return payload;
  },

  get(url) {
    return this.request(url);
  },

  post(url, body) {
    const isForm = body instanceof FormData;
    return this.request(url, {
      method: "POST",
      headers: isForm ? undefined : { "Content-Type": "application/json" },
      body: isForm ? body : JSON.stringify(body || {}),
    });
  },

  patch(url, body) {
    return this.request(url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  delete(url) {
    return this.request(url, { method: "DELETE" });
  },
};

function byId(id) {
  return document.getElementById(id);
}

function clearChildren(element) {
  if (element) element.replaceChildren();
}

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = String(text);
  return element;
}

function formatNumber(value, digits = 1) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "—";
}

function formatDuration(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} 分 ${(seconds % 60).toFixed(0)} 秒`;
}

function formatBytes(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value < 0) return "未知大小";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function outputUrl(jobId, relativePath) {
  const path = String(relativePath || "")
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
  return `/outputs/${encodeURIComponent(jobId)}/${path}`;
}

function setButtonLoading(button, loading, loadingLabel) {
  if (!button) return;
  const label = button.querySelector(".button-label") || button;
  if (!button.dataset.originalLabel) {
    button.dataset.originalLabel = label.textContent.trim();
  }
  button.disabled = loading;
  button.classList.toggle("is-loading", loading);
  label.textContent = loading ? loadingLabel : button.dataset.originalLabel;
}

function showToast(message, type = "info") {
  const container = byId("toast-container");
  if (!container) return;
  const toast = createElement("div", `toast ${type}`, message);
  container.append(toast);
  window.setTimeout(() => toast.remove(), 4200);
}

function initTheme() {
  const allowed = new Set(["dark", "light", "ocean", "forest"]);
  const saved = localStorage.getItem("reelfire-theme");
  const theme = allowed.has(saved) ? saved : "dark";
  document.body.dataset.theme = theme;
  document.querySelectorAll("[data-theme-value]").forEach((button) => {
    const active = button.dataset.themeValue === theme;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
    button.addEventListener("click", () => {
      const next = button.dataset.themeValue;
      if (!allowed.has(next)) return;
      document.body.dataset.theme = next;
      localStorage.setItem("reelfire-theme", next);
      document.querySelectorAll("[data-theme-value]").forEach((item) => {
        const selected = item.dataset.themeValue === next;
        item.classList.toggle("active", selected);
        item.setAttribute("aria-pressed", String(selected));
      });
    });
  });
}

function selectAuthView(view) {
  const login = view === "login";
  byId("login-form").hidden = !login;
  byId("register-form").hidden = login;
  byId("login-tab").classList.toggle("active", login);
  byId("register-tab").classList.toggle("active", !login);
  byId("login-tab").setAttribute("aria-selected", String(login));
  byId("register-tab").setAttribute("aria-selected", String(!login));
  byId("auth-title").textContent = login ? "登录 ReelFire" : "创建 ReelFire 账号";
  byId("auth-description").textContent = login
    ? "使用项目账号进入分析工作台。"
    : "创建当前运行环境中的项目账号。";
  byId(login ? "login-username" : "register-username").focus();
}

function authRedirectTarget() {
  const value = new URLSearchParams(window.location.search).get("next");
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/";
  try {
    const target = new URL(value, window.location.origin);
    if (target.origin !== window.location.origin) return "/";
    return `${target.pathname}${target.search}${target.hash}`;
  } catch {
    return "/";
  }
}

async function submitAuth(form, mode) {
  const isLogin = mode === "login";
  const prefix = isLogin ? "login" : "register";
  const username = byId(`${prefix}-username`).value.trim();
  const password = byId(`${prefix}-password`).value;
  const error = byId(`${prefix}-error`);
  const button = byId(`${prefix}-submit`);
  error.textContent = "";

  if (username.length < 2 || username.length > 32) {
    error.textContent = "用户名长度需为 2–32 个字符。";
    return;
  }
  if (password.length < 6) {
    error.textContent = "密码至少需要 6 个字符。";
    return;
  }
  if (!isLogin && password !== byId("register-confirm").value) {
    error.textContent = "两次输入的密码不一致。";
    return;
  }

  setButtonLoading(button, true, isLogin ? "正在登录…" : "正在创建…");
  try {
    await api.post(`/api/auth/${mode}`, { username, password });
    showToast(isLogin ? "登录成功" : "账号创建成功", "success");
    window.location.assign(authRedirectTarget());
  } catch (requestError) {
    error.textContent = requestError.message;
  } finally {
    setButtonLoading(button, false);
  }
}

async function submitGuestLogin() {
  const button = byId("guest-submit");
  const error = byId("guest-error");
  error.textContent = "";
  setButtonLoading(button, true, "正在创建游客空间…");
  try {
    await api.post("/api/auth/guest", {});
    showToast("已进入独立游客空间", "success");
    window.location.assign(authRedirectTarget());
  } catch (requestError) {
    error.textContent = requestError.message;
  } finally {
    setButtonLoading(button, false);
  }
}

function initAuth() {
  byId("login-tab").addEventListener("click", () => selectAuthView("login"));
  byId("register-tab").addEventListener("click", () => selectAuthView("register"));
  byId("login-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitAuth(event.currentTarget, "login");
  });
  byId("register-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitAuth(event.currentTarget, "register");
  });
  byId("guest-submit").addEventListener("click", submitGuestLogin);
}

function setView(view) {
  const normalized = ["upload", "history", "analysis"].includes(view)
    ? view
    : "upload";
  const history = normalized === "history";
  const analysis = normalized === "analysis";
  byId("view-analysis").hidden = history;
  byId("view-history").hidden = !history;
  byId("view-analysis").classList.toggle("active", !history);
  byId("view-history").classList.toggle("active", history);
  byId("upload-panel").hidden = history || analysis;
  byId("analysis-panel").hidden = history || !analysis;
  byId("analysis-agent-panel").hidden = history || !analysis;
  document.body.dataset.workspaceView = normalized;

  const copy = {
    upload: {
      eyebrow: "VIDEO UPLOAD",
      heading: "上传待分析视频",
      description: "上传 FPS 录屏并设置分析参数，系统仅接受视频输入。",
    },
    analysis: {
      eyebrow: "ANALYSIS WORKBENCH",
      heading: "视频分析工作台",
      description: "查看分块进度、关键帧、候选片段和 Agent 结果。",
    },
  };
  if (!history) {
    byId("workspace-eyebrow").textContent = copy[normalized].eyebrow;
    byId("analysis-heading").textContent = copy[normalized].heading;
    byId("workspace-description").textContent = copy[normalized].description;
  }
  document.querySelectorAll("[data-view]").forEach((item) => {
    const active = item.dataset.view === normalized;
    item.classList.toggle("active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  if (history) loadHistory();
}

function updateJobNavigation(jobId, editorReady = false) {
  const analysisLink = byId("nav-analysis");
  const editorLink = byId("nav-editor");
  if (!jobId) return;
  analysisLink.href = `/jobs/${encodeURIComponent(jobId)}/analysis`;
  analysisLink.classList.remove("disabled");
  analysisLink.removeAttribute("aria-disabled");
  analysisLink.removeAttribute("tabindex");
  analysisLink.removeAttribute("title");
  editorLink.href = `/jobs/${encodeURIComponent(jobId)}/editor`;
  editorLink.classList.toggle("disabled", !editorReady);
  if (editorReady) {
    editorLink.removeAttribute("aria-disabled");
    editorLink.removeAttribute("tabindex");
    editorLink.removeAttribute("title");
  } else {
    editorLink.setAttribute("aria-disabled", "true");
    editorLink.setAttribute("tabindex", "-1");
    editorLink.title = "首个 YOLO 分块完成后可进入剪辑工作台";
  }
}

async function loadUser() {
  try {
    const payload = await api.get("/api/auth/me");
    byId("user-name").textContent = payload.user.display_name || payload.user.username;
    byId("user-info").hidden = false;
    byId("login-link").hidden = true;
  } catch {
    byId("user-info").hidden = true;
    byId("login-link").hidden = false;
  }
}

async function logout() {
  try {
    await api.post("/api/auth/logout", {});
    showToast("已退出登录", "success");
    window.location.assign("/login");
  } catch (error) {
    showToast(error.message, "error");
  }
}

function clearSelectedFile() {
  state.selectedFile = null;
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = null;
  byId("video-file").value = "";
  byId("preview-video").removeAttribute("src");
  byId("preview-video").load();
  byId("file-preview").hidden = true;
  byId("upload-zone").hidden = false;
  byId("file-error").textContent = "";
}

function selectFile(file) {
  if (!file) {
    clearSelectedFile();
    return;
  }
  const allowedExtensions = /\.(mp4|mov|avi|mkv)$/i;
  if (!file.type.startsWith("video/") && !allowedExtensions.test(file.name)) {
    byId("file-error").textContent = "请选择 MP4、MOV、AVI 或 MKV 视频文件。";
    return;
  }
  if (file.size > 2 * 1024 * 1024 * 1024) {
    byId("file-error").textContent = "视频文件不能超过 2GB。";
    return;
  }
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.selectedFile = file;
  state.previewUrl = URL.createObjectURL(file);
  byId("preview-video").src = state.previewUrl;
  byId("video-filename").textContent = file.name;
  byId("video-filesize").textContent = formatBytes(file.size);
  byId("upload-zone").hidden = true;
  byId("file-preview").hidden = false;
  byId("file-error").textContent = "";
}

function initUpload() {
  const input = byId("video-file");
  const zone = byId("upload-zone");
  input.addEventListener("change", () => selectFile(input.files[0]));
  byId("clear-file-button").addEventListener("click", clearSelectedFile);
  ["dragenter", "dragover"].forEach((eventName) => {
    zone.addEventListener(eventName, (event) => {
      event.preventDefault();
      zone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    zone.addEventListener(eventName, (event) => {
      event.preventDefault();
      zone.classList.remove("dragover");
    });
  });
  zone.addEventListener("drop", (event) => {
    selectFile(event.dataTransfer.files[0]);
  });
}

function setResultState(view, status = "idle", message = "") {
  ["empty", "loading", "error", "content"].forEach((name) => {
    byId(`result-${name}`).hidden = name !== view;
  });
  const badge = byId("analysis-status");
  badge.className = `status-badge ${status}`;
  badge.textContent = statusLabels[status] || "等待输入";
  if (view === "loading" && message) byId("loading-message").textContent = message;
  if (view === "error") byId("result-error-message").textContent = message;
}

function logTool(method, path, detail) {
  state.toolCalls.push({
    method,
    path,
    detail,
    time: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
  });
  renderToolCalls();
}

function renderToolCalls() {
  const container = byId("tool-call-list");
  clearChildren(container);
  byId("tool-count").textContent = String(state.toolCalls.length);
  if (!state.toolCalls.length) {
    container.append(createElement("p", "empty-copy", "任务运行后显示 API 与处理节点。"));
    return;
  }
  state.toolCalls.forEach((call) => {
    const item = createElement("div", "tool-call");
    item.append(
      createElement("strong", "", `${call.method} ${call.path}`),
      createElement("small", "", `${call.time} · ${call.detail}`),
    );
    container.append(item);
  });
}

function updateAgentFlow(hasReport = false) {
  const nodes = [...document.querySelectorAll(".agent-node")];
  nodes.forEach((node) => node.classList.remove("complete", "blocked"));
  if (!hasReport) {
    stopAgentPolling();
    state.agentCallId = null;
    byId("agent-provider-badge").textContent = "等待 Agent";
    byId("agent-run-note").textContent =
      "YOLO 完成后会自动启动 Agent，并在这里显示排队、运行、完成或降级状态。";
    if (nodes.length >= 4) {
      nodes[0].querySelector("small").textContent = "等待任务完成";
      nodes[1].querySelector("small").textContent = "等待真实检测";
      nodes[2].querySelector("small").textContent = "等待 Agent 调用";
      nodes[3].querySelector("small").textContent = "等待复核";
    }
    return;
  }
  nodes[0].classList.add("complete");
  nodes[0].querySelector("small").textContent = "真实分析报告已读取";
  nodes[1].classList.add("complete");
  nodes[1].querySelector("small").textContent = "真实检测标签已汇总";
  nodes[2].querySelector("small").textContent = "准备启动 Agent";
  nodes[3].querySelector("small").textContent = "等待 Agent 结果与人工复核";
}

function stopAgentPolling() {
  if (state.agentPollTimer) window.clearTimeout(state.agentPollTimer);
  state.agentPollTimer = null;
}

function renderAgentCall(call) {
  const nodes = [...document.querySelectorAll(".agent-node")];
  if (nodes.length < 4 || !call) return;
  const badge = byId("agent-provider-badge");
  const note = byId("agent-run-note");
  nodes[0].classList.add("complete");
  nodes[1].classList.add("complete");
  nodes[2].classList.remove("complete", "blocked");
  nodes[3].classList.remove("complete", "blocked");

  const provider = call.model_name || "已配置的 Agent";
  const status = call.status;
  if (status === "queued") {
    badge.textContent = "Agent 排队中";
    note.textContent = "Agent 调用已创建，正在等待后台执行器。";
    nodes[2].querySelector("small").textContent = "调用已排队";
    nodes[3].querySelector("small").textContent = "等待 Agent 结果";
  } else if (status === "running") {
    badge.textContent = provider;
    note.textContent = "Agent 正在执行报告解析、知识检索、建议生成和规则校验。";
    nodes[2].querySelector("small").textContent = "Agent 正在运行";
    nodes[3].querySelector("small").textContent = "等待 Agent 结果";
  } else if (status === "completed") {
    badge.textContent = provider;
    note.textContent = "Agent 已完成，结果和工具轨迹已经保存。";
    nodes[2].classList.add("complete");
    nodes[2].querySelector("small").textContent = "Agent 结果已保存";
    nodes[3].classList.add("complete");
    nodes[3].querySelector("small").textContent = "可进入 Editor 复核";
  } else if (status === "needs_review") {
    const riskFlags = call.result?.risk_flags || [];
    const degraded = riskFlags.includes("model_generation_failed")
      || riskFlags.includes("model_provider_not_configured");
    badge.textContent = degraded ? "规则降级结果" : provider;
    note.textContent = degraded
      ? "在线模型调用失败，系统已保留规则结果；请检查 Agent 调用详情和 Dify 配置。"
      : "Agent 已完成，但结果需要人工复核。";
    nodes[2].classList.add(degraded ? "blocked" : "complete");
    nodes[2].querySelector("small").textContent = degraded
      ? "在线模型失败，已规则降级"
      : "Agent 结果待复核";
    nodes[3].classList.add("complete");
    nodes[3].querySelector("small").textContent = "请进入 Editor 复核";
  } else {
    badge.textContent = "Agent 失败";
    note.textContent = call.error_message || "Agent 执行失败，请检查服务配置。";
    nodes[2].classList.add("blocked");
    nodes[2].querySelector("small").textContent =
      call.error_code || "Agent 执行失败";
    nodes[3].classList.add("blocked");
    nodes[3].querySelector("small").textContent = "没有可复核的 Agent 结果";
  }
}

async function pollAgentCall(jobId, callId) {
  stopAgentPolling();
  try {
    const payload = await api.get(
      `/api/agent-calls/${encodeURIComponent(callId)}`,
    );
    const call = payload.agent_call;
    renderAgentCall(call);
    if (call.status === "queued" || call.status === "running") {
      state.agentPollTimer = window.setTimeout(
        () => pollAgentCall(jobId, callId),
        1400,
      );
      return;
    }
    logTool(
      "GET",
      `/api/agent-calls/${callId}`,
      `Agent 终态：${call.status}`,
    );
  } catch (error) {
    byId("agent-provider-badge").textContent = "Agent 状态异常";
    byId("agent-run-note").textContent = error.message;
  }
}

async function ensureAgentRun(jobId) {
  stopAgentPolling();
  try {
    const history = await api.get(
      `/api/jobs/${encodeURIComponent(jobId)}/agent-calls`,
    );
    let call = Array.isArray(history.agent_calls)
      ? history.agent_calls[0]
      : null;
    if (!call) {
      logTool(
        "POST",
        `/api/jobs/${jobId}/agent-calls`,
        "启动 Agent 分析",
      );
      const created = await api.post(
        `/api/jobs/${encodeURIComponent(jobId)}/agent-calls`,
        { prompt_version: "v2", force: false },
      );
      call = created.agent_call;
    }
    state.agentCallId = call.id;
    renderAgentCall(call);
    await pollAgentCall(jobId, call.id);
  } catch (error) {
    byId("agent-provider-badge").textContent = "Agent 未启动";
    byId("agent-run-note").textContent = error.message;
  }
}

function aggregateDetections(report) {
  const counts = new Map();
  (report.samples || []).forEach((sample) => {
    (sample.objects || []).forEach((object) => {
      const label = String(object.class || object.label || "unknown");
      counts.set(label, (counts.get(label) || 0) + 1);
    });
  });
  return [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label));
}

function renderDetections(report) {
  const detections = aggregateDetections(report);
  const container = byId("result-detections");
  clearChildren(container);
  detections.forEach((item) => {
    const row = createElement("div", "detection-item");
    row.append(createElement("span", "", item.label), createElement("strong", "", item.count));
    container.append(row);
  });
  if (!detections.length) {
    container.append(createElement("p", "empty-copy", "当前采样帧没有检测到目标。"));
  }
  const total = detections.reduce((sum, item) => sum + item.count, 0);
  byId("detection-count").textContent = `${total} 次检测`;

  const tags = byId("result-tags");
  clearChildren(tags);
  const summary = report.segment_tags?.summary || [];
  summary.forEach((tag) => tags.append(createElement("span", "tag", tag)));
}

function renderSegments(segments) {
  const container = byId("segment-list");
  clearChildren(container);
  byId("segment-count").textContent = `${segments.length} 个片段`;
  if (!segments.length) {
    container.append(createElement("p", "empty-copy", "报告中没有候选片段。"));
    return;
  }
  segments.forEach((segment, index) => {
    const item = createElement("div", "segment-item");
    const order = createElement("span", "segment-order", String(index + 1).padStart(2, "0"));
    const detail = createElement("div");
    detail.append(
      createElement(
        "strong",
        "",
        `${formatNumber(segment.start)}s – ${formatNumber(segment.end)}s`,
      ),
      createElement(
        "small",
        "",
        `来源关键帧：${(segment.source_keyframes || []).join("、") || "未标注"}`,
      ),
    );
    item.append(
      order,
      detail,
      createElement("span", "segment-score", formatNumber(Number(segment.score) * 100, 0)),
    );
    container.append(item);
  });
}

function renderAnalysisProgress(progress) {
  const value = progress && typeof progress === "object" ? progress : {};
  const total = Number(value.total_chunks) || 0;
  const completed = Number(value.completed_chunks) || 0;
  const percent = Math.max(0, Math.min(100, Number(value.percent) || 0));
  const chunks = Array.isArray(value.chunks) ? value.chunks : [];
  byId("analysis-progress-count").textContent = `${completed} / ${total}`;
  byId("analysis-progress-percent").textContent = `${Math.round(percent)}%`;
  byId("analysis-progress-bar").value = percent;
  byId("analysis-progress-bar").textContent = `${Math.round(percent)}%`;
  byId("analysis-progress-detail").textContent =
    value.message || "正在等待新的分块结果。";

  const track = byId("analysis-chunk-track");
  clearChildren(track);
  if (!total) {
    track.append(createElement("span", "chunk-empty", "等待计算视频分块"));
  } else {
    for (let index = 0; index < total; index += 1) {
      const chunk = chunks[index];
      const current =
        value.current_chunk && Number(value.current_chunk.index) === index + 1;
      const rawStatus = chunk && typeof chunk.status === "string"
        ? chunk.status
        : null;
      const status =
        rawStatus === "completed" || (chunk && !rawStatus && !current)
          ? "completed"
          : rawStatus === "running" || current
            ? "running"
            : "pending";
      const item = createElement("span", `analysis-chunk ${status}`);
      item.setAttribute("role", "listitem");
      item.textContent =
        status === "completed"
          ? `${index + 1} 已完成`
          : status === "running"
            ? `${index + 1} 分析中`
            : `${index + 1} 排队中`;
      item.title = chunk && Number.isFinite(Number(chunk.start))
        ? `${formatDuration(chunk.start)} – ${formatDuration(chunk.end)}`
        : `分析分块 ${index + 1}`;
      track.append(item);
    }
  }

  const partialSegments = chunks
    .flatMap((chunk) =>
      Array.isArray(chunk.provisional_segments)
        ? chunk.provisional_segments
        : [],
    )
    .slice(-12);
  const partialKeyframes = chunks
    .flatMap((chunk) => (Array.isArray(chunk.keyframes) ? chunk.keyframes : []))
    .slice(-12);
  byId("partial-results").hidden =
    partialSegments.length === 0 && partialKeyframes.length === 0;

  const segmentList = byId("partial-segment-list");
  clearChildren(segmentList);
  partialSegments.forEach((segment) => {
    const item = createElement("span", "partial-segment");
    item.textContent =
      `${formatDuration(segment.start)}–${formatDuration(segment.end)} 暂定`;
    segmentList.append(item);
  });

  const keyframeList = byId("partial-keyframe-list");
  clearChildren(keyframeList);
  partialKeyframes.forEach((frame) => {
    const image = document.createElement("img");
    image.src = outputUrl(state.currentJobId, frame.image);
    image.alt =
      `已分析关键帧 ${frame.id}，时间 ${formatDuration(frame.timestamp)}`;
    image.loading = "lazy";
    image.width = 160;
    image.height = 90;
    keyframeList.append(image);
  });
}

function persistVisibleKeyframeReview() {
  document.querySelectorAll(".keyframe-card").forEach((card) => {
    const index = Number(card.dataset.frameIndex);
    const frame = state.keyframes[index];
    if (!frame) return;
    const decision = card.querySelector(".review-decision");
    const note = card.querySelector(".review-note");
    if (decision) {
      frame.decision = decision.value;
      frame.keep = decision.value === "keep";
    }
    if (note) frame.note = note.value.trim();
  });
}

function keyframeGroups() {
  if (state.analysisChunks.length) {
    return state.analysisChunks
      .map((chunk) => ({
        id: chunk.id,
        label: `${formatDuration(chunk.start)}–${formatDuration(chunk.end)}`,
        start: Number(chunk.start) || 0,
        end: Number(chunk.end) || 0,
        frames: state.keyframes
          .map((frame, index) => ({ frame, index }))
          .filter(({ frame }) => frame.chunk_id === chunk.id),
      }))
      .filter((group) => group.frames.length > 0);
  }
  const grouped = new Map();
  state.keyframes.forEach((frame, index) => {
    const id = frame.chunk_id || "all";
    if (!grouped.has(id)) grouped.set(id, []);
    grouped.get(id).push({ frame, index });
  });
  return [...grouped.entries()].map(([id, frames]) => ({
    id,
    label: id === "all" ? "全部关键帧" : id,
    start: Math.min(...frames.map(({ frame }) => Number(frame.timestamp) || 0)),
    end: Math.max(...frames.map(({ frame }) => Number(frame.timestamp) || 0)),
    frames,
  }));
}

function renderActiveKeyframeGroup(groups) {
  const container = byId("keyframe-list");
  clearChildren(container);
  const active =
    groups.find((group) => group.id === state.activeKeyframeChunkId) || groups[0];
  if (!active) {
    container.append(createElement("p", "empty-copy", "报告中没有关键帧。"));
    byId("keyframe-chunk-summary").textContent = "";
    return;
  }
  state.activeKeyframeChunkId = active.id;
  byId("keyframe-chunk-summary").textContent =
    `当前时间段 ${active.label}，显示 ${active.frames.length} 张关键帧。`;
  byId("keyframe-chunk-tabs")
    .querySelectorAll("[role='tab']")
    .forEach((tab) => {
      const selected = tab.dataset.chunkId === active.id;
      tab.classList.toggle("active", selected);
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });

  active.frames.forEach(({ frame, index }) => {
    const card = createElement("article", "keyframe-card");
    card.dataset.frameIndex = String(index);
    const image = document.createElement("img");
    image.src = outputUrl(state.currentJobId, frame.image);
    image.alt = `关键帧 ${frame.id || index + 1}，时间 ${formatNumber(frame.timestamp)} 秒`;
    image.loading = "lazy";
    const body = createElement("div", "keyframe-body");
    const meta = createElement("div", "keyframe-meta");
    meta.append(
      createElement("span", "", `${frame.id || `#${index + 1}`} · ${formatNumber(frame.timestamp)}s`),
      createElement("strong", "", `评分 ${formatNumber(Number(frame.highlight_score) * 100, 0)}`),
    );
    const controls = createElement("div", "review-controls");
    const decision = document.createElement("select");
    decision.className = "review-decision";
    decision.setAttribute("aria-label", `${frame.id || index + 1} 审核决定`);
    [
      ["keep", "保留"],
      ["skip", "跳过"],
    ].forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      option.selected = (frame.decision || "keep") === value;
      decision.append(option);
    });
    const note = document.createElement("input");
    note.className = "review-note";
    note.value = frame.note || "";
    note.maxLength = 500;
    note.placeholder = "审核备注";
    note.setAttribute("aria-label", `${frame.id || index + 1} 审核备注`);
    controls.append(decision, note);
    body.append(meta, controls);
    card.append(image, body);
    container.append(card);
  });
}

function renderKeyframes(keyframes) {
  const tabs = byId("keyframe-chunk-tabs");
  clearChildren(tabs);
  if (!keyframes.length) {
    renderActiveKeyframeGroup([]);
    return;
  }
  const groups = keyframeGroups();
  if (!groups.some((group) => group.id === state.activeKeyframeChunkId)) {
    state.activeKeyframeChunkId = groups[0] ? groups[0].id : null;
  }
  groups.forEach((group) => {
    const button = createElement(
      "button",
      "keyframe-chunk-tab",
      `${group.label} · ${group.frames.length}`,
    );
    button.type = "button";
    button.setAttribute("role", "tab");
    button.dataset.chunkId = group.id;
    button.addEventListener("click", () => {
      persistVisibleKeyframeReview();
      state.activeKeyframeChunkId = group.id;
      renderActiveKeyframeGroup(groups);
    });
    tabs.append(button);
  });
  renderActiveKeyframeGroup(groups);
}

function renderOutputs(report) {
  const output = report.output || {};
  const files = [
    ["粗剪视频", output.video],
    ["关键帧联系表", output.contact_sheet],
  ].filter(([, path]) => path);
  const card = byId("output-card");
  const container = byId("output-list");
  clearChildren(container);
  card.hidden = !files.length;
  files.forEach(([label, path]) => {
    const link = createElement("a", "output-link");
    link.href = outputUrl(state.currentJobId, path);
    link.target = "_blank";
    link.rel = "noopener";
    link.append(createElement("span", "", label), createElement("small", "", path));
    container.append(link);
  });
}

function renderReport(report) {
  state.report = report;
  state.keyframes = Array.isArray(report.keyframes) ? report.keyframes.map((item) => ({ ...item })) : [];
  state.segments = Array.isArray(report.segments) ? report.segments.map((item) => ({ ...item })) : [];
  state.analysisChunks = Array.isArray(report.analysis_chunks)
    ? report.analysis_chunks.map((item) => ({ ...item }))
    : [];
  const scores = state.keyframes.map((frame) => Number(frame.highlight_score)).filter(Number.isFinite);
  const maxScore = scores.length ? Math.max(...scores) : 0;
  const detected = aggregateDetections(report);
  const classNames = detected.slice(0, 4).map((item) => item.label);

  byId("result-summary").textContent = detected.length
    ? `在 ${report.total_sampled_frames || 0} 个采样帧中识别到 ${detected.length} 类目标：${classNames.join("、")}。候选片段与评分均来自当前分析报告。`
    : `已完成 ${report.total_sampled_frames || 0} 个采样帧的分析，当前未识别到目标类别。`;
  byId("metric-duration").textContent = formatDuration(report.duration);
  byId("metric-frames").textContent = String(report.total_sampled_frames ?? "—");
  byId("metric-keyframes").textContent = String(state.keyframes.length);
  byId("metric-score").textContent = `${formatNumber(maxScore * 100, 0)} / 100`;

  renderDetections(report);
  renderSegments(state.segments);
  renderKeyframes(state.keyframes);
  renderOutputs(report);
  byId("report-content").textContent = JSON.stringify(report, null, 2);
  byId("generation-panel").hidden = false;
  byId("generation-output").hidden = true;
  updateAgentFlow(true);
  setResultState("content", "completed");

  // 显示剪辑预览入口
  var editorLink = byId("editor-link");
  if (editorLink) {
    editorLink.href = "/jobs/" + encodeURIComponent(state.currentJobId) + "/editor";
    editorLink.hidden = false;
  }
  updateJobNavigation(state.currentJobId, true);
}

async function loadReport(jobId) {
  logTool("GET", `/api/jobs/${jobId}/report`, "读取真实分析报告");
  const payload = await api.get(`/api/jobs/${encodeURIComponent(jobId)}/report`);
  renderReport(payload.report);
  await ensureAgentRun(jobId);
}

function stopPolling() {
  if (state.pollTimer) window.clearTimeout(state.pollTimer);
  state.pollTimer = null;
}

async function pollJob(jobId) {
  stopPolling();
  try {
    const payload = await api.get(`/api/jobs/${encodeURIComponent(jobId)}`);
    const job = payload.job;
    state.currentJob = job;
    renderAnalysisProgress(job.progress);
    updateJobNavigation(
      jobId,
      job.status === "completed" ||
        Number(job.progress && job.progress.completed_chunks) > 0,
    );
    if (job.status === "completed") {
      logTool("GET", `/api/jobs/${jobId}`, "任务已完成");
      await loadReport(jobId);
      showToast("视频分析完成", "success");
      return;
    }
    if (job.status === "failed") {
      logTool("GET", `/api/jobs/${jobId}`, "任务失败");
      setResultState("error", "failed", job.error || "分析任务失败。");
      return;
    }
    const message =
      job.status === "running"
        ? "正在进行视频采样、目标检测与片段评分…"
        : "任务已创建，正在等待分析线程…";
    setResultState("loading", job.status || "queued", message);
    state.pollTimer = window.setTimeout(() => pollJob(jobId), 1600);
  } catch (error) {
    setResultState("error", "failed", error.message);
  }
}

async function resolveProject(projectName, gameType) {
  // 仅在项目名称未变化时复用已创建的 project_id。
  if (state.currentProjectId && state.currentProjectName === projectName) {
    return state.currentProjectId;
  }
  state.currentProjectId = null;
  state.currentProjectName = null;

  // 尝试创建项目；后端兼容期可能返回 404，此时降级使用 project_name。
  try {
    const payload = await api.post("/api/projects", {
      name: projectName,
      game_type: gameType,
    });
    if (payload.project && payload.project.id) {
      state.currentProjectId = payload.project.id;
      state.currentProjectName = projectName;
      return payload.project.id;
    }
  } catch (error) {
    const status = error.status || 0;
    if ([400, 401, 403, 500].includes(status)) {
      showToast(`项目创建失败：${error.message}`, "error");
    }
  }
  return null;
}

async function submitAnalysis() {
  const file = state.selectedFile || byId("video-file").files[0];
  const projectName = byId("project-name").value.trim();
  if (!projectName) {
    showToast("请填写项目名称。", "error");
    byId("project-name").focus();
    return;
  }
  if (!file) {
    byId("file-error").textContent = "请先选择一个视频文件。";
    byId("upload-zone").focus();
    return;
  }

  const button = byId("analyze-button");
  const gameType = byId("game-type").value;

  // 解析项目：优先获取 project_id，失败时降级为 project_name
  setButtonLoading(button, true, "正在准备…");
  const projectId = await resolveProject(projectName, gameType);

  const form = new FormData();
  form.append("file", file, file.name);
  // project_id 是任务归属依据（整数），优先使用
  if (projectId) {
    form.append("project_id", String(projectId));
  }
  // project_name 仅用于页面显示和兼容期降级
  form.append("project_name", projectName);
  form.append("game_type", gameType);
  form.append("sample_interval", byId("sample-interval").value);
  form.append("target_duration", byId("target-duration").value);
  form.append("output_ratio", byId("output-ratio").value);

  stopPolling();
  state.toolCalls = [];
  renderToolCalls();
  updateAgentFlow(false);
  setButtonLoading(button, true, "正在创建任务…");
  setResultState("loading", "queued", "正在上传视频并创建任务…");
  try {
    logTool("POST", "/api/jobs", `上传 ${file.name}`);
    const created = await api.post("/api/jobs", form);
    state.currentJobId = created.job_id;
    updateJobNavigation(created.job_id, false);
    window.history.replaceState(
      {},
      "",
      `/jobs/${encodeURIComponent(created.job_id)}/analysis`,
    );
    setView("analysis");
    if (created.project_id) state.currentProjectId = created.project_id;
    logTool("POST", `/api/jobs/${created.job_id}/analyze`, "启动真实 CV 分析");
    await api.post(`/api/jobs/${encodeURIComponent(created.job_id)}/analyze`, {});
    setButtonLoading(button, false);
    await pollJob(created.job_id);
  } catch (error) {
    setButtonLoading(button, false);
    setResultState("error", "failed", error.message);
    showToast(error.message, "error");
  }
}

function collectReview() {
  persistVisibleKeyframeReview();
  return state.keyframes.map((frame) => ({ ...frame }));
}

async function saveReview() {
  if (!state.currentJobId || !state.report) return;
  const button = byId("save-review-button");
  setButtonLoading(button, true, "保存中…");
  try {
    const keyframes = collectReview();
    logTool("PATCH", `/api/jobs/${state.currentJobId}/review`, "保存人工审核决策");
    const payload = await api.patch(
      `/api/jobs/${encodeURIComponent(state.currentJobId)}/review`,
      { keyframes, segments: state.segments },
    );
    renderReport(payload.report);
    showToast("审核结果已保存", "success");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setButtonLoading(button, false);
  }
}

async function createRoughCut() {
  if (!state.currentJobId || !state.report) return;
  const button = byId("rough-cut-button");
  setButtonLoading(button, true, "生成中…");
  try {
    await saveReview();
    logTool("POST", `/api/jobs/${state.currentJobId}/rough-cut`, "调用 FFmpeg 生成粗剪");
    await api.post(`/api/jobs/${encodeURIComponent(state.currentJobId)}/rough-cut`, {});
    await loadReport(state.currentJobId);
    showToast("粗剪视频已生成", "success");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setButtonLoading(button, false);
  }
}

function showRuleOutput(type) {
  if (!state.report) return;
  const output = byId("generation-output");
  let value;
  if (type === "cover") {
    value = state.report.ai_cover_prompt || "报告未生成封面描述。";
  } else if (type === "tags") {
    value = JSON.stringify(state.report.segment_tags || {}, null, 2);
  } else {
    value = JSON.stringify(state.report, null, 2);
  }
  output.textContent = value;
  output.hidden = false;
}

function showReportDialog() {
  if (!state.report) return;
  byId("report-content").textContent = JSON.stringify(state.report, null, 2);
  byId("report-dialog").showModal();
}

function historyStatus(status) {
  return statusLabels[status] || status || "未知";
}

function renderHistory(jobs) {
  byId("history-loading").hidden = true;
  byId("history-error").hidden = true;
  byId("history-empty").hidden = jobs.length > 0;
  byId("history-table-wrapper").hidden = jobs.length === 0;
  const body = byId("history-body");
  clearChildren(body);

  jobs.forEach((job) => {
    const row = document.createElement("tr");
    const projectCell = createElement("td", "", job.project_name || "未命名任务");
    const assetCell = createElement("td", "", job.original_asset_name || job.asset_name || "—");
    const typeCell = createElement("td", "", job.game_type || "other");
    const statusCell = document.createElement("td");
    statusCell.append(createElement("span", `history-status ${job.status || ""}`, historyStatus(job.status)));
    const dateCell = createElement("td", "", formatDate(job.created_at));
    const actionCell = document.createElement("td");
    const actions = createElement("div", "table-actions");
    const openButton = createElement(
      "button",
      "button secondary small",
      job.status === "completed" ? "打开" : "查看",
    );
    openButton.type = "button";
    openButton.dataset.historyAction = "open";
    openButton.dataset.jobId = job.job_id;
    const deleteButton = createElement("button", "button ghost small", "删除");
    deleteButton.type = "button";
    deleteButton.dataset.historyAction = "delete";
    deleteButton.dataset.jobId = job.job_id;
    actions.append(openButton, deleteButton);
    actionCell.append(actions);
    row.append(projectCell, assetCell, typeCell, statusCell, dateCell, actionCell);
    body.append(row);
  });
}

async function loadHistory() {
  byId("history-loading").hidden = false;
  byId("history-empty").hidden = true;
  byId("history-error").hidden = true;
  byId("history-table-wrapper").hidden = true;
  try {
    const payload = await api.get("/api/jobs");
    renderHistory(Array.isArray(payload.jobs) ? payload.jobs : []);
  } catch (error) {
    byId("history-loading").hidden = true;
    byId("history-error").hidden = false;
    byId("history-error-message").textContent = error.message;
  }
}

async function openHistoryJob(jobId) {
  window.location.assign(`/jobs/${encodeURIComponent(jobId)}/analysis`);
}

async function hydrateAnalysisJob(jobId) {
  try {
    const payload = await api.get(`/api/jobs/${encodeURIComponent(jobId)}`);
    state.currentJobId = jobId;
    state.currentJob = payload.job;
    state.toolCalls = [];
    updateJobNavigation(jobId, payload.job.status === "completed");
    renderAnalysisProgress(payload.job.progress);
    logTool("GET", `/api/jobs/${jobId}`, "从任务链接恢复分析工作台");
    if (payload.job.status === "completed") {
      await loadReport(jobId);
    } else if (payload.job.status === "failed") {
      setResultState("error", "failed", payload.job.error || "任务失败。");
    } else {
      await pollJob(jobId);
    }
  } catch (error) {
    setResultState("error", "failed", error.message);
    showToast(error.message, "error");
  }
}

async function deleteHistoryJob(jobId) {
  if (!window.confirm("删除后将同时移除该任务的上传文件与输出结果，确定继续吗？")) return;
  try {
    await api.delete(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (state.currentJobId === jobId) {
      stopPolling();
      state.currentJobId = null;
      state.currentJob = null;
      state.report = null;
      setResultState("empty", "idle");
    }
    showToast("任务已删除", "success");
    await loadHistory();
  } catch (error) {
    showToast(error.message, "error");
  }
}

function initApp() {
  document.querySelectorAll("[data-view]").forEach((item) => {
    item.addEventListener("click", (event) => {
      if (item.getAttribute("aria-disabled") === "true") {
        event.preventDefault();
        showToast(item.title || "该工作台当前不可用。", "info");
      }
    });
  });
  byId("logout-button").addEventListener("click", logout);
  byId("project-name").addEventListener("input", () => {
    state.currentProjectId = null;
    state.currentProjectName = null;
  });
  byId("analysis-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitAnalysis();
  });
  byId("retry-button").addEventListener("click", submitAnalysis);
  byId("save-review-button").addEventListener("click", saveReview);
  byId("rough-cut-button").addEventListener("click", createRoughCut);
  byId("open-report-button").addEventListener("click", showReportDialog);
  byId("close-report-button").addEventListener("click", () => byId("report-dialog").close());
  byId("report-dialog").addEventListener("click", (event) => {
    if (event.target === byId("report-dialog")) byId("report-dialog").close();
  });
  byId("refresh-history-button").addEventListener("click", loadHistory);
  byId("history-body").addEventListener("click", (event) => {
    const button = event.target.closest("[data-history-action]");
    if (!button) return;
    if (button.dataset.historyAction === "open") openHistoryJob(button.dataset.jobId);
    if (button.dataset.historyAction === "delete") deleteHistoryJob(button.dataset.jobId);
  });
  byId("show-cover-button").addEventListener("click", () => showRuleOutput("cover"));
  byId("show-tags-button").addEventListener("click", () => showRuleOutput("tags"));
  byId("show-report-button").addEventListener("click", () => showRuleOutput("report"));
  initUpload();
  loadUser();
  const initialView = document.body.dataset.initialView || "upload";
  const initialJobId = document.body.dataset.jobId || "";
  setView(initialView);
  if (initialView === "analysis" && initialJobId) {
    hydrateAnalysisJob(initialJobId);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  if (document.body.dataset.page === "auth") initAuth();
  if (document.body.dataset.page === "app") initApp();
});

window.addEventListener("beforeunload", () => {
  stopPolling();
  stopAgentPolling();
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
});
