// ReelFire — auth page entry point
import { initTheme } from "./utils/theme.js";
import { initAuth } from "./views/auth.js";

if (document.body.dataset.page === "auth") {
  initTheme();
  initAuth();
}
