// ReelFire — theme initialization
export function initTheme() {
  const allowed = new Set(["dark", "light", "ocean", "forest"]);
  const saved = localStorage.getItem("reelfire-theme");
  const theme = allowed.has(saved) ? saved : "dark";
  document.body.dataset.theme = theme;
  document.querySelectorAll("[data-theme-value]").forEach((button) => {
    const active = button.dataset.themeValue === theme;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
    button.addEventListener("click", () => {
      const next = button.dataset.themeValue;
      if (!allowed.has(next)) return;
      document.body.dataset.theme = next;
      localStorage.setItem("reelfire-theme", next);
      document.querySelectorAll("[data-theme-value]").forEach((item) => {
        const selected = item.dataset.themeValue === next;
        item.classList.toggle("active", selected);
        item.setAttribute("aria-pressed", String(selected));
      });
    });
  });
}
