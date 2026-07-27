// ReelFire — workbench entry point
import { initTheme } from "./utils/theme.js";
import { loadUser } from "./utils/user.js";
import { byId } from "./utils/dom.js";
import api from "./api/client.js";
import { showToast } from "./utils/ui.js";
import { appState } from "./state/app-state.js";
import { initUpload } from "./views/upload.js";
import { setView, submitAnalysis, stopPolling, stopAgentPolling, showRuleOutput, showReportDialog, hydrateAnalysisJob } from "./views/analysis.js";
import { saveReview, createRoughCut } from "./views/review.js";
import { loadHistory, openHistoryJob, deleteHistoryJob } from "./views/history.js";
import {
  loadProjects, openProject, startAnalysisInProject,
  backToProjectDetail, showProjectsView, showHistoryView,
  initProjectDialog,
} from "./views/projects.js";

function initApp() {
  // Navigation buttons — prevent default link navigation, handle disabled state
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
      else if (view === "analysis") startAnalysisInProject();
      else if (view === "history") showHistoryView();
    });
  });

  // Back to projects
  const backBtn = byId("back-to-projects");
  if (backBtn) backBtn.addEventListener("click", backToProjectDetail);

  // Project detail → start analysis
  const startAnalysisBtn = byId("project-start-analysis");
  if (startAnalysisBtn) startAnalysisBtn.addEventListener("click", startAnalysisInProject);

  // Empty state create button
  const emptyCreate = byId("projects-empty-create");
  if (emptyCreate) emptyCreate.addEventListener("click", () => byId("project-dialog").showModal());

  // Projects retry
  const projectsRetry = byId("projects-retry-button");
  if (projectsRetry) projectsRetry.addEventListener("click", loadProjects);

  // Logout
  byId("logout-button").addEventListener("click", logout);

  // Analysis form
  byId("project-name").addEventListener("input", () => {
    appState.currentProjectId = null;
    appState.currentProjectName = null;
  });
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
  byId("close-report-button").addEventListener("click", () => byId("report-dialog").close());
  byId("report-dialog").addEventListener("click", (event) => {
    if (event.target === byId("report-dialog")) byId("report-dialog").close();
  });

  // History
  byId("refresh-history-button").addEventListener("click", loadHistory);
  byId("history-body").addEventListener("click", (event) => {
    const button = event.target.closest("[data-history-action]");
    if (!button) return;
    if (button.dataset.historyAction === "open") openHistoryJob(button.dataset.jobId);
    if (button.dataset.historyAction === "delete") deleteHistoryJob(button.dataset.jobId);
  });

  // Rule output buttons
  byId("show-cover-button").addEventListener("click", () => showRuleOutput("cover"));
  byId("show-tags-button").addEventListener("click", () => showRuleOutput("tags"));
  byId("show-report-button").addEventListener("click", () => showRuleOutput("report"));

  // Init upload, project dialog, and load user
  initUpload();
  initProjectDialog();
  loadUser();

  // Check for server-injected initial view / job ID
  const initialView = document.body.dataset.initialView || "projects";
  const initialJobId = document.body.dataset.jobId || "";
  if (initialView === "analysis" && initialJobId) {
    setView("analysis");
    hydrateAnalysisJob(initialJobId);
  } else if (initialView === "history") {
    setView("history");
  } else {
    showProjectsView();
  }
}

async function logout() {
  try {
    await api.post("/api/auth/logout", {});
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
initTheme();
if (document.body.dataset.page === "app") initApp();
