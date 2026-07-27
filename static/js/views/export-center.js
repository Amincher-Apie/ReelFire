// ReelFire — export center: config, progress, result display
import { editorState } from "../state/editor-state.js";
import api from "../api/client.js";
import { byId, clearChildren, createElement } from "../utils/dom.js";
import { formatTime, formatBytes, formatDuration, formatDate } from "../utils/format.js";
import { outputUrl } from "../utils/url.js";
import { showToast, setButtonLoading } from "../utils/ui.js";

const EXPORT_CONFIG_DEFAULTS = {
  mode: "collection",       // "single" | "collection"
  aspectRatio: "16:9",
  resolution: "original",
  keepAudio: true,
  filename: "",
};

let exportConfig = { ...EXPORT_CONFIG_DEFAULTS };
let exportPollTimer = null;

// ── dialog ──────────────────────────────────────────────────────────────

export function showExportDialog(options = {}) {
  const dialog = byId("export-dialog");
  if (!dialog) return;

  const requestedSegmentId = editorState.segments.some(
    (segment) => segment.id === options.segmentId,
  ) ? options.segmentId : null;
  exportConfig = {
    ...EXPORT_CONFIG_DEFAULTS,
    mode: options.mode === "single" ? "single" : "collection",
    segmentId: requestedSegmentId,
    filename: "reelfire_export_" + (editorState.jobId || "output").slice(0, 8),
  };
  if (exportConfig.mode === "single" && !exportConfig.segmentId) {
    exportConfig.segmentId = editorState.selectedSegmentId
      || editorState.segments[0]?.id
      || null;
  }

  byId("export-config-panel").hidden = false;
  byId("export-progress-panel").hidden = true;
  byId("export-result-panel").hidden = true;
  byId("export-single-results").hidden = true;
  byId("export-collection-result").hidden = true;
  renderExportConfig();
  dialog.showModal();
}

export function showSelectedSegmentExportDialog() {
  const segmentId = editorState.selectedSegmentId;
  if (!segmentId) {
    showToast("请先选择要导出的片段", "info");
    return;
  }
  showExportDialog({ mode: "single", segmentId });
}

export function closeExportDialog() {
  const dialog = byId("export-dialog");
  if (dialog) dialog.close();
  stopExportPolling();
}

// ── config rendering ────────────────────────────────────────────────────

function renderExportConfig() {
  // Mode selector
  document.querySelectorAll(".export-mode-option").forEach((btn) => {
    const active = btn.dataset.exportMode === exportConfig.mode;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", String(active));
  });

  // Segment list for single mode
  const singleSelector = byId("export-single-segment-selector");
  const collectionInfo = byId("export-collection-info");
  if (singleSelector) singleSelector.hidden = exportConfig.mode !== "single";
  if (collectionInfo) collectionInfo.hidden = exportConfig.mode !== "collection";

  if (exportConfig.mode === "single") {
    renderSingleSegmentSelector();
  } else {
    const adopted = editorState.segments.filter((s) => {
      const rev = editorState.reviews[s.id];
      return rev && rev.recommendation === "pass";
    });
    const count = adopted.length || editorState.segments.length;
    if (collectionInfo) {
      collectionInfo.textContent = `将导出 ${count} 个片段（按当前顺序合并）`;
    }
  }

  // Aspect ratio
  document.querySelectorAll(".export-ratio-option").forEach((btn) => {
    const active = btn.dataset.ratioValue === exportConfig.aspectRatio;
    btn.classList.toggle("active", active);
  });

  // Resolution
  const resSelect = byId("export-resolution");
  if (resSelect) resSelect.value = exportConfig.resolution;

  // Audio toggle
  const audioToggle = byId("export-audio-toggle");
  if (audioToggle) audioToggle.checked = exportConfig.keepAudio;

  // Filename
  const filenameInput = byId("export-filename");
  if (filenameInput) filenameInput.value = exportConfig.filename;
}

function renderSingleSegmentSelector() {
  const container = byId("export-single-segment-list");
  if (!container) return;
  clearChildren(container);

  editorState.segments.forEach((seg) => {
    const row = createElement("div", "export-segment-row");
    row.dataset.segmentId = seg.id;
    if (seg.id === exportConfig.segmentId) row.classList.add("selected");

    row.append(
      createElement("span", "", "片段 " + (seg.id || "")),
      createElement("span", "export-segment-time",
        formatTime(seg.start) + " – " + formatTime(seg.end)),
      createElement("span", "", formatDuration(seg.end - seg.start))
    );

    row.addEventListener("click", () => {
      exportConfig.segmentId = seg.id;
      renderExportConfig();
    });

    container.append(row);
  });
}

// ── mode switching ──────────────────────────────────────────────────────

export function setExportMode(mode) {
  exportConfig.mode = mode;
  exportConfig.segmentId = mode === "single"
    ? editorState.selectedSegmentId || editorState.segments[0]?.id || null
    : null;
  renderExportConfig();
}

export function setExportRatio(ratio) {
  exportConfig.aspectRatio = ratio;
  renderExportConfig();
}

export function updateExportConfig(changes) {
  Object.assign(exportConfig, changes);
}

// ── submit export ───────────────────────────────────────────────────────

export async function submitExport() {
  if (!editorState.jobId) return;

  const button = byId("export-submit-button");
  setButtonLoading(button, true, "启动导出…");

  const body = {
    mode: exportConfig.mode,
    aspect_ratio: exportConfig.aspectRatio,
    resolution: exportConfig.resolution,
    keep_audio: exportConfig.keepAudio,
    filename: exportConfig.filename || undefined,
  };

  if (exportConfig.mode === "single") {
    if (!exportConfig.segmentId) {
      // Default to selected segment
      if (editorState.selectedSegmentId) {
        exportConfig.segmentId = editorState.selectedSegmentId;
      } else if (editorState.segments.length > 0) {
        exportConfig.segmentId = editorState.segments[0].id;
      }
    }
    const seg = editorState.segments.find((s) => s.id === exportConfig.segmentId);
    if (!seg) {
      showToast("请选择要导出的片段", "error");
      setButtonLoading(button, false);
      return;
    }
    body.segments = [{ id: seg.id }];
  } else {
    // Collection: export adopted segments, or all if none adopted
    const adopted = editorState.segments.filter((s) => {
      const rev = editorState.reviews[s.id];
      return rev && rev.recommendation === "pass";
    });
    const targets = adopted.length > 0 ? adopted : editorState.segments;
    body.segments = targets.map((s) => ({ id: s.id }));
  }

  try {
    const resp = await api.post(
      "/api/jobs/" + encodeURIComponent(editorState.jobId) + "/export",
      body
    );

    setButtonLoading(button, false);

    if (resp.ok) {
      showExportProgress(resp);
    }
  } catch (err) {
    showToast(err.message || "导出失败", "error");
    setButtonLoading(button, false);
  }
}

// ── progress ────────────────────────────────────────────────────────────

function showExportProgress(resp) {
  const configPanel = byId("export-config-panel");
  const progressPanel = byId("export-progress-panel");
  const resultPanel = byId("export-result-panel");

  if (configPanel) configPanel.hidden = true;
  if (progressPanel) progressPanel.hidden = false;
  if (resultPanel) resultPanel.hidden = true;

  const progressFill = byId("export-progress-fill");
  const progressText = byId("export-progress-text");

  if (resp.exports && resp.mode === "single") {
    // Single export completed immediately (sync)
    if (progressFill) progressFill.style.width = "100%";
    if (progressText) progressText.textContent = "导出完成！";
    setTimeout(() => showExportResult(resp), 500);
  } else {
    // Collection export may be async
    if (progressFill) progressFill.style.width = "60%";
    if (progressText) progressText.textContent = "正在处理视频…";
    setTimeout(() => {
      if (progressFill) progressFill.style.width = "100%";
      if (progressText) progressText.textContent = "导出完成！";
      setTimeout(() => showExportResult(resp), 500);
    }, 2000);
  }
}

function showExportResult(resp) {
  const configPanel = byId("export-config-panel");
  const progressPanel = byId("export-progress-panel");
  const resultPanel = byId("export-result-panel");

  if (configPanel) configPanel.hidden = true;
  if (progressPanel) progressPanel.hidden = true;
  if (resultPanel) resultPanel.hidden = false;

  if (resp.exports && Array.isArray(resp.exports)) {
    // Single mode — multiple clips
    renderSingleExportResults(resp.exports);
  } else if (resp.export) {
    // Collection mode — one file
    renderCollectionExportResult(resp.export);
  }
}

function renderSingleExportResults(exports) {
  const container = byId("export-result-list");
  if (!container) return;
  clearChildren(container);

  exports.forEach((exp) => {
    const item = createElement("div", "export-result-item");
    const url = outputUrl(editorState.jobId, exp.output);

    item.innerHTML = `
      <div class="export-result-header">
        <strong>片段 ${exp.segment_id}</strong>
        <span>${formatTime(exp.start)} – ${formatTime(exp.end)}</span>
      </div>
      <video class="export-result-video" src="${url}" controls preload="metadata"
             aria-label="导出片段 ${exp.segment_id} 预览"></video>
      <a class="button primary small export-download-btn" href="${url}" download>
        下载片段
      </a>
    `;

    container.append(item);
  });

  byId("export-collection-result").hidden = true;
  byId("export-single-results").hidden = false;
}

function renderCollectionExportResult(exp) {
  byId("export-single-results").hidden = true;
  byId("export-collection-result").hidden = false;

  const url = outputUrl(editorState.jobId, exp.file);
  const videoEl = byId("export-result-video");
  if (videoEl) videoEl.src = url;

  byId("export-result-segments").textContent = String(exp.segment_count || 0);
  byId("export-result-duration").textContent = formatDuration(exp.total_duration || 0);

  const downloadBtn = byId("export-download-button");
  if (downloadBtn) downloadBtn.href = url;
}

// ── poll ────────────────────────────────────────────────────────────────

function stopExportPolling() {
  if (exportPollTimer) {
    clearTimeout(exportPollTimer);
    exportPollTimer = null;
  }
}

// ── init ────────────────────────────────────────────────────────────────

export function initExportCenter() {
  // Mode buttons
  document.querySelectorAll(".export-mode-option").forEach((btn) => {
    btn.addEventListener("click", () => setExportMode(btn.dataset.exportMode));
  });

  // Ratio buttons
  document.querySelectorAll(".export-ratio-option").forEach((btn) => {
    btn.addEventListener("click", () => setExportRatio(btn.dataset.ratioValue));
  });

  // Resolution select
  const resSelect = byId("export-resolution");
  if (resSelect) {
    resSelect.addEventListener("change", () => {
      updateExportConfig({ resolution: resSelect.value });
    });
  }

  // Audio toggle
  const audioToggle = byId("export-audio-toggle");
  if (audioToggle) {
    audioToggle.addEventListener("change", () => {
      updateExportConfig({ keepAudio: audioToggle.checked });
    });
  }

  // Filename input
  const filenameInput = byId("export-filename");
  if (filenameInput) {
    filenameInput.addEventListener("input", () => {
      updateExportConfig({ filename: filenameInput.value.trim() });
    });
  }

  // Submit
  const submitBtn = byId("export-submit-button");
  if (submitBtn) submitBtn.addEventListener("click", submitExport);

  // Close
  const closeBtn = byId("close-export-dialog");
  if (closeBtn) closeBtn.addEventListener("click", closeExportDialog);

  // Dialog backdrop click
  const dialog = byId("export-dialog");
  if (dialog) {
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog) closeExportDialog();
    });
  }

  // Back to config button
  const backBtn = byId("export-back-config");
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      byId("export-config-panel").hidden = false;
      byId("export-progress-panel").hidden = true;
      byId("export-result-panel").hidden = true;
      byId("export-single-results").hidden = true;
      byId("export-collection-result").hidden = true;
      renderExportConfig();
    });
  }

  // Close result button
  const closeResultBtn = byId("export-close-result");
  if (closeResultBtn) {
    closeResultBtn.addEventListener("click", closeExportDialog);
  }
}
