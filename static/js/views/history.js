import { appState, statusLabels } from "../state/app-state.js";
import { setSelectedProject } from "../state/project-selection.js";
import api from "../api/client.js";
import { byId } from "../utils/dom.js";
import { showToast } from "../utils/ui.js";
import {
  setResultState,
  stopPolling,
  loadReport,
  pollJob,
  logTool,
  renderAnalysisProgress,
  updateJobNavigation,
  updateAnalysisContext,
  prepareActiveAnalysis,
} from "./analysis.js";
import { showAppView } from "./navigation.js";

export function historyStatus(status) {
  return statusLabels[status] || status || "未知";
}

async function restoreProjectFromJob(job) {
  let project = null;
  if (job.project_id != null) {
    try {
      const payload = await api.get(
        `/api/projects/${encodeURIComponent(job.project_id)}`,
      );
      project = payload.project || null;
    } catch {
      project = null;
    }
  }
  if (!project && job.project_name) {
    const payload = await api.get("/api/projects");
    project = (payload.projects || []).find(
      (item) => item.name === job.project_name,
    ) || null;
  }
  if (project) setSelectedProject(project);
  return project;
}

export async function openHistoryJob(jobId) {
  try {
    const payload = await api.get(`/api/jobs/${encodeURIComponent(jobId)}`);
    const job = payload.job;
    appState.currentJobId = jobId;
    appState.currentJob = job;
    appState.toolCalls = [];
    const project = await restoreProjectFromJob(job);
    updateAnalysisContext(project, job);
    logTool("GET", `/api/jobs/${jobId}`, "打开所选项目的分析任务");
    updateJobNavigation(jobId, job.status === "completed");
    if (job.progress) renderAnalysisProgress(job.progress);
    showAppView("analysis");
    if (job.status === "completed") {
      await loadReport(jobId);
    } else if (job.status === "failed") {
      setResultState("error", "failed", job.error || "任务失败。");
    } else {
      prepareActiveAnalysis(job);
      await pollJob(jobId);
    }
  } catch (error) {
    showToast(error.message, "error");
    showAppView("projects");
  }
}

export async function deleteHistoryJob(jobId) {
  if (!window.confirm("删除后将同时移除该任务的上传文件与输出结果，确定继续吗？")) {
    return;
  }
  try {
    await api.delete(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (appState.currentJobId === jobId) {
      stopPolling();
      appState.currentJobId = null;
      appState.currentJob = null;
      appState.report = null;
      setResultState("empty", "idle");
      updateAnalysisContext(appState.currentProject, null);
    }
    showToast("任务已删除", "success");
  } catch (error) {
    showToast(error.message, "error");
  }
}
