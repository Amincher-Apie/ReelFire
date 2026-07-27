// ReelFire — segment operations: add, delete, merge, split, playhead markers
//
// ⚠ 后端依赖说明：
// 以下 CRUD 端点（/segments、/segments/<id>、/segments/merge、/segments/<id>/split）
// 是否在新后端中保留需由最新 backend 分支确认。
// 正式的片段写回路径为 PATCH /api/jobs/<job_id>/review（完整 Segment Schema 快照）。
// 若独立 CRUD 端点被移除，对应 UI 按钮仍会显示但操作将返回错误提示。
import { editorState } from "../state/editor-state.js";
import api from "../api/client.js";
import { byId, createElement } from "../utils/dom.js";
import { showToast } from "../utils/ui.js";
import { renderSegmentList, selectSegment, loadEditorData } from "./editor-segments.js";
import { renderTimeline } from "./editor-video.js";
import { markDirty, pushUndo } from "./editor-review.js";
import { renderStatsDashboard } from "./editor-stats.js";

// ── manual add segment ──────────────────────────────────────────────────

export function showAddSegmentDialog() {
  const dialog = byId("add-segment-dialog");
  if (!dialog) return;

  // Pre-fill with current playhead position
  const currentTime = editorState.videoElement
    ? editorState.videoElement.currentTime
    : 0;
  const startInput = byId("new-segment-start");
  const endInput = byId("new-segment-end");
  if (startInput) startInput.value = currentTime.toFixed(1);
  if (endInput) endInput.value = Math.min(
    currentTime + 15,
    editorState.video ? editorState.video.duration : Infinity
  ).toFixed(1);

  dialog.showModal();
}

export async function addManualSegment(start, end) {
  if (!editorState.jobId) return;
  try {
    const resp = await api.post(
      "/api/jobs/" + encodeURIComponent(editorState.jobId) + "/segments",
      { start, end }
    );
    if (resp.segment) {
      showToast("手动片段已添加", "success");
      byId("add-segment-dialog").close();
      await loadEditorData(editorState.jobId);
    }
  } catch (err) {
    showToast(err.message || "添加片段失败", "error");
  }
}

// ── delete segment ──────────────────────────────────────────────────────

export async function deleteSegment(segId) {
  if (!editorState.jobId) return;
  try {
    await api.delete(
      "/api/jobs/" + encodeURIComponent(editorState.jobId) + "/segments/" + encodeURIComponent(segId)
    );
    pushUndo();
    showToast("片段已删除", "success");
    await loadEditorData(editorState.jobId);
  } catch (err) {
    showToast(err.message || "删除片段失败", "error");
  }
}

// ── set playhead as boundary ────────────────────────────────────────────

export function setPlayheadAsStart() {
  if (!editorState.selectedSegmentId || !editorState.videoElement) return;
  const time = editorState.videoElement.currentTime;
  const seg = editorState.segments.find((s) => s.id === editorState.selectedSegmentId);
  if (!seg) return;
  if (time >= seg.end) {
    showToast("起始时间必须小于结束时间", "error");
    return;
  }
  pushUndo();
  seg.start = time;
  markDirty();
  renderTimeline();
  renderSegmentList();
  renderStatsDashboard();

  // Update the boundary input
  const startInput = document.querySelector(".boundary-start");
  if (startInput) startInput.value = time.toFixed(1);
}

export function setPlayheadAsEnd() {
  if (!editorState.selectedSegmentId || !editorState.videoElement) return;
  const time = editorState.videoElement.currentTime;
  const seg = editorState.segments.find((s) => s.id === editorState.selectedSegmentId);
  if (!seg) return;
  if (time <= seg.start) {
    showToast("结束时间必须大于起始时间", "error");
    return;
  }
  pushUndo();
  seg.end = time;
  markDirty();
  renderTimeline();
  renderSegmentList();
  renderStatsDashboard();

  // Update the boundary input
  const endInput = document.querySelector(".boundary-end");
  if (endInput) endInput.value = time.toFixed(1);
}

// ── merge segments ──────────────────────────────────────────────────────

export async function mergeSelectedSegments() {
  if (!editorState.jobId) return;

  // Find two adjacent segments to merge — prefer selected + next
  const idx = editorState.segments.findIndex((s) => s.id === editorState.selectedSegmentId);
  if (idx < 0) {
    showToast("请先选择一个片段作为合并起点", "info");
    return;
  }
  const seg1 = editorState.segments[idx];
  const seg2 = editorState.segments[idx + 1];
  if (!seg2) {
    showToast("该片段后面没有相邻片段可以合并", "info");
    return;
  }

  const label = `合并 "${seg1.id}" 和 "${seg2.id}"？`;
  if (!window.confirm(label)) return;

  try {
    pushUndo();
    const resp = await api.post(
      "/api/jobs/" + encodeURIComponent(editorState.jobId) + "/segments/merge",
      { seg_id_1: seg1.id, seg_id_2: seg2.id }
    );
    if (resp.segment) {
      showToast("片段已合并", "success");
      await loadEditorData(editorState.jobId);
    }
  } catch (err) {
    showToast(err.message || "合并失败", "error");
  }
}

// ── split segment ───────────────────────────────────────────────────────

export function showSplitDialog() {
  if (!editorState.selectedSegmentId) return;
  const seg = editorState.segments.find((s) => s.id === editorState.selectedSegmentId);
  if (!seg) return;

  const midPoint = (seg.start + seg.end) / 2;
  const splitTime = window.prompt(
    `在片段 "${seg.id}"（${seg.start.toFixed(1)}s – ${seg.end.toFixed(1)}s）中输入拆分时间点：`,
    midPoint.toFixed(1)
  );
  if (!splitTime) return;

  const time = parseFloat(splitTime);
  if (isNaN(time) || time <= seg.start || time >= seg.end) {
    showToast("拆分时间必须在片段的起止时间之间", "error");
    return;
  }
  splitSegment(seg.id, time);
}

export async function splitSegment(segId, splitTime) {
  if (!editorState.jobId) return;
  try {
    pushUndo();
    const resp = await api.post(
      "/api/jobs/" + encodeURIComponent(editorState.jobId) +
      "/segments/" + encodeURIComponent(segId) + "/split",
      { split_time: splitTime }
    );
    if (resp.segments) {
      showToast("片段已拆分", "success");
      await loadEditorData(editorState.jobId);
    }
  } catch (err) {
    showToast(err.message || "拆分失败", "error");
  }
}

// ── segment playback ────────────────────────────────────────────────────

let _activePlaybackListener = null;

function _clearPlaybackListener(video) {
  if (_activePlaybackListener && video) {
    video.removeEventListener("timeupdate", _activePlaybackListener);
    _activePlaybackListener = null;
  }
}

export function playSegment(segId) {
  const seg = editorState.segments.find((s) => s.id === segId);
  if (!seg || !editorState.videoElement) return;

  const video = editorState.videoElement;

  // Remove any previous playback listener
  _clearPlaybackListener(video);

  video.currentTime = seg.start;
  selectSegment(segId);

  video.play().catch(() => { /* autoplay blocked — user must click play */ });

  // Pause at segment end
  const onTimeUpdate = () => {
    if (video.currentTime >= seg.end) {
      video.pause();
      _clearPlaybackListener(video);
    }
  };
  _activePlaybackListener = onTimeUpdate;
  video.addEventListener("timeupdate", onTimeUpdate);
}

// ── adopt / ignore ──────────────────────────────────────────────────────

export function adoptSegment(segId) {
  const { setReviewStatus } = requireEditorReview();
  setReviewStatus(segId, "pass");
  showToast("已采用该片段", "success");
}

export function ignoreSegment(segId) {
  const { setReviewStatus } = requireEditorReview();
  setReviewStatus(segId, "reject");
  showToast("已忽略该片段", "info");
}

function requireEditorReview() {
  // Dynamic import to avoid circular deps
  let reviewModule = null;
  import("./editor-review.js").then((m) => { reviewModule = m; });
  return {
    setReviewStatus(segId, value) {
      // Use the already-imported module from editor-review.js
      // We inline the logic here to avoid circular import issues
      if (!editorState.reviews[segId]) {
        editorState.reviews[segId] = { recommendation: "", note: "" };
      }
      editorState.reviews[segId].recommendation = value;
      markDirty();
      renderSegmentList();
      renderStatsDashboard();
    },
  };
}

// ── drag reorder ────────────────────────────────────────────────────────

export function initDragReorder(container, pageStartIndex = 0) {
  if (!container) return;

  container.ondragstart = (e) => {
    const card = e.target.closest(".segment-card");
    if (!card) return;
    card.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", card.dataset.segmentId || "");
  };

  container.ondragover = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const card = e.target.closest(".segment-card");
    if (!card) return;
    const dragging = container.querySelector(".segment-card.dragging");
    if (!dragging || dragging === card) return;

    const children = Array.from(container.children);
    const dragIdx = children.indexOf(dragging);
    const targetIdx = children.indexOf(card);

    if (dragIdx < targetIdx) {
      container.insertBefore(dragging, card.nextSibling);
    } else {
      container.insertBefore(dragging, card);
    }
  };

  container.ondragend = (e) => {
    const card = e.target.closest(".segment-card");
    if (card) card.classList.remove("dragging");

    const children = Array.from(container.children);
    const renderedIds = children.map((child) => child.dataset.segmentId);
    const originalIds = editorState.segments
      .slice(pageStartIndex, pageStartIndex + children.length)
      .map((segment) => segment.id);
    const changed = renderedIds.some((segmentId, index) => (
      segmentId !== originalIds[index]
    ));

    if (changed) {
      pushUndo();
      const segmentsById = new Map(
        editorState.segments.map((segment) => [segment.id, segment]),
      );
      const reorderedPage = renderedIds
        .map((segmentId) => segmentsById.get(segmentId))
        .filter(Boolean);
      editorState.segments.splice(
        pageStartIndex,
        reorderedPage.length,
        ...reorderedPage,
      );
      editorState.segments.forEach((segment, index) => {
        segment.order = index + 1;
      });
      markDirty();
      renderTimeline();
      renderSegmentList();
      renderStatsDashboard();
      showToast("片段顺序已更新", "info");
    }
  };

  container.ondrop = (e) => {
    e.preventDefault();
  };
}
