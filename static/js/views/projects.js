// ReelFire — project management: list, create, rename, delete
import { appState } from "../state/app-state.js";
import api from "../api/client.js";
import { byId, clearChildren, createElement } from "../utils/dom.js";
import { formatDate } from "../utils/format.js";
import { showToast, setButtonLoading } from "../utils/ui.js";

// ── view switching ──────────────────────────────────────────────────────

function showView(name) {
  ["projects", "project-detail", "analysis", "history"].forEach((v) => {
    const el = byId("view-" + v);
    if (el) el.hidden = v !== name;
    if (el) el.classList.toggle("active", v === name);
  });
  // Update nav buttons
  document.querySelectorAll("[data-view]").forEach((btn) => {
    const active = btn.dataset.view === name;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-current", active ? "page" : "false");
  });
}

// ── project list ────────────────────────────────────────────────────────

export async function loadProjects() {
  const loading = byId("projects-loading");
  const empty = byId("projects-empty");
  const error = byId("projects-error");
  const grid = byId("projects-grid");

  if (loading) loading.hidden = false;
  if (empty) empty.hidden = true;
  if (error) error.hidden = true;
  if (grid) grid.hidden = true;

  try {
    const payload = await api.get("/api/projects");
    const projects = Array.isArray(payload.projects) ? payload.projects : [];
    renderProjectCards(projects);
    if (loading) loading.hidden = true;
    if (projects.length === 0) {
      if (empty) empty.hidden = false;
    } else {
      if (grid) grid.hidden = false;
    }
  } catch (err) {
    if (loading) loading.hidden = true;
    if (error) {
      error.hidden = false;
      byId("projects-error-message").textContent = err.message || "加载项目列表失败";
    }
  }
}

function renderProjectCards(projects) {
  const grid = byId("projects-grid");
  if (!grid) return;
  clearChildren(grid);

  projects.forEach((project) => {
    const card = createElement("div", "project-card");
    card.setAttribute("tabindex", "0");
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", "打开项目 " + project.name);

    // Header
    const header = createElement("div", "project-card-header");
    const icon = createElement("div", "project-card-icon");
    icon.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="13" height="14" rx="2"/><path d="m16 10 5-3v10l-5-3z"/></svg>';
    header.append(icon);

    const badge = createElement(
      "span",
      "project-game-badge " + (project.game_type || "other"),
      gameTypeLabel(project.game_type)
    );
    header.append(badge);

    // Body
    const body = createElement("div", "project-card-body");
    const name = createElement("h3", "project-card-name", project.name);
    const meta = createElement("div", "project-card-meta");
    const date = createElement("span", "", "创建于 " + formatDate(project.created_at));
    meta.append(date);
    body.append(name, meta);

    // Actions
    const actions = createElement("div", "project-card-actions");
    const openBtn = createElement("button", "button primary small", "打开项目");
    openBtn.type = "button";
    openBtn.addEventListener("click", (e) => { e.stopPropagation(); openProject(project); });

    const moreBtn = createElement("button", "button ghost small", "⋯");
    moreBtn.type = "button";
    moreBtn.title = "更多操作";
    moreBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      showProjectMenu(card, project, moreBtn);
    });
    actions.append(openBtn, moreBtn);

    card.append(header, body, actions);

    card.addEventListener("click", () => openProject(project));
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openProject(project);
      }
    });

    grid.append(card);
  });
}

function gameTypeLabel(type) {
  const labels = { csgo: "CS2", valorant: "Valorant", other: "通用 FPS" };
  return labels[type] || "通用 FPS";
}

// ── project actions ─────────────────────────────────────────────────────

function showProjectMenu(card, project, anchorBtn) {
  // Remove any existing menus
  document.querySelectorAll(".project-context-menu").forEach((m) => m.remove());

  const menu = createElement("div", "project-context-menu");
  const renameBtn = createElement("button", "", "重命名");
  renameBtn.addEventListener("click", () => {
    menu.remove();
    promptRename(project);
  });
  const deleteBtn = createElement("button", "danger", "删除项目");
  deleteBtn.addEventListener("click", () => {
    menu.remove();
    confirmDelete(project);
  });
  menu.append(renameBtn, deleteBtn);

  const rect = anchorBtn.getBoundingClientRect();
  menu.style.position = "fixed";
  menu.style.top = (rect.bottom + 4) + "px";
  menu.style.right = (window.innerWidth - rect.right) + "px";

  document.body.append(menu);

  const closeMenu = (e) => {
    if (!menu.contains(e.target)) {
      menu.remove();
      document.removeEventListener("click", closeMenu);
    }
  };
  setTimeout(() => document.addEventListener("click", closeMenu), 0);
}

export async function createProject(name, gameType) {
  const button = byId("create-project-button");
  setButtonLoading(button, true, "创建中…");
  try {
    const payload = await api.post("/api/projects", { name, game_type: gameType });
    if (payload.project) {
      showToast("项目创建成功", "success");
      byId("project-dialog").close();
      await loadProjects();
      // Auto-open the new project
      openProject(payload.project);
    }
  } catch (err) {
    showToast(err.message || "创建项目失败", "error");
  } finally {
    setButtonLoading(button, false);
  }
}

async function promptRename(project) {
  const newName = window.prompt("请输入新项目名称：", project.name);
  if (!newName || newName.trim() === "" || newName.trim() === project.name) return;
  try {
    await api.patch("/api/projects/" + encodeURIComponent(project.id), {
      name: newName.trim(),
    });
    showToast("项目已重命名", "success");
    await loadProjects();
  } catch (err) {
    showToast(err.message || "重命名失败", "error");
  }
}

async function confirmDelete(project) {
  if (!window.confirm("确定要删除项目「" + project.name + "」吗？此操作可以撤销。")) return;
  try {
    await api.delete("/api/projects/" + encodeURIComponent(project.id));
    showToast("项目已删除", "success");
    await loadProjects();
  } catch (err) {
    showToast(err.message || "删除失败", "error");
  }
}

// ── project detail (jobs within project) ────────────────────────────────

export async function openProject(project) {
  appState.currentProjectId = project.id;
  appState.currentProjectName = project.name;
  appState.currentProject = project;

  showView("project-detail");
  byId("project-detail-name").textContent = project.name;
  byId("project-detail-game").textContent = gameTypeLabel(project.game_type);
  byId("project-detail-date").textContent = "创建于 " + formatDate(project.created_at);

  await loadProjectJobs(project.id);
}

async function loadProjectJobs(projectId) {
  const loading = byId("project-jobs-loading");
  const empty = byId("project-jobs-empty");
  const error = byId("project-jobs-error");
  const table = byId("project-jobs-table");

  if (loading) loading.hidden = false;
  if (empty) empty.hidden = true;
  if (error) error.hidden = true;
  if (table) table.hidden = true;

  try {
    const payload = await api.get("/api/jobs");
    const allJobs = Array.isArray(payload.jobs) ? payload.jobs : [];
    // For now, display all jobs since jobs aren't linked to projects in filesystem
    // In the future, filter by project_id
    const jobs = allJobs;
    renderProjectJobsTable(jobs);
    if (loading) loading.hidden = true;
    if (jobs.length === 0) {
      if (empty) empty.hidden = false;
    } else {
      if (table) table.hidden = false;
    }
  } catch (err) {
    if (loading) loading.hidden = true;
    if (error) {
      error.hidden = false;
      byId("project-jobs-error-msg").textContent = err.message || "加载任务列表失败";
    }
  }
}

function renderProjectJobsTable(jobs) {
  const tbody = byId("project-jobs-body");
  if (!tbody) return;
  clearChildren(tbody);

  const statusLabels = {
    created: "已创建", queued: "排队中", running: "分析中",
    completed: "已完成", failed: "失败",
  };

  jobs.forEach((job) => {
    const tr = document.createElement("tr");
    const statusClass = "history-status " + (job.status || "");
    tr.innerHTML =
      '<td>' + (job.project_name || "—") + '</td>' +
      '<td>' + (job.original_asset_name || job.asset_name || "—") + '</td>' +
      '<td><span class="' + statusClass + '">' + (statusLabels[job.status] || job.status || "未知") + '</span></td>' +
      '<td>' + formatDate(job.created_at) + '</td>' +
      '<td><div class="table-actions"></div></td>';

    const actions = tr.querySelector(".table-actions");
    if (job.status === "completed") {
      const openBtn = createElement("button", "button secondary small", "剪辑台");
      openBtn.type = "button";
      openBtn.addEventListener("click", () => {
        window.location.href = "/jobs/" + encodeURIComponent(job.job_id) + "/editor";
      });
      actions.append(openBtn);
    } else if (job.status === "failed") {
      const retryBtn = createElement("button", "button secondary small", "重试");
      retryBtn.type = "button";
      retryBtn.addEventListener("click", () => retryJob(job.job_id));
      actions.append(retryBtn);
    }
    const delBtn = createElement("button", "button ghost small", "删除");
    delBtn.type = "button";
    delBtn.addEventListener("click", () => deleteJobFromProject(job.job_id));
    actions.append(delBtn);

    tbody.append(tr);
  });
}

async function retryJob(jobId) {
  try {
    await api.post("/api/jobs/" + encodeURIComponent(jobId) + "/retry", {});
    showToast("任务已重新提交分析", "success");
    await loadProjectJobs(appState.currentProjectId);
  } catch (err) {
    showToast(err.message || "重试失败", "error");
  }
}

async function deleteJobFromProject(jobId) {
  if (!window.confirm("删除后将同时移除该任务的上传文件与输出结果，确定继续吗？")) return;
  try {
    await api.delete("/api/jobs/" + encodeURIComponent(jobId));
    showToast("任务已删除", "success");
    await loadProjectJobs(appState.currentProjectId);
  } catch (err) {
    showToast(err.message || "删除失败", "error");
  }
}

// ── create project dialog ───────────────────────────────────────────────

export function initProjectDialog() {
  const dialog = byId("project-dialog");
  const showBtn = byId("show-create-project-button");
  const closeBtn = byId("close-project-dialog-button");
  const submitBtn = byId("create-project-button");
  const cancelBtn = byId("cancel-project-button");

  if (showBtn) showBtn.addEventListener("click", () => dialog.showModal());
  if (closeBtn) closeBtn.addEventListener("click", () => dialog.close());
  if (cancelBtn) cancelBtn.addEventListener("click", () => dialog.close());
  if (dialog) {
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog) dialog.close();
    });
  }
  if (submitBtn) {
    submitBtn.addEventListener("click", () => {
      const name = byId("new-project-name").value.trim();
      const gameType = byId("new-project-game").value;
      if (!name) {
        showToast("请输入项目名称", "error");
        return;
      }
      createProject(name, gameType);
    });
  }
}

// ── navigate to analysis from project ───────────────────────────────────

export function startAnalysisInProject() {
  showView("analysis");
  // Keep project context in the upload form
  if (appState.currentProjectName) {
    byId("project-name").value = appState.currentProjectName;
  }
  if (appState.currentProject && appState.currentProject.game_type) {
    byId("game-type").value = appState.currentProject.game_type;
  }
}

// ── navigation ──────────────────────────────────────────────────────────

export function showProjectsView() {
  showView("projects");
  loadProjects();
}

export function backToProjectDetail() {
  if (appState.currentProjectId) {
    showView("project-detail");
    loadProjectJobs(appState.currentProjectId);
  } else {
    showProjectsView();
  }
}

export function showHistoryView() {
  showView("history");
  // dynamic import to avoid circular deps
  import("./history.js").then((m) => m.loadHistory());
}
