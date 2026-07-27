// ReelFire — enhanced task progress display
import { byId } from "../utils/dom.js";
import { formatTime } from "../utils/format.js";

const STAGES = [
  { key: "upload", label: "上传视频", order: 0 },
  { key: "initialize", label: "读取视频与加载模型", order: 1 },
  { key: "screening", label: "全片快速筛选", order: 2 },
  { key: "detect", label: "窗口 YOLO 与目标追踪", order: 3 },
  { key: "finalize", label: "片段归并与报告生成", order: 4 },
];

const STAGE_LABELS = {
  queued: "等待分析线程",
  initializing: "初始化",
  screening: "快速筛选",
  sampling: "候选窗口排队",
  detecting: "YOLO 识别",
  tracking: "候选片段目标跟踪",
  finalizing: "生成报告",
  completed: "分析完成",
  failed: "分析失败",
};

// ── stage rendering ─────────────────────────────────────────────────────

export function showTaskStages() {
  const el = byId("task-stages");
  if (el) el.hidden = false;
  STAGES.forEach((stage) => updateStageStatus(stage.key, "waiting"));
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
export function simulateStageProgress(jobStatus, progressStage = null) {
  const completeThrough = (stageKey) => {
    const target = STAGES.find((stage) => stage.key === stageKey);
    if (!target) return;
    STAGES.forEach((stage) => {
      if (stage.order < target.order) updateStageStatus(stage.key, "completed");
    });
  };

  if (jobStatus === "queued") {
    updateStageStatus("upload", "completed");
  } else if (jobStatus === "running") {
    updateStageStatus("upload", "completed");
    if (progressStage === "initializing") {
      completeThrough("initialize");
      updateStageStatus("initialize", "running");
    } else if (progressStage === "screening") {
      completeThrough("screening");
      updateStageStatus("screening", "running");
    } else if (progressStage === "sampling") {
      completeThrough("detect");
      updateStageStatus("detect", "waiting");
    } else if (progressStage === "detecting") {
      completeThrough("detect");
      updateStageStatus("detect", "running");
    } else if (progressStage === "tracking") {
      completeThrough("detect");
      updateStageStatus("detect", "running");
    } else if (progressStage === "finalizing") {
      completeThrough("finalize");
      updateStageStatus("finalize", "running");
    } else {
      updateStageStatus("initialize", "running");
    }
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

export function updateProgressDetail(
  framesProcessed,
  totalFrames,
  percentage,
  etaSeconds = null,
  elapsedSeconds = null,
  stage = null,
  provisionalCount = 0,
) {
  const framesEl = byId("progress-frames");
  const stageEl = byId("progress-stage");
  const provisionalEl = byId("progress-provisional");
  const elapsedEl = byId("progress-elapsed");

  if (framesEl) {
    framesEl.textContent = framesProcessed != null
      ? `${framesProcessed} / ${totalFrames || "—"}`
      : "—";
  }
  if (stageEl) stageEl.textContent = STAGE_LABELS[stage] || "处理中";
  if (provisionalEl) provisionalEl.textContent = String(provisionalCount || 0);
  if (elapsedEl) {
    const localElapsed = progressStartTime
      ? Math.round((Date.now() - progressStartTime) / 1000)
      : 0;
    const elapsed = Number.isFinite(Number(elapsedSeconds))
      ? Number(elapsedSeconds)
      : localElapsed;
    const elapsedText = formatTime(elapsed);
    if (etaSeconds != null && Number(etaSeconds) >= 0) {
      elapsedEl.textContent = `${elapsedText} / 约 ${formatTime(etaSeconds)}`;
    } else {
      elapsedEl.textContent = `${elapsedText} / 计算中`;
    }
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
