"use strict";

const state = {
  currentJobId: null,
  currentJob: null,
  currentProjectId: null,
  currentProjectName: null,
  report: null,
  keyframes: [],
  segments: [],
  selectedFile: null,
  previewUrl: null,
  pollTimer: null,
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
      const err = new Error(`服务返回了无法解析的响应（HTTP ${response.status}）`);
      err.status = response.status;
      throw err;
    }
    if (!response.ok || payload.ok === false) {
      const err = new Error(payload.error || `请求失败（HTTP ${response.status}）`);
      err.status = response.status;
      throw err;
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
    window.location.assign("/");
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
}

function setView(view) {
  const history = view === "history";
  byId("view-analysis").hidden = history;
  byId("view-history").hidden = !history;
  byId("view-analysis").classList.toggle("active", !history);
  byId("view-history").classList.toggle("active", history);
  document.querySelectorAll("[data-view]").forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  if (history) loadHistory();
}

async function loadUser() {
  try {
    const payload = await api.get("/api/auth/me");
    byId("user-name").textContent = payload.user.username;
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
    await loadUser();
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
  if (!hasReport) return;
  nodes[0].classList.add("complete");
  nodes[0].querySelector("small").textContent = "真实分析报告已读取";
  nodes[1].classList.add("complete");
  nodes[1].querySelector("small").textContent = "真实检测标签已汇总";
  nodes[2].classList.add("blocked");
  nodes[2].querySelector("small").textContent = "独立 Agent 服务待接入";
  nodes[3].querySelector("small").textContent = "可修改关键帧决策并保存";
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

function renderKeyframes(keyframes) {
  const container = byId("keyframe-list");
  clearChildren(container);
  if (!keyframes.length) {
    container.append(createElement("p", "empty-copy", "报告中没有关键帧。"));
    return;
  }
  keyframes.forEach((frame, index) => {
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
}

async function loadReport(jobId) {
  logTool("GET", `/api/jobs/${jobId}/report`, "读取真实分析报告");
  const payload = await api.get(`/api/jobs/${encodeURIComponent(jobId)}/report`);
  renderReport(payload.report);
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
  // 如果已有缓存的 project_id 且项目名称未变更，直接复用
  if (state.currentProjectId && state.currentProjectName === projectName) {
    return state.currentProjectId;
  }
  // 项目名称已变更或尚无缓存，清空旧 project_id
  state.currentProjectId = null;
  state.currentProjectName = null;

  // 尝试创建项目（后端兼容期可能返回 404，降级使用 project_name）
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
  } catch (err) {
    const status = err.status || 0;
    // 404 或接口尚未接入：静默降级，不阻塞上传流程
    if (status === 404) {
      // 后端项目 API 尚未接入，此场景允许兼容回退
    } else if (status === 400 || status === 401 || status === 403 || status === 500) {
      // 明确的服务器错误，提示用户
      showToast(`项目创建失败：${err.message}`, "error");
    }
    // 网络超时、DNS 错误等（status === 0）也静默降级
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
  return [...document.querySelectorAll(".keyframe-card")].map((card) => {
    const index = Number(card.dataset.frameIndex);
    const frame = { ...state.keyframes[index] };
    frame.decision = card.querySelector(".review-decision").value;
    frame.keep = frame.decision === "keep";
    frame.note = card.querySelector(".review-note").value.trim();
    return frame;
  });
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
  try {
    const payload = await api.get(`/api/jobs/${encodeURIComponent(jobId)}`);
    state.currentJobId = jobId;
    state.currentJob = payload.job;
    state.toolCalls = [];
    logTool("GET", `/api/jobs/${jobId}`, "从历史记录打开任务");
    setView("analysis");
    if (payload.job.status === "completed") {
      await loadReport(jobId);
    } else if (payload.job.status === "failed") {
      setResultState("error", "failed", payload.job.error || "任务失败。");
    } else {
      await pollJob(jobId);
    }
  } catch (error) {
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
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
  byId("logout-button").addEventListener("click", logout);
  // project_name 变更时清空旧 currentProjectId，防止新名称与旧 ID 一起提交
  byId("project-name").addEventListener("input", () => {
    if (state.currentProjectId) {
      state.currentProjectId = null;
      state.currentProjectName = null;
    }
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
}

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  if (document.body.dataset.page === "auth") initAuth();
  if (document.body.dataset.page === "app") initApp();
});

window.addEventListener("beforeunload", () => {
  stopPolling();
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
});
