// ReelFire — DOM utilities
export function byId(id) {
  return document.getElementById(id);
}

export function clearChildren(element) {
  if (element) element.replaceChildren();
}

export function createElement(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = String(text);
  return el;
}

export function safeOn(id, event, handler) {
  const el = byId(id);
  if (el) el.addEventListener(event, handler);
}
