// ReelFire — user session helpers
import api from "../api/client.js";
import { byId } from "./dom.js";

export async function loadUser() {
  try {
    const payload = await api.get("/api/auth/me");
    byId("user-name").textContent = payload.user.display_name || payload.user.username;
    byId("user-info").hidden = false;
    byId("login-link").hidden = true;
  } catch {
    byId("user-info").hidden = true;
    byId("login-link").hidden = false;
  }
}
