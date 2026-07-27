// ReelFire — workbench entry point
import "./login.js";
import { initTheme } from "./utils/theme.js";
import { loadUser } from "./utils/user.js";
import { byId } from "./utils/dom.js";
import api from "./api/client.js";
import { showToast } from "./utils/ui.js";
import { appState } from "./state/app-state.js";
import { clearSelectedProject, refreshProjectContext } from "./state/project-selection.js";
import { initUpload } from "./views/upload.js";
import {
  setKeyframeReviewMode,
  showReportDialog,
  showRuleOutput,
  stopAgentPolling,
  stopPolling,
  submitAnalysis,
} from "./views/analysis.js";
import { saveReview, createRoughCut } from "./views/review.js";
import {
  openHistoryJob,
} from "./views/history.js";
import {
  loadProjects, showProjectsView, showAnalysisWorkspace, showEditorWorkspace,
  initProjectBrowser, initProjectDialog,
} from "./views/projects.js";

async function initApp() {
  // Navigation buttons
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", (event) => {
      // Always prevent default <a> navigation to keep SPA routing
      event.preventDefault();
      if (button.getAttribute("aria-disabled") === "true") {
        showToast(button.title || "该工作台当前不可用。", "info");
        return;
      }
      const view = button.dataset.view;
      if (view === "projects") showProjectsView();
      else if (view === "analysis") showAnalysisWorkspace();
      else if (view === "editor") showEditorWorkspace();
    });
  });

  // Projects retry
  const projectsRetry = byId("projects-retry-button");
  if (projectsRetry) projectsRetry.addEventListener("click", loadProjects);

  // Logout
  byId("logout-button").addEventListener("click", logout);

  // Analysis form
  byId("analysis-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitAnalysis();
  });
  byId("retry-button").addEventListener("click", submitAnalysis);

  // Cancel analysis
  const cancelBtn = byId("cancel-analysis-button");
  if (cancelBtn) {
    cancelBtn.addEventListener("click", () => {
      if (appState.currentJobId) {
        api.post("/api/jobs/" + encodeURIComponent(appState.currentJobId) + "/cancel", {})
          .then(() => showToast("已取消分析任务", "info"))
          .catch((err) => showToast(err.message, "error"));
        stopPolling();
      }
    });
  }

  // Review & rough cut
  byId("save-review-button").addEventListener("click", saveReview);
  byId("rough-cut-button").addEventListener("click", createRoughCut);
  byId("open-report-button").addEventListener("click", showReportDialog);
  document.querySelectorAll("[data-keyframe-review-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      setKeyframeReviewMode(button.dataset.keyframeReviewMode);
    });
  });
  byId("close-report-button").addEventListener("click", () => byId("report-dialog").close());
  byId("report-dialog").addEventListener("click", (event) => {
    if (event.target === byId("report-dialog")) byId("report-dialog").close();
  });

  // Rule output buttons
  byId("show-cover-button").addEventListener("click", () => showRuleOutput("cover"));
  byId("show-tags-button").addEventListener("click", () => showRuleOutput("tags"));
  byId("show-report-button").addEventListener("click", () => showRuleOutput("report"));

  // Init upload, project dialog, and load user
  initUpload();
  initProjectBrowser();
  initProjectDialog();
  await loadUser();
  refreshProjectContext();

  const initialView = document.body.dataset.initialView;
  const initialJobId = document.body.dataset.jobId;
  if (initialView === "analysis" && initialJobId) {
    await openHistoryJob(initialJobId);
  } else {
    showProjectsView();
  }
}

async function logout() {
  try {
    await api.post("/api/auth/logout", {});
    clearSelectedProject();
    showToast("已退出登录", "success");
    window.location.assign("/login");
  } catch (error) {
    showToast(error.message, "error");
  }
}

window.addEventListener("beforeunload", () => {
  stopPolling();
  stopAgentPolling();
  if (appState.previewUrl) URL.revokeObjectURL(appState.previewUrl);
});

// ES modules are deferred — DOM is already parsed
if (document.body.dataset.page === "app") {
  initTheme();
  initApp();
}
