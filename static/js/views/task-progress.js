// ReelFire — enhanced task progress display
import { byId } from "../utils/dom.js";
import { formatTime } from "../utils/format.js";

const STAGES = [
  { key: "upload", label: "上传视频", order: 0 },
  { key: "preprocess", label: "视频预处理", order: 1 },
  { key: "keyframe", label: "关键帧提取", order: 2 },
  { key: "detect", label: "YOLO 目标识别", order: 3 },
  { key: "highlight", label: "高光片段生成", order: 4 },
  { key: "proxy", label: "代理视频生成", order: 5 },
];

// ── stage rendering ─────────────────────────────────────────────────────

export function showTaskStages() {
  const el = byId("task-stages");
  if (el) el.hidden = false;
  updateStageStatus("upload", "completed");
}

export function hideTaskStages() {
  const el = byId("task-stages");
  if (el) el.hidden = true;
}

export function updateStageStatus(stageKey, status) {
  const stage = document.querySelector(`.task-stage[data-stage="${stageKey}"]`);
  if (!stage) return;
  stage.classList.remove("completed", "running", "failed");
  stage.classList.add(status);

  const icon = stage.querySelector(".task-stage-icon");
  if (icon) {
    if (status === "completed") icon.textContent = "✓";
    else if (status === "running") icon.textContent = "⟳";
    else if (status === "failed") icon.textContent = "✗";
    else icon.textContent = "";
  }

  const statusEl = byId("stage-status-" + stageKey);
  if (statusEl) {
    if (status === "completed") statusEl.textContent = "已完成";
    else if (status === "running") statusEl.textContent = "进行中";
    else if (status === "failed") statusEl.textContent = "失败";
    else statusEl.textContent = "等待中";
  }
}

// Simulate stage progression based on job status
export function simulateStageProgress(jobStatus) {
  if (jobStatus === "queued") {
    updateStageStatus("upload", "completed");
  } else if (jobStatus === "running") {
    updateStageStatus("upload", "completed");
    updateStageStatus("preprocess", "completed");
    updateStageStatus("keyframe", "completed");
    updateStageStatus("detect", "running");
  } else if (jobStatus === "completed") {
    STAGES.forEach((s) => updateStageStatus(s.key, "completed"));
  } else if (jobStatus === "failed") {
    // Find last running stage and mark as failed
    const running = document.querySelector(".task-stage.running");
    if (running) {
      updateStageStatus(running.dataset.stage, "failed");
    }
  }
}

// ── progress detail ─────────────────────────────────────────────────────

let progressStartTime = null;

export function showProgressDetail() {
  const el = byId("analysis-progress-detail");
  if (el) el.hidden = false;
  progressStartTime = Date.now();
}

export function hideProgressDetail() {
  const el = byId("analysis-progress-detail");
  if (el) el.hidden = true;
  progressStartTime = null;
}

export function updateProgressDetail(framesProcessed, totalFrames, percentage) {
  const framesEl = byId("progress-frames");
  const percentEl = byId("progress-percent");
  const elapsedEl = byId("progress-elapsed");

  if (framesEl) {
    framesEl.textContent = framesProcessed != null
      ? `${framesProcessed} / ${totalFrames || "—"}`
      : "—";
  }
  if (percentEl) {
    percentEl.textContent = percentage != null
      ? `${Math.round(percentage)}%`
      : "—";
  }
  if (elapsedEl && progressStartTime) {
    const elapsed = Math.round((Date.now() - progressStartTime) / 1000);
    const mins = Math.floor(elapsed / 60);
    const secs = elapsed % 60;
    elapsedEl.textContent = `${mins}分${secs}秒`;
  }
}

// ── empty result guidance ───────────────────────────────────────────────

export function showEmptyResultGuide() {
  const guide = byId("empty-result-guide");
  if (guide) guide.hidden = false;
}

export function hideEmptyResultGuide() {
  const guide = byId("empty-result-guide");
  if (guide) guide.hidden = true;
}

// ── upload progress ─────────────────────────────────────────────────────

export function showUploadProgress() {
  const bar = byId("upload-progress-bar");
  if (bar) bar.hidden = false;
}

export function hideUploadProgress() {
  const bar = byId("upload-progress-bar");
  if (bar) bar.hidden = true;
}

export function setUploadProgress(percent) {
  const fill = byId("upload-progress-fill");
  if (fill) fill.style.width = Math.min(100, Math.max(0, percent)) + "%";
}
