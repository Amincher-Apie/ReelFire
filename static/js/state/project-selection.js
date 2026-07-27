import { appState } from "./app-state.js";
import { byId } from "../utils/dom.js";

const STORAGE_KEY = "reelfire-selected-project";

function normalizedProject(project) {
  if (!project || project.id == null) return null;
  return {
    id: project.id,
    name: String(project.name || "未命名项目"),
    game_type: project.game_type || "other",
    created_at: project.created_at || null,
    updated_at: project.updated_at || null,
  };
}

function renderProjectContext() {
  const badge = byId("project-context");
  if (!badge) return;
  if (!appState.currentProject) {
    badge.hidden = true;
    badge.textContent = "";
    return;
  }
  badge.textContent = `当前项目：${appState.currentProject.name}`;
  badge.title = appState.currentProject.name;
  badge.hidden = false;
}

export function setSelectedProject(project, { persist = true } = {}) {
  const normalized = normalizedProject(project);
  appState.currentProject = normalized;
  appState.currentProjectId = normalized ? normalized.id : null;
  appState.currentProjectName = normalized ? normalized.name : null;

  if (persist) {
    try {
      if (normalized) {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
      } else {
        window.localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      // The in-memory selection remains usable when storage is unavailable.
    }
  }

  renderProjectContext();
  window.dispatchEvent(new CustomEvent("reelfire:project-selected", {
    detail: normalized,
  }));
  return normalized;
}

export function restoreSelectedProject(projects = []) {
  if (appState.currentProjectId != null) {
    const current = projects.find(
      (project) => String(project.id) === String(appState.currentProjectId),
    );
    if (current) return setSelectedProject(current);
  }

  let stored = null;
  try {
    stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null");
  } catch {
    stored = null;
  }
  const match = stored && projects.find(
    (project) => String(project.id) === String(stored.id),
  );
  return setSelectedProject(match || null);
}

export function clearSelectedProject() {
  setSelectedProject(null);
}

export function refreshProjectContext() {
  renderProjectContext();
}
