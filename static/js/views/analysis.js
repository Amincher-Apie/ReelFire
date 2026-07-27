// ReelFire — analysis pipeline: submit, poll, render reports
import { appState, statusLabels } from "../state/app-state.js";
import api from "../api/client.js";
import { byId, clearChildren, createElement } from "../utils/dom.js";
import { formatNumber, formatDuration } from "../utils/format.js";
import { outputUrl } from "../utils/url.js";
import { showToast, setButtonLoading } from "../utils/ui.js";
import { renderWorkbenchCharts } from "./charts.js";
import { isSSESupported, connectSSE } from "../api/sse.js";
import { showTaskStages, hideTaskStages, simulateStageProgress, showProgressDetail, hideProgressDetail, updateProgressDetail, showEmptyResultGuide, hideEmptyResultGuide } from "./task-progress.js";

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

export function stopAgentPolling() {
  if (appState.agentPollTimer) window.clearTimeout(appState.agentPollTimer);
  appState.agentPollTimer = null;
}

export function updateAgentFlow(hasReport = false) {
  const nodes = [...document.querySelectorAll(".agent-node")];
  nodes.forEach((node) => node.classList.remove("complete", "blocked"));
  const badge = byId("agent-provider-badge");
  const note = byId("agent-run-note");
  if (!hasReport) {
    stopAgentPolling();
    appState.agentCallId = null;
    if (badge) badge.textContent = "等待 Agent";
    if (note) note.textContent =
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

export function renderAgentCall(call) {
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
    if (badge) badge.textContent = "Agent 排队中";
    if (note) note.textContent = "Agent 调用已创建，正在等待后台执行器。";
    nodes[2].querySelector("small").textContent = "调用已排队";
    nodes[3].querySelector("small").textContent = "等待 Agent 结果";
  } else if (status === "running") {
    if (badge) badge.textContent = provider;
    if (note) note.textContent = "Agent 正在执行报告解析、知识检索、建议生成和规则校验。";
    nodes[2].querySelector("small").textContent = "Agent 正在运行";
    nodes[3].querySelector("small").textContent = "等待 Agent 结果";
  } else if (status === "completed") {
    if (badge) badge.textContent = provider;
    if (note) note.textContent = "Agent 已完成，结果和工具轨迹已经保存。";
    nodes[2].classList.add("complete");
    nodes[2].querySelector("small").textContent = "Agent 结果已保存";
    nodes[3].classList.add("complete");
    nodes[3].querySelector("small").textContent = "可进入 Editor 复核";
  } else if (status === "needs_review") {
    const riskFlags = call.result?.risk_flags || [];
    const degraded = riskFlags.includes("model_generation_failed")
      || riskFlags.includes("model_provider_not_configured");
    if (badge) badge.textContent = degraded ? "规则降级结果" : provider;
    if (note) note.textContent = degraded
      ? "在线模型调用失败，系统已保留规则结果；请检查 Agent 调用详情和 Dify 配置。"
      : "Agent 已完成，但结果需要人工复核。";
    nodes[2].classList.add(degraded ? "blocked" : "complete");
    nodes[2].querySelector("small").textContent = degraded
      ? "在线模型失败，已规则降级"
      : "Agent 结果待复核";
    nodes[3].classList.add("complete");
    nodes[3].querySelector("small").textContent = "请进入 Editor 复核";
  } else {
    if (badge) badge.textContent = "Agent 失败";
    if (note) note.textContent = call.error_message || "Agent 执行失败，请检查服务配置。";
    nodes[2].classList.add("blocked");
    nodes[2].querySelector("small").textContent =
      call.error_code || "Agent 执行失败";
    nodes[3].classList.add("blocked");
    nodes[3].querySelector("small").textContent = "没有可复核的 Agent 结果";
  }
}

export async function pollAgentCall(jobId, callId) {
  stopAgentPolling();
  try {
    const payload = await api.get(
      `/api/agent-calls/${encodeURIComponent(callId)}`,
    );
    const call = payload.agent_call;
    renderAgentCall(call);
    if (call.status === "queued" || call.status === "running") {
      appState.agentPollTimer = window.setTimeout(
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
    const badge = byId("agent-provider-badge");
    const note = byId("agent-run-note");
    if (badge) badge.textContent = "Agent 状态异常";
    if (note) note.textContent = error.message;
  }
}

export async function ensureAgentRun(jobId) {
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
    appState.agentCallId = call.id;
    renderAgentCall(call);
    await pollAgentCall(jobId, call.id);
  } catch (error) {
    const badge = byId("agent-provider-badge");
    const note = byId("agent-run-note");
    if (badge) badge.textContent = "Agent 未启动";
    if (note) note.textContent = error.message;
  }
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

// ── chunk progress ────────────────────────────────────────────────────

export function renderAnalysisProgress(progress) {
  const value = progress && typeof progress === "object" ? progress : {};
  const total = Number(value.total_chunks) || 0;
  const completed = Number(value.completed_chunks) || 0;
  const percent = Math.max(0, Math.min(100, Number(value.percent) || 0));
  const chunks = Array.isArray(value.chunks) ? value.chunks : [];

  const panel = byId("analysis-progress-panel");
  if (panel) panel.hidden = false;
  const countEl = byId("analysis-progress-count");
  if (countEl) countEl.textContent = `${completed} / ${total}`;
  const percentEl = byId("analysis-progress-percent");
  if (percentEl) percentEl.textContent = `${Math.round(percent)}%`;
  const bar = byId("analysis-progress-bar");
  if (bar) { bar.value = percent; bar.textContent = `${Math.round(percent)}%`; }
  const detailEl = byId("analysis-progress-detail-text");
  if (detailEl) detailEl.textContent = value.message || "正在等待新的分块结果。";

  const track = byId("analysis-chunk-track");
  if (!track) return;
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
  const partialResults = byId("partial-results");
  if (partialResults) {
    partialResults.hidden =
      partialSegments.length === 0 && partialKeyframes.length === 0;
  }

  const segmentList = byId("partial-segment-list");
  if (segmentList) {
    clearChildren(segmentList);
    partialSegments.forEach((segment) => {
      const item = createElement("span", "partial-segment");
      item.textContent =
        `${formatDuration(segment.start)}–${formatDuration(segment.end)} 暂定`;
      segmentList.append(item);
    });
  }

  const keyframeList = byId("partial-keyframe-list");
  if (keyframeList) {
    clearChildren(keyframeList);
    partialKeyframes.forEach((frame) => {
      const image = document.createElement("img");
      image.src = outputUrl(appState.currentJobId, frame.image);
      image.alt =
        `已分析关键帧 ${frame.id}，时间 ${formatDuration(frame.timestamp)}`;
      image.loading = "lazy";
      image.width = 160;
      image.height = 90;
      keyframeList.append(image);
    });
  }
}

// ── keyframe grouping ────────────────────────────────────────────────

export function persistVisibleKeyframeReview() {
  document.querySelectorAll(".keyframe-card").forEach((card) => {
    const index = Number(card.dataset.frameIndex);
    const frame = appState.keyframes[index];
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

export function keyframeGroups() {
  if (appState.analysisChunks.length) {
    return appState.analysisChunks
      .map((chunk) => ({
        id: chunk.id,
        label: `${formatDuration(chunk.start)}–${formatDuration(chunk.end)}`,
        start: Number(chunk.start) || 0,
        end: Number(chunk.end) || 0,
        frames: appState.keyframes
          .map((frame, index) => ({ frame, index }))
          .filter(({ frame }) => frame.chunk_id === chunk.id),
      }))
      .filter((group) => group.frames.length > 0);
  }
  const grouped = new Map();
  appState.keyframes.forEach((frame, index) => {
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

export function renderActiveKeyframeGroup(groups) {
  const container = byId("keyframe-list");
  clearChildren(container);
  const active =
    groups.find((group) => group.id === appState.activeKeyframeChunkId) || groups[0];
  if (!active) {
    container.append(createElement("p", "empty-copy", "报告中没有关键帧。"));
    const summary = byId("keyframe-chunk-summary");
    if (summary) summary.textContent = "";
    return;
  }
  appState.activeKeyframeChunkId = active.id;
  const summary = byId("keyframe-chunk-summary");
  if (summary) summary.textContent =
    `当前时间段 ${active.label}，显示 ${active.frames.length} 张关键帧。`;

  const tabs = byId("keyframe-chunk-tabs");
  if (tabs) {
    tabs.querySelectorAll("[role='tab']").forEach((tab) => {
      const selected = tab.dataset.chunkId === active.id;
      tab.classList.toggle("active", selected);
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
  }

  active.frames.forEach(({ frame, index }) => {
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
    showEmptyResultGuide();
    return;
  }
  hideEmptyResultGuide();
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
  const tabs = byId("keyframe-chunk-tabs");
  if (tabs) clearChildren(tabs);
  if (!keyframes.length) {
    renderActiveKeyframeGroup([]);
    return;
  }
  const groups = keyframeGroups();
  if (!groups.some((group) => group.id === appState.activeKeyframeChunkId)) {
    appState.activeKeyframeChunkId = groups[0] ? groups[0].id : null;
  }
  if (tabs) {
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
        appState.activeKeyframeChunkId = group.id;
        renderActiveKeyframeGroup(groups);
      });
      tabs.append(button);
    });
  }
  renderActiveKeyframeGroup(groups);
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
  appState.analysisChunks = Array.isArray(report.analysis_chunks)
    ? report.analysis_chunks.map((item) => ({ ...item }))
    : [];
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
  updateJobNavigation(appState.currentJobId, true);
}

export async function loadReport(jobId) {
  logTool("GET", `/api/jobs/${jobId}/report`, "读取真实分析报告");
  const payload = await api.get(`/api/jobs/${encodeURIComponent(jobId)}/report`);
  renderReport(payload.report);
  await ensureAgentRun(jobId);
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

    // Update stage progress
    simulateStageProgress(job.status);

    // Update chunk-level progress
    if (job.progress) renderAnalysisProgress(job.progress);
    updateJobNavigation(
      jobId,
      job.status === "completed" ||
        Number(job.progress && job.progress.completed_chunks) > 0,
    );

    if (job.status === "completed") {
      logTool("GET", `/api/jobs/${jobId}`, "任务已完成");
      hideTaskStages();
      hideProgressDetail();
      byId("cancel-analysis-button").hidden = true;
      await loadReport(jobId);
      showToast("视频分析完成", "success");
      return;
    }
    if (job.status === "failed") {
      logTool("GET", `/api/jobs/${jobId}`, "任务失败");
      simulateStageProgress("failed");
      hideProgressDetail();
      byId("cancel-analysis-button").hidden = true;
      setResultState("error", "failed", job.error || "分析任务失败。");
      return;
    }

    // Update progress detail if available
    if (job.frames_processed != null) {
      updateProgressDetail(job.frames_processed, job.total_frames, job.percentage);
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
  showTaskStages();
  showProgressDetail();
  hideEmptyResultGuide();
  byId("cancel-analysis-button").hidden = false;
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
    hideTaskStages();
    hideProgressDetail();
    byId("cancel-analysis-button").hidden = true;
    // Special handling for archived project
    if (error.status === 409) {
      setResultState("error", "failed", "项目已归档，请恢复为 active 后再上传新任务。");
      showToast("项目已归档，请恢复为 active 后再上传新任务。", "error");
    } else {
      setResultState("error", "failed", error.message);
      showToast(error.message, "error");
    }
  }
}

// ── navigation ──────────────────────────────────────────────────────

export function updateJobNavigation(jobId, editorReady = false) {
  const analysisLink = byId("nav-analysis");
  const editorLink = byId("nav-editor");
  if (!jobId) return;
  if (analysisLink) {
    analysisLink.href = `/jobs/${encodeURIComponent(jobId)}/analysis`;
    analysisLink.classList.remove("disabled");
    analysisLink.removeAttribute("aria-disabled");
    analysisLink.removeAttribute("tabindex");
    analysisLink.removeAttribute("title");
  }
  if (editorLink) {
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
}

export async function hydrateAnalysisJob(jobId) {
  try {
    const payload = await api.get(`/api/jobs/${encodeURIComponent(jobId)}`);
    appState.currentJobId = jobId;
    appState.currentJob = payload.job;
    appState.toolCalls = [];
    renderToolCalls();
    updateJobNavigation(jobId, payload.job.status === "completed");
    if (payload.job.progress) renderAnalysisProgress(payload.job.progress);
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
