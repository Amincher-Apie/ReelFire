export const DEFAULT_VIDEO_FPS = 30;

export function editorShortcutAction(event = {}) {
  if (event.ctrlKey || event.metaKey || event.altKey) return null;

  if (event.key === " " || event.code === "Space") {
    return "toggle-playback";
  }
  if (event.key === "ArrowLeft" || event.code === "Numpad4") {
    return "step-backward";
  }
  if (event.key === "ArrowRight" || event.code === "Numpad6") {
    return "step-forward";
  }
  if (event.key === "ArrowUp" || event.code === "Numpad8") {
    return "previous-segment";
  }
  if (event.key === "ArrowDown" || event.code === "Numpad2") {
    return "next-segment";
  }
  return null;
}

export function adjacentSegmentIndex(
  segments,
  selectedSegmentId,
  direction,
) {
  if (!Array.isArray(segments) || segments.length === 0) return -1;

  const selectedIndex = segments.findIndex(
    (segment) => segment?.id === selectedSegmentId,
  );
  if (selectedIndex < 0) {
    return direction < 0 ? segments.length - 1 : 0;
  }

  return Math.max(
    0,
    Math.min(selectedIndex + (direction < 0 ? -1 : 1), segments.length - 1),
  );
}

export function steppedPlaybackTime(
  currentTime,
  duration,
  direction,
  fps = DEFAULT_VIDEO_FPS,
) {
  const current = Number(currentTime);
  const total = Number(duration);
  const frameRate = Number(fps);
  const safeCurrent = Number.isFinite(current) ? current : 0;
  const safeDuration = Number.isFinite(total) && total > 0 ? total : 0;
  const safeFps = Number.isFinite(frameRate) && frameRate > 0
    ? frameRate
    : DEFAULT_VIDEO_FPS;
  const delta = (direction < 0 ? -1 : 1) / safeFps;
  return Math.max(0, Math.min(safeCurrent + delta, safeDuration));
}

export function shouldIgnoreEditorShortcutTarget(target) {
  if (!target) return false;
  if (target.isContentEditable) return true;

  const tagName = String(target.tagName || "").toLowerCase();
  if (["input", "textarea", "select", "button", "a"].includes(tagName)) {
    return true;
  }

  return typeof target.closest === "function" && Boolean(target.closest(
    "[contenteditable='true'], [role='button'], [role='slider']",
  ));
}
