// ReelFire - shared top-level workspace navigation.
import { byId } from "../utils/dom.js";

const VIEW_NAMES = ["projects", "analysis"];

export function showAppView(requestedView) {
  const view = VIEW_NAMES.includes(requestedView) ? requestedView : "projects";

  VIEW_NAMES.forEach((name) => {
    const section = byId("view-" + name);
    if (!section) return;
    const active = name === view;
    section.hidden = !active;
    section.classList.toggle("active", active);
  });

  document.body.dataset.workspaceView = view;
  document.querySelectorAll("[data-view]").forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle("active", active);
    if (active) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });
}
