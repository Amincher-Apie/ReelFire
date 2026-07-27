// ReelFire — workbench entry point
import { initTheme } from "./utils/theme.js";
import { loadUser } from "./utils/user.js";
import { byId } from "./utils/dom.js";
import api from "./api/client.js";
import { showToast } from "./utils/ui.js";
import { appState } from "./state/app-state.js";
import { initUpload } from "./views/upload.js";
import { setView, submitAnalysis, stopPolling, showRuleOutput, showReportDialog } from "./views/analysis.js";
import { saveReview, createRoughCut } from "./views/review.js";
import { loadHistory, openHistoryJob, deleteHistoryJob } from "./views/history.js";

function initApp() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
  byId("logout-button").addEventListener("click", logout);
  byId("project-name").addEventListener("input", () => {
    appState.currentProjectId = null;
    appState.currentProjectName = null;
  });
  byId("analysis-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitAnalysis();
  });
  byId("retry-button").addEventListener("click", submitAnalysis);
  byId("save-review-button").addEventListener("click", saveReview);
  byId("rough-cut-button").addEventListener("click", createRoughCut);
  byId("open-report-button").addEventListener("click", showReportDialog);
  byId("close-report-button").addEventListener("click", () => byId("report-dialog").close());
  byId("report-dialog").addEventListener("click", (event) => {
    if (event.target === byId("report-dialog")) byId("report-dialog").close();
  });
  byId("refresh-history-button").addEventListener("click", loadHistory);
  byId("history-body").addEventListener("click", (event) => {
    const button = event.target.closest("[data-history-action]");
    if (!button) return;
    if (button.dataset.historyAction === "open") openHistoryJob(button.dataset.jobId);
    if (button.dataset.historyAction === "delete") deleteHistoryJob(button.dataset.jobId);
  });
  byId("show-cover-button").addEventListener("click", () => showRuleOutput("cover"));
  byId("show-tags-button").addEventListener("click", () => showRuleOutput("tags"));
  byId("show-report-button").addEventListener("click", () => showRuleOutput("report"));
  initUpload();
  loadUser();
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
  if (appState.previewUrl) URL.revokeObjectURL(appState.previewUrl);
});

// ES modules are deferred — DOM is already parsed
initTheme();
if (document.body.dataset.page === "app") initApp();
