// ReelFire — segment operations: add, delete, merge, split, playhead markers
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
    editorState.segments = editorState.segments.filter((s) => s.id !== segId);
    if (editorState.selectedSegmentId === segId) {
      editorState.selectedSegmentId = null;
    }
    markDirty();
    renderSegmentList();
    renderTimeline();
    renderStatsDashboard();
    showToast("片段已删除", "success");
  } catch (err) {
    showToast(err.message || "删除片段失败", "error");
    // Fallback: remove from local state anyway
    editorState.segments = editorState.segments.filter((s) => s.id !== segId);
    if (editorState.selectedSegmentId === segId) {
      editorState.selectedSegmentId = null;
    }
    renderSegmentList();
    renderTimeline();
    renderStatsDashboard();
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
    // Fallback: merge locally
    const merged = {
      id: "merged_" + seg1.id + "_" + seg2.id,
      start: Math.min(seg1.start, seg2.start),
      end: Math.max(seg1.end, seg2.end),
      score: Math.max(seg1.score || 0, seg2.score || 0),
      order: Math.min(seg1.order || 0, seg2.order || 0),
      source_keyframes: [
        ...(seg1.source_keyframes || []),
        ...(seg2.source_keyframes || []),
      ],
      type: "merged",
    };
    editorState.segments = [
      ...editorState.segments.filter((s) => s.id !== seg1.id && s.id !== seg2.id),
      merged,
    ].sort((a, b) => (a.order || 0) - (b.order || 0));
    editorState.selectedSegmentId = merged.id;
    markDirty();
    renderSegmentList();
    renderTimeline();
    renderStatsDashboard();
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
    // Fallback: split locally
    const seg = editorState.segments.find((s) => s.id === segId);
    if (!seg) return;
    const segA = {
      id: segId + "_a",
      start: seg.start,
      end: splitTime,
      score: seg.score || 0,
      order: seg.order || 0,
      source_keyframes: [...(seg.source_keyframes || [])],
      type: "split",
    };
    const segB = {
      id: segId + "_b",
      start: splitTime,
      end: seg.end,
      score: seg.score || 0,
      order: (seg.order || 0) + 1,
      source_keyframes: [...(seg.source_keyframes || [])],
      type: "split",
    };
    editorState.segments = [
      ...editorState.segments.filter((s) => s.id !== segId),
      segA,
      segB,
    ].sort((a, b) => (a.order || 0) - (b.order || 0));
    editorState.selectedSegmentId = segA.id;
    markDirty();
    renderSegmentList();
    renderTimeline();
    renderStatsDashboard();
  }
}

// ── segment playback ────────────────────────────────────────────────────

export function playSegment(segId) {
  const seg = editorState.segments.find((s) => s.id === segId);
  if (!seg || !editorState.videoElement) return;

  const video = editorState.videoElement;
  video.currentTime = seg.start;
  selectSegment(segId);

  video.play().catch(() => { /* autoplay blocked — user must click play */ });

  // Pause at segment end
  const onTimeUpdate = () => {
    if (video.currentTime >= seg.end) {
      video.pause();
      video.removeEventListener("timeupdate", onTimeUpdate);
    }
  };
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

let dragSrcIndex = null;

export function initDragReorder(container) {
  if (!container) return;

  container.addEventListener("dragstart", (e) => {
    const card = e.target.closest(".segment-card");
    if (!card) return;
    dragSrcIndex = Array.from(container.children).indexOf(card);
    card.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", card.dataset.segmentId || "");
  });

  container.addEventListener("dragover", (e) => {
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
  });

  container.addEventListener("dragend", (e) => {
    const card = e.target.closest(".segment-card");
    if (card) card.classList.remove("dragging");

    // Calculate new order from DOM positions
    const children = Array.from(container.children);
    const changed = children.some((child, i) => {
      const segId = child.dataset.segmentId;
      const seg = editorState.segments.find((s) => s.id === segId);
      return seg && seg.order !== i + 1;
    });

    if (changed) {
      pushUndo();
      children.forEach((child, i) => {
        const segId = child.dataset.segmentId;
        const seg = editorState.segments.find((s) => s.id === segId);
        if (seg) seg.order = i + 1;
      });
      editorState.segments.sort((a, b) => (a.order || 0) - (b.order || 0));
      markDirty();
      renderTimeline();
      renderStatsDashboard();
      showToast("片段顺序已更新", "info");
    }
    dragSrcIndex = null;
  });

  container.addEventListener("drop", (e) => {
    e.preventDefault();
  });
}
