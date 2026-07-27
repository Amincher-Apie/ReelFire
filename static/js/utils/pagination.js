function positiveInteger(value, fallback) {
  const parsed = Number.parseInt(String(value), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function paginate(items, requestedPage = 1, requestedPageSize = 5) {
  const source = Array.isArray(items) ? items : [];
  const pageSize = positiveInteger(requestedPageSize, 5);
  const pageCount = Math.max(1, Math.ceil(source.length / pageSize));
  const page = Math.min(
    pageCount,
    Math.max(1, positiveInteger(requestedPage, 1)),
  );
  const startIndex = (page - 1) * pageSize;
  const endIndex = Math.min(source.length, startIndex + pageSize);

  return {
    items: source.slice(startIndex, endIndex),
    page,
    pageSize,
    pageCount,
    total: source.length,
    startIndex,
    endIndex,
  };
}

export function pageForIndex(index, pageSize = 5) {
  const safeIndex = Math.max(0, Number(index) || 0);
  return Math.floor(safeIndex / positiveInteger(pageSize, 5)) + 1;
}

function makeButton(label, className, disabled, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  button.disabled = disabled;
  button.addEventListener("click", onClick);
  return button;
}

export function renderPagination(container, options) {
  if (!container) return;

  const total = Math.max(0, Number(options.total) || 0);
  const pageSize = positiveInteger(options.pageSize, 5);
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(
    pageCount,
    Math.max(1, positiveInteger(options.page, 1)),
  );
  const start = total ? (page - 1) * pageSize + 1 : 0;
  const end = Math.min(total, page * pageSize);
  const itemLabel = options.itemLabel || "项";
  const adjustable = options.adjustable !== false;

  container.replaceChildren();
  container.hidden = total === 0 || (!adjustable && pageCount <= 1);
  if (container.hidden) return;

  container.setAttribute("role", "navigation");
  container.setAttribute("aria-label", options.ariaLabel || "分页");

  const summary = document.createElement("span");
  summary.className = "pagination-summary";
  summary.setAttribute("aria-live", "polite");
  summary.textContent = `${start}-${end} / ${total} ${itemLabel}`;

  const controls = document.createElement("div");
  controls.className = "pagination-controls";

  if (adjustable) {
    const sizeLabel = document.createElement("label");
    sizeLabel.className = "pagination-size";
    const labelText = document.createElement("span");
    labelText.textContent = "每页";
    const input = document.createElement("input");
    input.type = "number";
    input.min = "1";
    input.step = "1";
    input.inputMode = "numeric";
    input.value = String(pageSize);
    input.setAttribute("aria-label", `每页显示${itemLabel}数量`);
    const applySize = () => {
      const nextSize = positiveInteger(input.value, pageSize);
      input.value = String(nextSize);
      if (nextSize !== pageSize) options.onPageSizeChange?.(nextSize);
    };
    input.addEventListener("change", applySize);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        applySize();
        input.blur();
      }
    });
    sizeLabel.append(labelText, input);
    controls.append(sizeLabel);
  }

  const pageStatus = document.createElement("span");
  pageStatus.className = "pagination-page";
  pageStatus.textContent = `${page} / ${pageCount}`;

  controls.append(
    makeButton(
      "上一页",
      "button ghost small pagination-button",
      page <= 1,
      () => options.onPageChange?.(page - 1),
    ),
    pageStatus,
    makeButton(
      "下一页",
      "button ghost small pagination-button",
      page >= pageCount,
      () => options.onPageChange?.(page + 1),
    ),
  );
  container.append(summary, controls);
}
