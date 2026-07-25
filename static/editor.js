"use strict";

const editorState = {
  payload: null,
  highlights: [],
  activeId: null,
  roughCutUrl: null,
};

function editorById(id) {
  return document.getElementById(id);
}

function formatEditorTime(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0) return "00:00";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = Math.floor(seconds % 60);
  return hours
    ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function editorComment(highlight) {
  if (highlight.agent_comment_status === "ready" && highlight.agent_comment) {
    return highlight.agent_comment;
  }
  if (highlight.agent_comment_status === "unavailable") {
    return "Agent 评论不可用";
  }
  return "Agent 评论尚未生成";
}

function validateEditorPayload(payload) {
  if (!payload || payload.ok !== true || payload.contract_version !== "1.0") {
    throw new Error("剪辑预览数据契约版本不受支持。");
  }
  if (!payload.job || !payload.video || !Array.isArray(payload.highlights)) {
    throw new Error("剪辑预览数据缺少必要字段。");
  }
  const duration = Number(payload.video.duration);
  if (!Number.isFinite(duration) || duration < 0 || !payload.video.url) {
    throw new Error("剪辑预览数据中的视频信息无效。");
  }
  payload.highlights.forEach((highlight) => {
    const start = Number(highlight.start);
    const end = Number(highlight.end);
    if (
      !highlight.id
      || !Number.isFinite(start)
      || !Number.isFinite(end)
      || start < 0
      || start >= end
      || end > duration
    ) {
      throw new Error("剪辑预览数据中存在无效的精彩片段。");
    }
  });
  return payload;
}

async function fetchEditorPayload(jobId) {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/editor`);
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`服务返回了无法解析的响应（HTTP ${response.status}）。`);
  }
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `读取剪辑预览失败（HTTP ${response.status}）。`);
  }
  return validateEditorPayload(payload);
}

function setEditorControlsEnabled(enabled) {
  [
    "skip-back-button",
    "play-toggle-button",
    "skip-forward-button",
    "timeline-scrubber",
  ].forEach((id) => {
    editorById(id).disabled = !enabled;
  });
}

function createHighlightRow(highlight) {
  const row = document.createElement("tr");
  row.dataset.highlightId = highlight.id;
  const timeCell = document.createElement("td");
  const seekButton = document.createElement("button");
  seekButton.type = "button";
  seekButton.className = "highlight-seek-button";
  seekButton.dataset.highlightId = highlight.id;
  seekButton.setAttribute(
    "aria-label",
    `定位到精彩片段 ${formatEditorTime(highlight.start)} 至 ${formatEditorTime(highlight.end)}`,
  );
  const range = document.createElement("strong");
  range.textContent = `${formatEditorTime(highlight.start)} – ${formatEditorTime(highlight.end)}`;
  const duration = document.createElement("small");
  duration.textContent = `时长 ${formatEditorTime(highlight.duration)}`;
  seekButton.append(range, duration);
  timeCell.append(seekButton);

  const commentCell = document.createElement("td");
  const comment = document.createElement("p");
  comment.className = `agent-comment ${highlight.agent_comment_status}`;
  comment.textContent = editorComment(highlight);
  commentCell.append(comment);
  row.append(timeCell, commentCell);
  return row;
}

function createTimelineMarker(highlight, videoDuration) {
  const marker = document.createElement("button");
  marker.type = "button";
  marker.className = "timeline-highlight";
  marker.dataset.highlightId = highlight.id;
  marker.style.left = `${(highlight.start / videoDuration) * 100}%`;
  marker.style.width = `${((highlight.end - highlight.start) / videoDuration) * 100}%`;
  marker.setAttribute(
    "aria-label",
    `精彩片段 ${formatEditorTime(highlight.start)} 至 ${formatEditorTime(highlight.end)}`,
  );
  marker.title = `${formatEditorTime(highlight.start)} – ${formatEditorTime(highlight.end)}`;
  return marker;
}

function updateActiveHighlight(highlight, seek = false) {
  const video = editorById("editor-video");
  editorState.activeId = highlight?.id || null;
  document.querySelectorAll("[data-highlight-id]").forEach((element) => {
    const active = element.dataset.highlightId === editorState.activeId;
    if (active) {
      element.setAttribute("aria-current", "true");
    } else {
      element.removeAttribute("aria-current");
    }
  });
  if (!highlight) {
    editorById("active-highlight-time").textContent = "尚未选择";
    editorById("active-highlight-score").textContent = "—";
    editorById("active-highlight-comment").textContent = "从左侧列表或时间轴选择一个精彩片段。";
    return;
  }
  editorById("active-highlight-time").textContent =
    `${formatEditorTime(highlight.start)} – ${formatEditorTime(highlight.end)}`;
  editorById("active-highlight-score").textContent =
    Number.isFinite(Number(highlight.score))
      ? `${Math.round(Number(highlight.score) * 100)} / 100`
      : "—";
  editorById("active-highlight-comment").textContent = editorComment(highlight);
  if (seek) {
    video.currentTime = highlight.start;
    editorById("timeline-scrubber").value = String(highlight.start);
    updatePlaybackTime();
  }
}

function highlightAtTime(time) {
  return editorState.highlights.find(
    (highlight) => time >= highlight.start && time <= highlight.end,
  ) || null;
}

function updatePlaybackTime() {
  const video = editorById("editor-video");
  const duration = Number(editorState.payload?.video.duration || video.duration || 0);
  const current = Number(video.currentTime || 0);
  editorById("playback-time").textContent =
    `${formatEditorTime(current)} / ${formatEditorTime(duration)}`;
  editorById("timeline-scrubber").value = String(Math.min(current, duration));
  const active = highlightAtTime(current);
  if ((active?.id || null) !== editorState.activeId) {
    updateActiveHighlight(active);
  }
}

function renderEditor(payload) {
  editorState.payload = payload;
  editorState.highlights = [...payload.highlights].sort(
    (left, right) => Number(left.order) - Number(right.order),
  );
  editorState.roughCutUrl = payload.output?.rough_cut_url || null;
  const video = editorById("editor-video");
  const duration = Number(payload.video.duration);

  editorById("editor-project-name").textContent = payload.job.project_name || "未命名项目";
  editorById("editor-video-name").textContent = payload.video.filename || "";
  editorById("editor-job-status").className = "status-badge completed";
  editorById("editor-job-status").textContent = "分析完成";
  editorById("highlight-count").textContent = `共 ${editorState.highlights.length} 段`;
  editorById("timeline-description").textContent =
    editorState.highlights.length
      ? `已标记 ${editorState.highlights.length} 个精彩片段`
      : "当前没有精彩片段";
  editorById("timeline-end").textContent = formatEditorTime(duration);

  const list = editorById("highlight-list");
  const markerLayer = editorById("highlight-marker-layer");
  list.replaceChildren();
  markerLayer.replaceChildren();
  editorState.highlights.forEach((highlight) => {
    list.append(createHighlightRow(highlight));
    markerLayer.append(createTimelineMarker(highlight, duration));
  });
  editorById("highlight-list-state").textContent = editorState.highlights.length
    ? "选择任意片段可定位视频。"
    : "当前报告没有精彩片段。";

  const scrubber = editorById("timeline-scrubber");
  scrubber.max = String(duration);
  scrubber.value = "0";
  video.src = payload.video.url;
  video.load();
  setEditorControlsEnabled(true);

  const exportButton = editorById("editor-export-button");
  exportButton.disabled = !editorState.roughCutUrl;
  exportButton.title = editorState.roughCutUrl ? "打开已生成的粗剪视频" : "粗剪视频尚未生成";
  editorById("editor-main").setAttribute("aria-busy", "false");
}

function showEditorError(error) {
  editorById("editor-main").setAttribute("aria-busy", "false");
  editorById("video-state").hidden = true;
  editorById("editor-error").hidden = false;
  editorById("editor-error-message").textContent = error.message;
  editorById("highlight-list-state").textContent = "剪辑预览数据读取失败。";
  editorById("editor-job-status").className = "status-badge failed";
  editorById("editor-job-status").textContent = "加载失败";
  setEditorControlsEnabled(false);
}

function initEditorEvents() {
  const video = editorById("editor-video");
  editorById("highlight-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-highlight-id]");
    if (!button) return;
    const highlight = editorState.highlights.find(
      (item) => item.id === button.dataset.highlightId,
    );
    if (highlight) updateActiveHighlight(highlight, true);
  });
  editorById("highlight-marker-layer").addEventListener("click", (event) => {
    const button = event.target.closest("[data-highlight-id]");
    if (!button) return;
    const highlight = editorState.highlights.find(
      (item) => item.id === button.dataset.highlightId,
    );
    if (highlight) updateActiveHighlight(highlight, true);
  });
  editorById("timeline-scrubber").addEventListener("input", (event) => {
    video.currentTime = Number(event.currentTarget.value);
    updatePlaybackTime();
  });
  editorById("skip-back-button").addEventListener("click", () => {
    video.currentTime = Math.max(0, video.currentTime - 5);
  });
  editorById("skip-forward-button").addEventListener("click", () => {
    video.currentTime = Math.min(video.duration || 0, video.currentTime + 5);
  });
  editorById("play-toggle-button").addEventListener("click", async () => {
    if (video.paused) {
      try {
        await video.play();
      } catch {
        return;
      }
    } else {
      video.pause();
    }
  });
  editorById("editor-export-button").addEventListener("click", () => {
    if (editorState.roughCutUrl) {
      window.open(editorState.roughCutUrl, "_blank", "noopener");
    }
  });
  video.addEventListener("loadedmetadata", () => {
    editorById("video-state").hidden = true;
    updatePlaybackTime();
  });
  video.addEventListener("timeupdate", updatePlaybackTime);
  video.addEventListener("play", () => {
    editorById("play-toggle-button").setAttribute("aria-label", "暂停视频");
  });
  video.addEventListener("pause", () => {
    editorById("play-toggle-button").setAttribute("aria-label", "播放视频");
  });
  video.addEventListener("error", () => {
    editorById("video-state").hidden = false;
    editorById("video-state").querySelector("p").textContent = "视频加载失败，请返回工作台检查源文件。";
  });
}

async function initEditor() {
  const savedTheme = localStorage.getItem("reelfire-theme");
  if (["dark", "light", "ocean", "forest"].includes(savedTheme)) {
    document.body.dataset.theme = savedTheme;
  }
  initEditorEvents();
  const jobId = document.body.dataset.jobId;
  try {
    renderEditor(await fetchEditorPayload(jobId));
  } catch (error) {
    showEditorError(error);
  }
}

document.addEventListener("DOMContentLoaded", initEditor);
