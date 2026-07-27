// ReelFire — analysis pipeline: submit, poll, render reports
import { appState, statusLabels } from "../state/app-state.js";
import api from "../api/client.js";
import { byId, clearChildren, createElement } from "../utils/dom.js";
import { formatNumber, formatDuration } from "../utils/format.js";
import { outputUrl } from "../utils/url.js";
import { showToast, setButtonLoading } from "../utils/ui.js";
import { renderWorkbenchCharts } from "./charts.js";
import { isSSESupported, connectSSE } from "../api/sse.js";

// ── view switching ────────────────────────────────────────────────────

export function setView(view) {
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
  if (history) {
    // dynamic import to avoid circular dependency at module level
    import("./history.js").then((m) => m.loadHistory());
  }
}

// ── result state ──────────────────────────────────────────────────────

export function setResultState(view, status = "idle", message = "") {
  ["empty", "loading", "error", "content"].forEach((name) => {
    byId(`result-${name}`).hidden = name !== view;
  });
  const badge = byId("analysis-status");
  badge.className = `status-badge ${status}`;
  badge.textContent = statusLabels[status] || "等待输入";
  if (view === "loading" && message) byId("loading-message").textContent = message;
  if (view === "error") byId("result-error-message").textContent = message;
}

// ── tool call log ─────────────────────────────────────────────────────

export function logTool(method, path, detail) {
  appState.toolCalls.push({
    method,
    path,
    detail,
    time: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
  });
  renderToolCalls();
}

export function renderToolCalls() {
  const container = byId("tool-call-list");
  clearChildren(container);
  byId("tool-count").textContent = String(appState.toolCalls.length);
  if (!appState.toolCalls.length) {
    container.append(createElement("p", "empty-copy", "任务运行后显示 API 与处理节点。"));
    return;
  }
  appState.toolCalls.forEach((call) => {
    const item = createElement("div", "tool-call");
    item.append(
      createElement("strong", "", `${call.method} ${call.path}`),
      createElement("small", "", `${call.time} · ${call.detail}`),
    );
    container.append(item);
  });
}

// ── agent flow ────────────────────────────────────────────────────────

export function updateAgentFlow(hasReport = false) {
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

// ── detection aggregation ─────────────────────────────────────────────

export function aggregateDetections(report) {
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

// ── render functions ──────────────────────────────────────────────────

export function renderDetections(report) {
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

export function renderSegments(segments) {
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

export function renderKeyframes(keyframes) {
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
    image.src = outputUrl(appState.currentJobId, frame.image);
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

export function renderOutputs(report) {
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
    link.href = outputUrl(appState.currentJobId, path);
    link.target = "_blank";
    link.rel = "noopener";
    link.append(createElement("span", "", label), createElement("small", "", path));
    container.append(link);
  });
}

export function renderReport(report) {
  appState.report = report;
  appState.keyframes = Array.isArray(report.keyframes) ? report.keyframes.map((item) => ({ ...item })) : [];
  appState.segments = Array.isArray(report.segments) ? report.segments.map((item) => ({ ...item })) : [];
  const scores = appState.keyframes.map((frame) => Number(frame.highlight_score)).filter(Number.isFinite);
  const maxScore = scores.length ? Math.max(...scores) : 0;
  const detected = aggregateDetections(report);
  const classNames = detected.slice(0, 4).map((item) => item.label);

  byId("result-summary").textContent = detected.length
    ? `在 ${report.total_sampled_frames || 0} 个采样帧中识别到 ${detected.length} 类目标：${classNames.join("、")}。候选片段与评分均来自当前分析报告。`
    : `已完成 ${report.total_sampled_frames || 0} 个采样帧的分析，当前未识别到目标类别。`;
  byId("metric-duration").textContent = formatDuration(report.duration);
  byId("metric-frames").textContent = String(report.total_sampled_frames ?? "—");
  byId("metric-keyframes").textContent = String(appState.keyframes.length);
  byId("metric-score").textContent = `${formatNumber(maxScore * 100, 0)} / 100`;

  renderDetections(report);
  renderSegments(appState.segments);
  renderKeyframes(appState.keyframes);
  renderOutputs(report);
  byId("report-content").textContent = JSON.stringify(report, null, 2);
  byId("generation-panel").hidden = false;
  byId("generation-output").hidden = true;
  updateAgentFlow(true);
  setResultState("content", "completed");

  const editorLink = byId("editor-link");
  if (editorLink) {
    editorLink.href = "/jobs/" + encodeURIComponent(appState.currentJobId) + "/editor";
    editorLink.hidden = false;
  }

  renderWorkbenchCharts(report);
}

export async function loadReport(jobId) {
  logTool("GET", `/api/jobs/${jobId}/report`, "读取真实分析报告");
  const payload = await api.get(`/api/jobs/${encodeURIComponent(jobId)}/report`);
  renderReport(payload.report);
}

// ── polling ───────────────────────────────────────────────────────────

export function stopPolling() {
  if (appState.pollTimer) window.clearTimeout(appState.pollTimer);
  appState.pollTimer = null;
}

export async function pollJob(jobId) {
  stopPolling();
  try {
    const payload = await api.get(`/api/jobs/${encodeURIComponent(jobId)}`);
    const job = payload.job;
    appState.currentJob = job;
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
    appState.pollTimer = window.setTimeout(() => pollJob(jobId), 1600);
  } catch (error) {
    setResultState("error", "failed", error.message);
  }
}

// SSE-backed watch (falls back to polling)
export function watchJob(jobId) {
  if (isSSESupported()) {
    const es = connectSSE(jobId, {
      onCompleted() {
        es.close();
        logTool("SSE", `/api/jobs/${jobId}`, "任务已完成");
        loadReport(jobId).then(() => showToast("视频分析完成", "success"));
      },
      onError(data) {
        es.close();
        setResultState("error", "failed", (data && data.error) || "分析任务失败。");
      },
      onSnapshot(data) {
        if (data && data.status) {
          const message =
            data.status === "running"
              ? "正在进行视频采样、目标检测与片段评分…"
              : "任务已创建，正在等待分析线程…";
          setResultState("loading", data.status, message);
        }
      },
    });
    window.addEventListener("beforeunload", () => es.close());
    return es;
  }
  // fallback to polling
  return pollJob(jobId);
}

// ── project & submission ──────────────────────────────────────────────

export async function resolveProject(projectName, gameType) {
  if (appState.currentProjectId && appState.currentProjectName === projectName) {
    return appState.currentProjectId;
  }
  appState.currentProjectId = null;
  appState.currentProjectName = null;

  try {
    const payload = await api.post("/api/projects", {
      name: projectName,
      game_type: gameType,
    });
    if (payload.project && payload.project.id) {
      appState.currentProjectId = payload.project.id;
      appState.currentProjectName = projectName;
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

export async function submitAnalysis() {
  const file = appState.selectedFile || byId("video-file").files[0];
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

  setButtonLoading(button, true, "正在准备…");
  const projectId = await resolveProject(projectName, gameType);

  const form = new FormData();
  form.append("file", file, file.name);
  if (projectId) {
    form.append("project_id", String(projectId));
  }
  form.append("project_name", projectName);
  form.append("game_type", gameType);
  form.append("sample_interval", byId("sample-interval").value);
  form.append("target_duration", byId("target-duration").value);
  form.append("output_ratio", byId("output-ratio").value);

  stopPolling();
  appState.toolCalls = [];
  renderToolCalls();
  updateAgentFlow(false);
  setButtonLoading(button, true, "正在创建任务…");
  setResultState("loading", "queued", "正在上传视频并创建任务…");
  try {
    logTool("POST", "/api/jobs", `上传 ${file.name}`);
    const created = await api.post("/api/jobs", form);
    appState.currentJobId = created.job_id;
    if (created.project_id) appState.currentProjectId = created.project_id;
    logTool("POST", `/api/jobs/${created.job_id}/analyze`, "启动真实 CV 分析");
    await api.post(`/api/jobs/${encodeURIComponent(created.job_id)}/analyze`, {});
    setButtonLoading(button, false);
    // prefer SSE, fallback to polling
    watchJob(created.job_id);
  } catch (error) {
    setButtonLoading(button, false);
    setResultState("error", "failed", error.message);
    showToast(error.message, "error");
  }
}

// ── rule output / report dialog ───────────────────────────────────────

export function showRuleOutput(type) {
  if (!appState.report) return;
  const output = byId("generation-output");
  let value;
  if (type === "cover") {
    value = appState.report.ai_cover_prompt || "报告未生成封面描述。";
  } else if (type === "tags") {
    value = JSON.stringify(appState.report.segment_tags || {}, null, 2);
  } else {
    value = JSON.stringify(appState.report, null, 2);
  }
  output.textContent = value;
  output.hidden = false;
}

export function showReportDialog() {
  if (!appState.report) return;
  byId("report-content").textContent = JSON.stringify(appState.report, null, 2);
  byId("report-dialog").showModal();
}
