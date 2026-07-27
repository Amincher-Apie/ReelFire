// ReelFire — analysis pipeline: submit, poll, render reports
import { appState, statusLabels } from "../state/app-state.js";
import { setSelectedProject } from "../state/project-selection.js";
import api from "../api/client.js";
import { byId, clearChildren, createElement } from "../utils/dom.js";
import { formatNumber, formatDuration } from "../utils/format.js";
import { paginate, renderPagination } from "../utils/pagination.js";
import { outputUrl } from "../utils/url.js";
import { showToast, setButtonLoading } from "../utils/ui.js";
import {
  drawSegmentScoreChart,
  renderWorkbenchCharts,
} from "./charts.js";
import { showTaskStages, hideTaskStages, simulateStageProgress, showProgressDetail, hideProgressDetail, updateProgressDetail, showEmptyResultGuide, hideEmptyResultGuide } from "./task-progress.js";
import { showAppView } from "./navigation.js";

const AGENT_PROMPT_VERSION = "v2";
const analysisPagination = {
  segmentPage: 1,
  segmentPageSize: 5,
  keyframePage: 1,
  keyframePageSize: 5,
};
let selectedCandidateSegmentId = null;

// ── view switching ────────────────────────────────────────────────────

export function setView(view) {
  showAppView(view);
}

export function updateAnalysisContext(project = appState.currentProject, job = appState.currentJob) {
  const projectName = byId("analysis-project-name");
  const assetName = byId("analysis-asset-name");
  if (projectName) projectName.textContent = project?.name || job?.project_name || "未选择项目";
  if (assetName) {
    assetName.textContent = job
      ? job.original_asset_name || job.asset_name || "未命名素材"
      : "等待添加素材";
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
        { prompt_version: AGENT_PROMPT_VERSION, force: false },
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
  const screening = value.stage === "screening";
  const screeningTotal = Number(value.screening_total_chunks) || 0;
  const screeningCompleted = Number(value.screening_completed_chunks) || 0;
  const percent = Math.max(0, Math.min(100, Number(value.percent) || 0));
  const chunks = Array.isArray(value.chunks) ? value.chunks : [];

  const panel = byId("analysis-progress-panel");
  if (panel) panel.hidden = false;
  const countEl = byId("analysis-progress-count");
  if (countEl) {
    countEl.textContent = screening
      ? `已扫描 ${screeningCompleted} / ${screeningTotal}`
      : `${completed} / ${total} 个候选窗口`;
  }
  const percentEl = byId("analysis-progress-percent");
  if (percentEl) percentEl.textContent = `${Math.round(percent)}%`;
  const bar = byId("analysis-progress-bar");
  if (bar) { bar.value = percent; bar.textContent = `${Math.round(percent)}%`; }
  const detailEl = byId("analysis-progress-detail-text");
  if (detailEl) detailEl.textContent = value.message || "正在等待新的分块结果。";

  const track = byId("analysis-chunk-track");
  if (!track) return;
  clearChildren(track);
  if (screening) {
    const scanned = Number(value.screened_seconds) || 0;
    const videoDuration =
      Number(value.video_duration_seconds)
      || Number(value.video && value.video.duration)
      || 0;
    const item = createElement("span", "analysis-screening-status running");
    item.setAttribute("role", "listitem");
    item.textContent =
      `全片粗筛 ${formatDuration(scanned)} / ${formatDuration(videoDuration)}`;
    track.append(item);
  } else if (!total) {
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
  const indexedFrames = appState.keyframes.map((frame, index) => ({
    frame,
    index,
  }));

  const groups = [{
    id: "all",
    label: "全部关键帧",
    timeLabel: "完整报告",
    frames: indexedFrames,
  }];
  appState.segments.forEach((segment, segmentIndex) => {
    const segmentId = candidateSegmentId(segment, segmentIndex);
    const sourceIds = new Set(
      (segment.source_keyframes || []).map((value) => (
        String(value).replace(/\.(?:jpe?g|png|webp)$/i, "")
      )),
    );
    let frames = indexedFrames.filter(({ frame }) => (
      sourceIds.has(String(frame.id || "").replace(/\.(?:jpe?g|png|webp)$/i, ""))
    ));
    if (!frames.length) {
      const start = Number(segment.start) || 0;
      const end = Number(segment.end) || start;
      frames = indexedFrames.filter(({ frame }) => {
        const timestamp = Number(frame.timestamp) || 0;
        return timestamp >= start && timestamp <= end;
      });
    }
    groups.push({
      id: `segment:${segmentId}`,
      segmentId,
      label: `片段 ${String(segmentIndex + 1).padStart(2, "0")}`,
      timeLabel: `${formatDuration(segment.start)}–${formatDuration(segment.end)}`,
      frames,
    });
  });
  return groups;
}

function normalizedKeyframeReviewMode(mode) {
  return mode === "all" ? "all" : "segment";
}

function candidateSegmentId(segment, index) {
  const explicitId = String(segment?.id ?? "").trim();
  return explicitId || `index:${index}`;
}

function selectedSegmentGroup(groups) {
  return (
    groups.find((group) => group.segmentId === selectedCandidateSegmentId)
    || groups.find((group) => Boolean(group.segmentId))
    || groups.find((group) => group.id === "all")
    || null
  );
}

function activeKeyframeGroup(groups) {
  if (normalizedKeyframeReviewMode(appState.keyframeReviewMode) === "all") {
    return groups.find((group) => group.id === "all") || groups[0] || null;
  }
  return selectedSegmentGroup(groups);
}

function renderKeyframeReviewMode(active) {
  const mode = normalizedKeyframeReviewMode(appState.keyframeReviewMode);
  document.querySelectorAll("[data-keyframe-review-mode]").forEach((button) => {
    const selected = button.dataset.keyframeReviewMode === mode;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });

  const context = byId("keyframe-review-context");
  const detail = byId("keyframe-review-context-detail");
  if (mode === "all") {
    if (context) context.textContent = "全部关键帧";
    if (detail) {
      detail.textContent = "候选片段选择不会改变下方审核范围";
    }
    return;
  }
  if (context) context.textContent = active?.label || "当前片段";
  if (detail) {
    detail.textContent = active?.segmentId
      ? `${active.timeLabel || "未标注时间"} · ${active.frames.length} 张关联关键帧`
      : "选择上方候选片段，下方将显示对应关键帧";
  }
}

export function setKeyframeReviewMode(mode) {
  const nextMode = normalizedKeyframeReviewMode(mode);
  if (nextMode === normalizedKeyframeReviewMode(appState.keyframeReviewMode)) {
    return;
  }
  persistVisibleKeyframeReview();
  appState.keyframeReviewMode = nextMode;
  analysisPagination.keyframePage = 1;
  const groups = keyframeGroups();
  const active = activeKeyframeGroup(groups);
  appState.activeKeyframeChunkId = active?.id || null;
  if (
    nextMode === "segment"
    && active?.segmentId
    && active.segmentId !== selectedCandidateSegmentId
  ) {
    selectedCandidateSegmentId = active.segmentId;
    renderSegments(appState.segments);
  }
  renderKeyframes(appState.keyframes);
}

export function renderActiveKeyframeGroup(groups) {
  const container = byId("keyframe-list");
  clearChildren(container);
  const active = activeKeyframeGroup(groups);
  renderKeyframeReviewMode(active);
  if (!active) {
    container.append(createElement("p", "empty-copy", "报告中没有关键帧。"));
    const summary = byId("keyframe-chunk-summary");
    if (summary) summary.textContent = "";
    return;
  }
  appState.activeKeyframeChunkId = active.id;
  const framePage = paginate(
    active.frames,
    analysisPagination.keyframePage,
    analysisPagination.keyframePageSize,
  );
  analysisPagination.keyframePage = framePage.page;
  const summary = byId("keyframe-chunk-summary");
  if (summary) {
    summary.textContent = framePage.total
      ? `${active.label} · ${active.timeLabel || ""}，显示 ${framePage.startIndex + 1}-${framePage.endIndex} / ${framePage.total} 张关键帧。`
      : `${active.label} · ${active.timeLabel || ""}，暂无关联关键帧。`;
  }

  const tabs = byId("keyframe-chunk-tabs");
  if (tabs) {
    tabs.querySelectorAll("[role='tab']").forEach((tab) => {
      const selected = tab.dataset.chunkId === active.id;
      tab.classList.toggle("active", selected);
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
  }

  if (!framePage.total) {
    container.append(
      createElement(
        "p",
        "empty-copy",
        normalizedKeyframeReviewMode(appState.keyframeReviewMode) === "all"
          ? "报告中没有关键帧。"
          : "当前片段没有关联关键帧，可切换到“全部关键帧”继续审核。",
      ),
    );
  }
  framePage.items.forEach(({ frame, index }) => {
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
  renderPagination(byId("keyframe-pagination"), {
    total: framePage.total,
    page: framePage.page,
    pageSize: framePage.pageSize,
    itemLabel: "张关键帧",
    ariaLabel: "关键帧审核分页",
    onPageChange: (page) => {
      persistVisibleKeyframeReview();
      analysisPagination.keyframePage = page;
      renderActiveKeyframeGroup(groups);
    },
    onPageSizeChange: (pageSize) => {
      persistVisibleKeyframeReview();
      analysisPagination.keyframePageSize = pageSize;
      analysisPagination.keyframePage = 1;
      renderActiveKeyframeGroup(groups);
    },
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
  const segmentPage = paginate(
    segments,
    analysisPagination.segmentPage,
    analysisPagination.segmentPageSize,
  );
  analysisPagination.segmentPage = segmentPage.page;
  const chartsCard = byId("workbench-charts-card");
  if (chartsCard && !chartsCard.hidden) {
    drawSegmentScoreChart(segmentPage.items, segmentPage.startIndex);
  }
  segmentPage.items.forEach((segment, localIndex) => {
    const index = segmentPage.startIndex + localIndex;
    const segmentId = candidateSegmentId(segment, index);
    const item = createElement(
      "button",
      `segment-item${segmentId === selectedCandidateSegmentId ? " selected" : ""}`,
    );
    item.type = "button";
    item.setAttribute(
      "aria-pressed",
      String(segmentId === selectedCandidateSegmentId),
    );
    item.setAttribute(
      "aria-label",
      `选择候选片段 ${index + 1}，查看关联关键帧`,
    );
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
    item.addEventListener("click", () => {
      persistVisibleKeyframeReview();
      selectedCandidateSegmentId = segmentId;
      if (normalizedKeyframeReviewMode(appState.keyframeReviewMode) === "segment") {
        const groups = keyframeGroups();
        const group = groups.find(
          (candidate) => candidate.segmentId === segmentId,
        );
        appState.activeKeyframeChunkId = group?.id || null;
        analysisPagination.keyframePage = 1;
      }
      renderSegments(appState.segments);
      if (normalizedKeyframeReviewMode(appState.keyframeReviewMode) === "segment") {
        renderKeyframes(appState.keyframes);
      }
    });
    container.append(item);
  });
  renderPagination(byId("segment-pagination"), {
    total: segmentPage.total,
    page: segmentPage.page,
    pageSize: segmentPage.pageSize,
    itemLabel: "个片段",
    ariaLabel: "候选片段分页",
    onPageChange: (page) => {
      analysisPagination.segmentPage = page;
      renderSegments(segments);
    },
    onPageSizeChange: (pageSize) => {
      analysisPagination.segmentPageSize = pageSize;
      analysisPagination.segmentPage = 1;
      renderSegments(segments);
    },
  });
}

export function renderKeyframes(keyframes) {
  const tabs = byId("keyframe-chunk-tabs");
  if (tabs) {
    clearChildren(tabs);
    tabs.hidden = true;
  }
  const groups = keyframeGroups();
  const groupPagination = byId("keyframe-group-pagination");
  if (groupPagination) {
    clearChildren(groupPagination);
    groupPagination.hidden = true;
  }
  const active = activeKeyframeGroup(groups);
  appState.activeKeyframeChunkId = active?.id || null;
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
  analysisPagination.segmentPage = 1;
  analysisPagination.keyframePage = 1;
  if (!appState.segments.some((segment, index) => (
    candidateSegmentId(segment, index) === selectedCandidateSegmentId
  ))) {
    selectedCandidateSegmentId = appState.segments.length
      ? candidateSegmentId(appState.segments[0], 0)
      : null;
  }
  appState.keyframeReviewMode = normalizedKeyframeReviewMode(
    appState.keyframeReviewMode,
  );
  appState.activeKeyframeChunkId =
    appState.keyframeReviewMode === "all"
      ? "all"
      : selectedCandidateSegmentId
        ? `segment:${selectedCandidateSegmentId}`
        : "all";
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

  const visibleSegmentPage = paginate(
    appState.segments,
    analysisPagination.segmentPage,
    analysisPagination.segmentPageSize,
  );
  renderWorkbenchCharts(
    report,
    visibleSegmentPage.items,
    visibleSegmentPage.startIndex,
  );
  updateJobNavigation(appState.currentJobId, true);
}

export async function loadReport(jobId) {
  logTool("GET", `/api/jobs/${jobId}/report`, "读取真实分析报告");
  const payload = await api.get(`/api/jobs/${encodeURIComponent(jobId)}/report`);
  renderReport(payload.report);
  await ensureAgentRun(jobId);
}

// ── polling ───────────────────────────────────────────────────────────

function updateEditorEntry(jobId, ready) {
  const editorLink = byId("editor-link");
  if (!editorLink) return;
  editorLink.href = `/jobs/${encodeURIComponent(jobId)}/editor`;
  editorLink.hidden = !ready;
}

export function stopPolling() {
  if (appState.pollTimer) window.clearTimeout(appState.pollTimer);
  appState.pollTimer = null;
}

export function prepareActiveAnalysis(job) {
  const progress = job?.progress || {};
  showTaskStages();
  showProgressDetail();
  hideEmptyResultGuide();
  simulateStageProgress(job?.status || "queued", progress.stage);
  if (job?.progress) renderAnalysisProgress(job.progress);
  byId("cancel-analysis-button").hidden = false;
}

export async function pollJob(jobId) {
  stopPolling();
  try {
    const payload = await api.get(`/api/jobs/${encodeURIComponent(jobId)}`);
    const job = payload.job;
    const progress = job.progress || {};
    appState.currentJob = job;

    // Update stage progress
    simulateStageProgress(job.status, progress.stage);

    // Update chunk-level progress
    if (job.progress) renderAnalysisProgress(job.progress);
    updateJobNavigation(
      jobId,
      job.status === "completed" ||
        Number(job.progress && job.progress.completed_chunks) > 0,
    );
    updateEditorEntry(
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
    if (progress.processed_frames != null) {
      updateProgressDetail(
        progress.processed_frames,
        progress.total_frames,
        progress.percent,
        progress.eta_seconds ?? progress.stage_eta_seconds,
        progress.elapsed_seconds,
        progress.stage,
        progress.provisional_segment_count ?? (progress.chunks || [])
          .reduce(
            (count, chunk) =>
              count + (chunk.provisional_segments || []).length,
            0,
          ),
      );
    }

    const message =
      progress.message ||
      (job.status === "running"
        ? "正在进行视频粗筛、目标检测与片段评分…"
        : "任务已创建，正在等待分析线程…");
    setResultState("loading", job.status || "queued", message);
    appState.pollTimer = window.setTimeout(() => pollJob(jobId), 1600);
  } catch (error) {
    setResultState("error", "failed", error.message);
  }
}

// SSE-backed watch (falls back to polling)
export function watchJob(jobId) {
  return pollJob(jobId);
}

// ── project & submission ──────────────────────────────────────────────

export async function resolveProject(projectName, gameType, requestedProjectId = null) {
  if (requestedProjectId) {
    if (
      appState.currentProject
      && String(appState.currentProject.id) === String(requestedProjectId)
    ) {
      return appState.currentProject;
    }
    const payload = await api.get(
      `/api/projects/${encodeURIComponent(requestedProjectId)}`,
    );
    return payload.project || null;
  }

  try {
    const payload = await api.post("/api/projects", {
      name: projectName,
      game_type: gameType,
    });
    if (payload.project && payload.project.id) {
      return payload.project;
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
  const requestedProjectId = byId("analysis-project-id").value || null;
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
  let project;
  try {
    project = await resolveProject(projectName, gameType, requestedProjectId);
  } catch (error) {
    setButtonLoading(button, false);
    showToast(`项目读取失败：${error.message}`, "error");
    return;
  }
  if (!project) {
    setButtonLoading(button, false);
    return;
  }

  const form = new FormData();
  form.append("file", file, file.name);
  form.append("project_id", String(project.id));
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
    setSelectedProject(project);
    appState.currentJob = {
      job_id: created.job_id,
      project_id: project.id,
      project_name: project.name,
      original_asset_name: file.name,
      game_type: gameType,
      status: created.status,
    };
    updateAnalysisContext(project, appState.currentJob);
    byId("project-dialog").close();
    showAppView("analysis");
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
    if (analysisLink.tagName === "A") {
      analysisLink.href = `/jobs/${encodeURIComponent(jobId)}/analysis`;
    } else {
      analysisLink.dataset.jobId = jobId;
    }
    analysisLink.classList.remove("disabled");
    analysisLink.removeAttribute("aria-disabled");
    analysisLink.removeAttribute("tabindex");
    analysisLink.removeAttribute("title");
  }
  if (editorLink) {
    if (editorLink.tagName === "A") {
      editorLink.href = `/jobs/${encodeURIComponent(jobId)}/editor`;
    } else {
      editorLink.dataset.jobId = jobId;
    }
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
      prepareActiveAnalysis(payload.job);
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
