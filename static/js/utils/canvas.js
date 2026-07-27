// ReelFire — Canvas utilities
export function getCanvasColors() {
  const style = getComputedStyle(document.body);
  return {
    bg: style.getPropertyValue("--bg").trim() || "#080b14",
    panel: style.getPropertyValue("--panel-soft").trim() || "#101727",
    text: style.getPropertyValue("--text").trim() || "#f7f8fc",
    textMuted: style.getPropertyValue("--text-muted").trim() || "#9ba6bc",
    textFaint: style.getPropertyValue("--text-faint").trim() || "#6e7890",
    border: style.getPropertyValue("--border").trim() || "rgba(255,255,255,0.1)",
    primary: style.getPropertyValue("--primary").trim() || "#ff4d70",
    accent: style.getPropertyValue("--accent").trim() || "#66a6ff",
    success: style.getPropertyValue("--success").trim() || "#35d399",
    warning: style.getPropertyValue("--warning").trim() || "#f5bd4f",
    danger: style.getPropertyValue("--danger").trim() || "#ff667d",
  };
}

export function setupHiDPI(canvas, width, height) {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = width + "px";
  canvas.style.height = height + "px";
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  return ctx;
}
