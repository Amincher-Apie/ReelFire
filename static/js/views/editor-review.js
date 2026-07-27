// ReelFire — editor review editor, boundary editor, sorting, undo/redo
import { editorState } from "../state/editor-state.js";
import { byId } from "../utils/dom.js";
import { renderTimeline, renderSegmentList } from "./editor-video.js";
import { renderSegmentList as refreshSegmentList } from "./editor-segments.js";
import { renderStatsDashboard } from "./editor-stats.js";
import { selectSegment } from "./editor-segments.js";

const MAX_UNDO = 50;

// ── snapshot helpers (P2 undo/redo) ───────────────────────────────────

function takeSnapshot() {
  return {
    reviews: JSON.parse(JSON.stringify(editorState.reviews)),
    segments: editorState.segments.map((s) => ({ ...s })),
  };
}

function restoreSnapshot(snap) {
  editorState.reviews = JSON.parse(JSON.stringify(snap.reviews));
  editorState.segments = snap.segments.map((s) => ({ ...s }));
}

export function pushUndo() {
  editorState.undoStack.push(takeSnapshot());
  if (editorState.undoStack.length > MAX_UNDO) {
    editorState.undoStack.shift();
  }
  // new action clears redo
  editorState.redoStack = [];
}

export function undo() {
  if (!editorState.undoStack.length) return;
  editorState.redoStack.push(takeSnapshot());
  const snap = editorState.undoStack.pop();
  restoreSnapshot(snap);
  markDirty();
  renderTimeline();
  refreshSegmentList();
  renderStatsDashboard();
  if (editorState.selectedSegmentId) {
    // re-select to refresh boundary editor etc
    const stillExists = editorState.segments.find((s) => s.id === editorState.selectedSegmentId);
    if (stillExists) selectSegment(editorState.selectedSegmentId);
  }
}

export function redo() {
  if (!editorState.redoStack.length) return;
  editorState.undoStack.push(takeSnapshot());
  const snap = editorState.redoStack.pop();
  restoreSnapshot(snap);
  markDirty();
  renderTimeline();
  refreshSegmentList();
  renderStatsDashboard();
  if (editorState.selectedSegmentId) {
    const stillExists = editorState.segments.find((s) => s.id === editorState.selectedSegmentId);
    if (stillExists) selectSegment(editorState.selectedSegmentId);
  }
}

// ── review editor ─────────────────────────────────────────────────────

export function renderReviewEditor(segmentId) {
  const container = byId("review-editor");
  if (!container) return;
  container.hidden = false;

  const review = editorState.reviews[segmentId];
  const recommendation = review ? review.recommendation : "";
  const note = review ? review.note || "" : "";

  const buttons = container.querySelectorAll(".review-option");
  buttons.forEach((btn) => {
    const active = btn.dataset.reviewValue === recommendation;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", String(active));
  });

  const noteField = container.querySelector(".review-note-field");
  if (noteField) noteField.value = note;
}

export function setReviewStatus(segmentId, value) {
  if (!segmentId) return;
  pushUndo();
  if (!editorState.reviews[segmentId]) {
    editorState.reviews[segmentId] = { recommendation: "", note: "" };
  }
  editorState.reviews[segmentId].recommendation = value;
  markDirty();
  renderReviewEditor(segmentId);
  refreshSegmentList();
  renderStatsDashboard();
}

export function setReviewNote(segmentId, note) {
  if (!segmentId) return;
  pushUndo();
  if (!editorState.reviews[segmentId]) {
    editorState.reviews[segmentId] = { recommendation: "", note: "" };
  }
  editorState.reviews[segmentId].note = note;
  markDirty();
}

// ── boundary editor ───────────────────────────────────────────────────

export function renderBoundaryEditor(segmentId) {
  const container = byId("boundary-editor");
  if (!container) return;

  const seg = editorState.segments.find((s) => s.id === segmentId);
  if (!seg) { container.hidden = true; return; }
  container.hidden = false;

  const startInput = container.querySelector(".boundary-start");
  const endInput = container.querySelector(".boundary-end");
  if (startInput) startInput.value = seg.start;
  if (endInput) endInput.value = seg.end;

  const duration = editorState.video ? editorState.video.duration : 0;
  if (startInput) startInput.max = String(duration);
  if (endInput) endInput.max = String(duration);
}

export function applyBoundaryChange(segmentId, field, rawValue) {
  const seg = editorState.segments.find((s) => s.id === segmentId);
  if (!seg) return;

  const value = Number(rawValue);
  if (!Number.isFinite(value) || value < 0) return;

  const duration = editorState.video ? editorState.video.duration : Infinity;

  pushUndo();

  if (field === "start") {
    if (value >= seg.end) return;
    if (value > duration) return;
    seg.start = value;
  } else if (field === "end") {
    if (value <= seg.start) return;
    if (value > duration) return;
    seg.end = value;
  }

  markDirty();
  renderTimeline();
  refreshSegmentList();
  renderBoundaryEditor(segmentId);
  renderStatsDashboard();
}

// ── sort ──────────────────────────────────────────────────────────────

export function renderSortButtons(segmentId) {
  const container = byId("sort-buttons");
  if (!container) return;
  container.hidden = false;

  const idx = editorState.segments.findIndex((s) => s.id === segmentId);
  const upBtn = container.querySelector(".sort-up");
  const downBtn = container.querySelector(".sort-down");
  if (upBtn) upBtn.disabled = idx <= 0;
  if (downBtn) downBtn.disabled = idx < 0 || idx >= editorState.segments.length - 1;
}

export function reorderSegment(segmentId, direction) {
  const idx = editorState.segments.findIndex((s) => s.id === segmentId);
  if (idx < 0) return;
  const swapIdx = direction === "up" ? idx - 1 : idx + 1;
  if (swapIdx < 0 || swapIdx >= editorState.segments.length) return;

  pushUndo();

  const tmp = editorState.segments[idx].order;
  editorState.segments[idx].order = editorState.segments[swapIdx].order;
  editorState.segments[swapIdx].order = tmp;

  editorState.segments.sort((a, b) => a.order - b.order);

  markDirty();
  renderTimeline();
  refreshSegmentList();
  renderSortButtons(segmentId);
  const newIdx = editorState.segments.findIndex((s) => s.id === segmentId);
  if (newIdx >= 0) selectSegment(editorState.segments[newIdx].id);
}

// ── dirty state ───────────────────────────────────────────────────────

export function markDirty() {
  editorState.dirty = true;
  updateDirtyIndicator();
  // P2: auto-save draft (imported dynamically to avoid circular deps at module level)
  import("./editor-actions.js").then((m) => m.scheduleAutoSave());
}

export function updateDirtyIndicator() {
  const button = byId("save-review-button");
  if (!button) return;
  const original = button.dataset.originalLabel || "保存审核";
  button.dataset.originalLabel = original;
  button.textContent = editorState.dirty ? "● " + original : original;
  button.setAttribute(
    "aria-label",
    editorState.dirty ? original + "（有未保存修改）" : original
  );
}
