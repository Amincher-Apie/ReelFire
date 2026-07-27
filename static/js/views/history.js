// ReelFire — history list
import { appState, statusLabels } from "../state/app-state.js";
import api from "../api/client.js";
import { byId, clearChildren, createElement } from "../utils/dom.js";
import { formatDate } from "../utils/format.js";
import { showToast } from "../utils/ui.js";
import {
  setView, setResultState, stopPolling,
  loadReport, pollJob, logTool,
  renderAnalysisProgress, updateJobNavigation,
} from "./analysis.js";

export function historyStatus(status) {
  return statusLabels[status] || status || "未知";
}

export function renderHistory(jobs) {
  byId("history-loading").hidden = true;
  byId("history-error").hidden = true;
  byId("history-empty").hidden = jobs.length > 0;
  byId("history-table-wrapper").hidden = jobs.length === 0;
  const body = byId("history-body");
  clearChildren(body);

  jobs.forEach((job) => {
    const row = document.createElement("tr");
    const projectCell = createElement("td", "", job.project_name || "未命名任务");
    const assetCell = createElement("td", "", job.original_asset_name || job.asset_name || "—");
    const typeCell = createElement("td", "", job.game_type || "other");
    const statusCell = document.createElement("td");
    statusCell.append(createElement("span", `history-status ${job.status || ""}`, historyStatus(job.status)));
    const dateCell = createElement("td", "", formatDate(job.created_at));
    const actionCell = document.createElement("td");
    const actions = createElement("div", "table-actions");
    const openButton = createElement(
      "button",
      "button secondary small",
      job.status === "completed" ? "打开" : "查看",
    );
    openButton.type = "button";
    openButton.dataset.historyAction = "open";
    openButton.dataset.jobId = job.job_id;
    const deleteButton = createElement("button", "button ghost small", "删除");
    deleteButton.type = "button";
    deleteButton.dataset.historyAction = "delete";
    deleteButton.dataset.jobId = job.job_id;
    actions.append(openButton, deleteButton);
    actionCell.append(actions);
    row.append(projectCell, assetCell, typeCell, statusCell, dateCell, actionCell);
    body.append(row);
  });
}

export async function loadHistory() {
  byId("history-loading").hidden = false;
  byId("history-empty").hidden = true;
  byId("history-error").hidden = true;
  byId("history-table-wrapper").hidden = true;
  try {
    const payload = await api.get("/api/jobs");
    renderHistory(Array.isArray(payload.jobs) ? payload.jobs : []);
  } catch (error) {
    byId("history-loading").hidden = true;
    byId("history-error").hidden = false;
    byId("history-error-message").textContent = error.message;
  }
}

export async function openHistoryJob(jobId) {
  try {
    const payload = await api.get(`/api/jobs/${encodeURIComponent(jobId)}`);
    appState.currentJobId = jobId;
    appState.currentJob = payload.job;
    appState.toolCalls = [];
    logTool("GET", `/api/jobs/${jobId}`, "从历史记录打开任务");
    updateJobNavigation(jobId, payload.job.status === "completed");
    if (payload.job.progress) renderAnalysisProgress(payload.job.progress);
    setView("analysis");
    if (payload.job.status === "completed") {
      await loadReport(jobId);
    } else if (payload.job.status === "failed") {
      setResultState("error", "failed", payload.job.error || "任务失败。");
    } else {
      await pollJob(jobId);
    }
  } catch (error) {
    showToast(error.message, "error");
  }
}

export async function deleteHistoryJob(jobId) {
  if (!window.confirm("删除后将同时移除该任务的上传文件与输出结果，确定继续吗？")) return;
  try {
    await api.delete(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (appState.currentJobId === jobId) {
      stopPolling();
      appState.currentJobId = null;
      appState.currentJob = null;
      appState.report = null;
      setResultState("empty", "idle");
    }
    showToast("任务已删除", "success");
    await loadHistory();
  } catch (error) {
    showToast(error.message, "error");
  }
}
