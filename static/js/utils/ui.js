// ReelFire — UI helpers
import { byId, createElement } from "./dom.js";

export function showToast(message, type = "info") {
  const container = byId("toast-container");
  if (!container) return;
  const toast = createElement("div", `toast ${type}`, message);
  container.append(toast);
  window.setTimeout(() => toast.remove(), 4200);
}

export function setButtonLoading(button, loading, loadingLabel) {
  if (!button) return;
  const label = button.querySelector(".button-label") || button;
  if (!button.dataset.originalLabel) {
    button.dataset.originalLabel = label.textContent.trim();
  }
  button.disabled = loading;
  button.classList.toggle("is-loading", loading);
  label.textContent = loading ? loadingLabel : button.dataset.originalLabel;
}
