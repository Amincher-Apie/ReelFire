// ReelFire — editor entry point
import { initTheme } from "./utils/theme.js";
import { loadUser } from "./utils/user.js";
import { byId, safeOn } from "./utils/dom.js";
import { editorState } from "./state/editor-state.js";
import { setEditorView } from "./views/editor-video.js";
import { loadEditorData } from "./views/editor-segments.js";
import { setReviewStatus, setReviewNote, applyBoundaryChange, reorderSegment, undo, redo } from "./views/editor-review.js";
import { showStatsDialog } from "./views/editor-stats.js";
import { saveReview, createRoughCut, exportReview, showReportDialog } from "./views/editor-actions.js";

function initEditor() {
  initTheme();
  loadUser();

  const pathParts = window.location.pathname.split("/").filter(Boolean);
  const jobId = pathParts.length >= 2 ? pathParts[1] : null;

  if (!jobId) {
    setEditorView("error");
    byId("editor-error-message").textContent = "URL 缺少任务编号。请从工作台进入编辑页。";
    return;
  }

  // buttons
  safeOn("editor-retry-button", "click", () => loadEditorData(jobId));
  safeOn("save-review-button", "click", saveReview);
  safeOn("rough-cut-button", "click", createRoughCut);
  safeOn("view-report-button", "click", showReportDialog);
  safeOn("close-report-button", "click", () => byId("report-dialog").close());
  safeOn("report-dialog", "click", (e) => {
    if (e.target === byId("report-dialog")) byId("report-dialog").close();
  });
  safeOn("export-review-button", "click", exportReview);

  // undo/redo buttons (P2)
  safeOn("undo-button", "click", undo);
  safeOn("redo-button", "click", redo);

  // stats tiles → dialog
  document.querySelectorAll(".stat-tile").forEach((tile) => {
    tile.addEventListener("click", showStatsDialog);
  });
  safeOn("close-stats-button", "click", () => byId("stats-dialog").close());

  // tri-state review buttons
  document.querySelectorAll(".review-option").forEach((btn) => {
    btn.addEventListener("click", () => {
      setReviewStatus(editorState.selectedSegmentId, btn.dataset.reviewValue);
    });
  });

  // review note input
  const reviewNoteInput = byId("review-note-input");
  if (reviewNoteInput) {
    reviewNoteInput.addEventListener("input", () => {
      setReviewNote(editorState.selectedSegmentId, reviewNoteInput.value);
    });
  }

  // boundary edit inputs
  ["boundary-start", "boundary-end"].forEach((id) => {
    const input = byId(id);
    if (!input) return;
    input.addEventListener("change", () => {
      applyBoundaryChange(
        editorState.selectedSegmentId,
        id === "boundary-start" ? "start" : "end",
        input.value
      );
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        applyBoundaryChange(
          editorState.selectedSegmentId,
          id === "boundary-start" ? "start" : "end",
          input.value
        );
      }
    });
  });

  // sort buttons
  const sortUp = document.querySelector(".sort-up");
  const sortDown = document.querySelector(".sort-down");
  if (sortUp) sortUp.addEventListener("click", () => reorderSegment(editorState.selectedSegmentId, "up"));
  if (sortDown) sortDown.addEventListener("click", () => reorderSegment(editorState.selectedSegmentId, "down"));

  // P2: keyboard shortcuts for undo/redo
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "z" && !e.shiftKey) {
      e.preventDefault();
      undo();
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === "y" || (e.key === "z" && e.shiftKey))) {
      e.preventDefault();
      redo();
    }
  });

  // dirty state warning
  window.addEventListener("beforeunload", (e) => {
    if (editorState.dirty) {
      e.preventDefault();
      e.returnValue = "您有未保存的审核修改，确定要离开吗？";
      return e.returnValue;
    }
  });

  loadEditorData(jobId);
}

initEditor();
