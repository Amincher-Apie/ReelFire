// ReelFire — auth page entry point
import { initTheme } from "./utils/theme.js";
import { initAuth } from "./views/auth.js";

initTheme();
if (document.body.dataset.page === "auth") initAuth();
