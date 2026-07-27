import { appState, statusLabels } from "../state/app-state.js";
import {
  restoreSelectedProject,
  setSelectedProject,
} from "../state/project-selection.js";
import api from "../api/client.js";
import { byId, clearChildren, createElement } from "../utils/dom.js";
import { formatDate } from "../utils/format.js";
import { paginate, renderPagination } from "../utils/pagination.js";
import { showToast } from "../utils/ui.js";
import { clearSelectedFile } from "./upload.js";
import { openHistoryJob } from "./history.js";
import { showAppView } from "./navigation.js";

let projectView = window.localStorage.getItem("reelfire-project-view") === "list"
  ? "list"
  : "cards";
let currentProjects = [];
let projectPage = 1;
const PROJECT_PAGE_SIZE = 10;

function gameTypeLabel(type) {
  const labels = { csgo: "CS2", valorant: "Valorant", other: "通用 FPS" };
  return labels[type] || "通用 FPS";
}

function projectJobs(project, jobs) {
  return jobs.filter((job) => (
    String(job.project_id ?? "") === String(project.id)
    || (
      job.project_id == null
      && job.project_name === project.name
    )
  ));
}

function jobTimestamp(job) {
  const value = job.updated_at || job.completed_at || job.created_at || "";
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function aggregateProjects(projects, jobs) {
  return projects.map((project) => {
    const relatedJobs = projectJobs(project, jobs)
      .slice()
      .sort((left, right) => jobTimestamp(right) - jobTimestamp(left));
    const latestJob = relatedJobs[0] || null;
    return {
      ...project,
      jobs: relatedJobs,
      latestJob,
      assetName: latestJob
        ? latestJob.original_asset_name || latestJob.asset_name || "未命名素材"
        : "暂无素材",
      latestStatus: latestJob ? latestJob.status : null,
      taskCount: relatedJobs.length,
      activityAt: latestJob
        ? latestJob.updated_at || latestJob.completed_at || latestJob.created_at
        : project.updated_at || project.created_at,
    };
  });
}

function statusText(status) {
  return status ? statusLabels[status] || status : "未开始";
}

function createStatusBadge(project) {
  return createElement(
    "span",
    `history-status ${project.latestStatus || "idle"}`,
    statusText(project.latestStatus),
  );
}

function selectProject(project) {
  setSelectedProject(project);
  renderProjects(currentProjects);
  showToast(`已选择项目：${project.name}`, "success");
}

function isSelected(project) {
  return String(project.id) === String(appState.currentProjectId);
}

function createProjectActions(project, compact = false) {
  const actions = createElement("div", compact ? "table-actions" : "project-card-actions");
  const selectButton = createElement(
    "button",
    `button ${isSelected(project) ? "secondary" : "primary"} small`,
    isSelected(project) ? "已选择" : "选择项目",
  );
  selectButton.type = "button";
  selectButton.setAttribute("aria-pressed", String(isSelected(project)));
  selectButton.addEventListener("click", () => selectProject(project));

  const taskButton = createElement("button", "button ghost small", "新建任务");
  taskButton.type = "button";
  taskButton.addEventListener("click", () => openProjectTaskDialog(project));

  const moreButton = createElement("button", "icon-button project-more-button", "⋯");
  moreButton.type = "button";
  moreButton.title = "更多操作";
  moreButton.setAttribute("aria-label", `${project.name} 的更多操作`);
  moreButton.addEventListener("click", () => showProjectMenu(project, moreButton));
  actions.append(selectButton, taskButton, moreButton);
  return actions;
}

function renderProjectCards(projects) {
  const grid = byId("projects-grid");
  clearChildren(grid);

  projects.forEach((project) => {
    const card = createElement(
      "article",
      `project-card${isSelected(project) ? " selected" : ""}`,
    );
    card.tabIndex = 0;
    card.setAttribute("aria-label", `选择项目 ${project.name}`);
    card.addEventListener("click", (event) => {
      if (!event.target.closest("button, a")) selectProject(project);
    });
    card.addEventListener("keydown", (event) => {
      if ((event.key === "Enter" || event.key === " ") && event.target === card) {
        event.preventDefault();
        selectProject(project);
      }
    });

    const header = createElement("div", "project-card-header");
    const heading = createElement("div", "project-card-heading");
    const icon = createElement("div", "project-card-icon");
    icon.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="13" height="14" rx="2"/><path d="m16 10 5-3v10l-5-3z"/></svg>';
    heading.append(icon, createElement("h3", "project-card-name", project.name));
    header.append(
      heading,
      createElement(
        "span",
        `project-game-badge ${project.game_type || "other"}`,
        gameTypeLabel(project.game_type),
      ),
    );

    const details = createElement("dl", "project-card-details");
    [
      ["素材", project.assetName],
      ["最近状态", createStatusBadge(project)],
      ["任务数量", `${project.taskCount} 个`],
      ["更新时间", formatDate(project.activityAt)],
    ].forEach(([label, value]) => {
      const item = createElement("div", "project-card-detail");
      item.append(createElement("dt", "", label));
      const content = createElement("dd");
      if (value instanceof Node) content.append(value);
      else content.textContent = value;
      item.append(content);
      details.append(item);
    });

    card.append(header, details, createProjectActions(project));
    grid.append(card);
  });
}

function renderProjectList(projects) {
  const body = byId("projects-list-body");
  clearChildren(body);

  projects.forEach((project) => {
    const row = document.createElement("tr");
    if (isSelected(project)) row.classList.add("selected");
    const nameCell = createElement("td");
    const nameButton = createElement("button", "project-name-button", project.name);
    nameButton.type = "button";
    nameButton.addEventListener("click", () => selectProject(project));
    nameCell.append(nameButton);
    const assetCell = createElement("td", "project-asset-cell", project.assetName);
    const gameCell = createElement("td");
    gameCell.append(createElement(
      "span",
      `project-game-badge ${project.game_type || "other"}`,
      gameTypeLabel(project.game_type),
    ));
    const statusCell = createElement("td");
    statusCell.append(createStatusBadge(project));
    const countCell = createElement("td", "tabular", String(project.taskCount));
    const dateCell = createElement("td", "", formatDate(project.activityAt));
    const actionCell = createElement("td");
    actionCell.append(createProjectActions(project, true));
    row.append(
      nameCell,
      assetCell,
      gameCell,
      statusCell,
      countCell,
      dateCell,
      actionCell,
    );
    body.append(row);
  });
}

function renderProjects(projects) {
  const pagination = paginate(projects, projectPage, PROJECT_PAGE_SIZE);
  projectPage = pagination.page;
  renderProjectCards(pagination.items);
  renderProjectList(pagination.items);
  renderPagination(byId("projects-pagination"), {
    total: pagination.total,
    page: pagination.page,
    pageSize: pagination.pageSize,
    adjustable: false,
    itemLabel: "个项目",
    ariaLabel: "项目列表分页",
    onPageChange: (page) => {
      projectPage = page;
      renderProjects(currentProjects);
      byId("projects-heading")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    },
  });
  applyProjectView();
}

function applyProjectView() {
  const hasProjects = currentProjects.length > 0;
  byId("projects-grid").hidden = !hasProjects || projectView !== "cards";
  byId("projects-list").hidden = !hasProjects || projectView !== "list";
  document.querySelectorAll("[data-project-view]").forEach((button) => {
    const active = button.dataset.projectView === projectView;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

export async function loadProjects() {
  const loading = byId("projects-loading");
  const empty = byId("projects-empty");
  const error = byId("projects-error");
  loading.hidden = false;
  empty.hidden = true;
  error.hidden = true;
  byId("projects-grid").hidden = true;
  byId("projects-list").hidden = true;

  try {
    const [projectPayload, jobPayload] = await Promise.all([
      api.get("/api/projects"),
      api.get("/api/jobs"),
    ]);
    const projects = Array.isArray(projectPayload.projects) ? projectPayload.projects : [];
    const jobs = Array.isArray(jobPayload.jobs) ? jobPayload.jobs : [];
    currentProjects = aggregateProjects(projects, jobs);
    projectPage = 1;
    restoreSelectedProject(currentProjects);
    if (appState.currentProjectId != null) {
      const selected = currentProjects.find((project) => isSelected(project));
      appState.currentProjectJobs = selected ? selected.jobs : [];
    } else {
      appState.currentProjectJobs = [];
    }
    renderProjects(currentProjects);
    byId("projects-count").textContent = `${projects.length} 个项目`;
    loading.hidden = true;
    empty.hidden = projects.length !== 0;
  } catch (errorValue) {
    loading.hidden = true;
    byId("projects-count").textContent = "项目加载失败";
    error.hidden = false;
    byId("projects-error-message").textContent = errorValue.message || "加载项目列表失败";
  }
}

function showProjectMenu(project, anchorButton) {
  document.querySelectorAll(".project-context-menu").forEach((menu) => menu.remove());
  const menu = createElement("div", "project-context-menu");
  const renameButton = createElement("button", "", "重命名");
  renameButton.type = "button";
  renameButton.addEventListener("click", () => {
    menu.remove();
    renameProject(project);
  });
  const deleteButton = createElement("button", "danger", "删除项目");
  deleteButton.type = "button";
  deleteButton.addEventListener("click", () => {
    menu.remove();
    deleteProject(project);
  });
  menu.append(renameButton, deleteButton);

  const rect = anchorButton.getBoundingClientRect();
  menu.style.position = "fixed";
  menu.style.top = `${rect.bottom + 4}px`;
  menu.style.right = `${window.innerWidth - rect.right}px`;
  document.body.append(menu);
  window.setTimeout(() => {
    document.addEventListener("click", function closeMenu(event) {
      if (menu.contains(event.target)) return;
      menu.remove();
      document.removeEventListener("click", closeMenu);
    });
  }, 0);
}

async function renameProject(project) {
  const name = window.prompt("请输入新项目名称：", project.name);
  if (!name || !name.trim() || name.trim() === project.name) return;
  try {
    const payload = await api.patch(`/api/projects/${encodeURIComponent(project.id)}`, {
      name: name.trim(),
    });
    if (isSelected(project)) setSelectedProject(payload.project);
    showToast("项目已重命名", "success");
    await loadProjects();
  } catch (error) {
    showToast(error.message || "重命名失败", "error");
  }
}

async function deleteProject(project) {
  if (!window.confirm(
    `确定要删除项目“${project.name}”吗？仅没有任务的空项目可以删除。`,
  )) return;
  try {
    await api.delete(`/api/projects/${encodeURIComponent(project.id)}`);
    showToast("项目已删除", "success");
    await loadProjects();
  } catch (error) {
    showToast(error.message || "删除失败", "error");
  }
}

export function openProjectTaskDialog(project = null) {
  const dialog = byId("project-dialog");
  const existingProject = project || null;
  byId("analysis-project-id").value = existingProject ? String(existingProject.id) : "";
  byId("project-dialog-title").textContent = existingProject ? "新建分析任务" : "创建新项目";
  byId("project-dialog-description").textContent = existingProject
    ? `素材将归档到“${existingProject.name}”。`
    : "创建项目并上传首个分析素材。";
  byId("project-name").value = existingProject ? existingProject.name : "";
  byId("project-name").readOnly = Boolean(existingProject);
  byId("game-type").value = existingProject?.game_type || "csgo";
  byId("game-type").disabled = Boolean(existingProject);
  byId("analysis-submit-label").textContent = existingProject
    ? "创建任务并开始分析"
    : "创建项目并开始分析";
  clearSelectedFile();
  dialog.showModal();
  window.setTimeout(() => {
    byId(existingProject ? "video-file" : "project-name").focus();
  }, 0);
}

export function initProjectBrowser() {
  document.querySelectorAll("[data-project-view]").forEach((button) => {
    button.addEventListener("click", () => {
      projectView = button.dataset.projectView === "list" ? "list" : "cards";
      window.localStorage.setItem("reelfire-project-view", projectView);
      applyProjectView();
    });
  });
}

export function initProjectDialog() {
  const dialog = byId("project-dialog");
  const inputPanel = document.querySelector(".input-panel");
  const formSlot = byId("project-form-slot");
  const taskStages = byId("task-stages");
  const cancelAnalysis = byId("cancel-analysis-button");
  const loadingState = byId("result-loading");
  if (inputPanel && formSlot) {
    inputPanel.classList.add("project-task-form-panel");
    formSlot.append(inputPanel);
  }
  if (taskStages && loadingState) loadingState.append(taskStages);
  if (cancelAnalysis && loadingState) loadingState.append(cancelAnalysis);

  byId("show-create-project-button").addEventListener(
    "click",
    () => openProjectTaskDialog(),
  );
  byId("projects-empty-create").addEventListener(
    "click",
    () => openProjectTaskDialog(),
  );
  byId("close-project-dialog-button").addEventListener("click", () => dialog.close());
  byId("cancel-project-button").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
}

function selectedProjectOrNotice() {
  if (appState.currentProject) return appState.currentProject;
  showAppView("projects");
  showToast("请先在项目页选择一个项目。", "info");
  return null;
}

function jobsForSelectedProject(jobs) {
  return jobs
    .filter((job) => (
      String(job.project_id ?? "") === String(appState.currentProjectId)
      || (
        job.project_id == null
        && job.project_name === appState.currentProjectName
      )
    ))
    .sort((left, right) => jobTimestamp(right) - jobTimestamp(left));
}

export async function showAnalysisWorkspace() {
  const project = selectedProjectOrNotice();
  if (!project) return;
  try {
    const payload = await api.get("/api/jobs");
    const jobs = jobsForSelectedProject(Array.isArray(payload.jobs) ? payload.jobs : []);
    if (!jobs.length) {
      openProjectTaskDialog(project);
      showToast("该项目还没有任务，请先添加素材。", "info");
      return;
    }
    await openHistoryJob(jobs[0].job_id);
  } catch (error) {
    showToast(error.message, "error");
  }
}

export async function showEditorWorkspace() {
  const project = selectedProjectOrNotice();
  if (!project) return;
  try {
    const currentJob = appState.currentJob;
    const currentBelongsToProject = currentJob && (
      String(currentJob.project_id ?? "") === String(project.id)
      || (
        currentJob.project_id == null
        && currentJob.project_name === project.name
      )
    );
    const currentReady = currentBelongsToProject && (
      currentJob.status === "completed"
      || Number(currentJob.progress && currentJob.progress.completed_chunks) > 0
    );
    if (currentReady) {
      window.location.assign(
        `/jobs/${encodeURIComponent(currentJob.job_id)}/editor`,
      );
      return;
    }

    const payload = await api.get("/api/jobs");
    const job = jobsForSelectedProject(
      Array.isArray(payload.jobs) ? payload.jobs : [],
    ).find((item) => item.status === "completed");
    if (!job) {
      showToast("首个 YOLO 候选窗口完成后即可进入剪辑工作台。", "info");
      return;
    }
    window.location.assign(`/jobs/${encodeURIComponent(job.job_id)}/editor`);
  } catch (error) {
    showToast(error.message, "error");
  }
}

export function showProjectsView() {
  showAppView("projects");
  loadProjects();
}
