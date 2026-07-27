// ReelFire — auth page: login, register, guest
import api from "../api/client.js";
import { byId, createElement } from "../utils/dom.js";
import { showToast, setButtonLoading } from "../utils/ui.js";

function selectAuthView(view) {
  const login = view === "login";
  byId("login-form").hidden = !login;
  byId("register-form").hidden = login;
  byId("login-tab").classList.toggle("active", login);
  byId("register-tab").classList.toggle("active", !login);
  byId("login-tab").setAttribute("aria-selected", String(login));
  byId("register-tab").setAttribute("aria-selected", String(!login));
  byId("auth-title").textContent = login ? "登录 ReelFire" : "创建 ReelFire 账号";
  byId("auth-description").textContent = login
    ? "使用项目账号进入分析工作台。"
    : "创建当前运行环境中的项目账号。";
  byId(login ? "login-username" : "register-username").focus();
}

function authRedirectTarget() {
  const value = new URLSearchParams(window.location.search).get("next");
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/";
  try {
    const target = new URL(value, window.location.origin);
    if (target.origin !== window.location.origin) return "/";
    return `${target.pathname}${target.search}${target.hash}`;
  } catch {
    return "/";
  }
}

async function submitAuth(form, mode) {
  const isLogin = mode === "login";
  const prefix = isLogin ? "login" : "register";
  const username = byId(`${prefix}-username`).value.trim();
  const password = byId(`${prefix}-password`).value;
  const error = byId(`${prefix}-error`);
  const button = byId(`${prefix}-submit`);
  error.textContent = "";

  if (username.length < 2 || username.length > 32) {
    error.textContent = "用户名长度需为 2–32 个字符。";
    return;
  }
  if (password.length < 6) {
    error.textContent = "密码至少需要 6 个字符。";
    return;
  }
  if (!isLogin && password !== byId("register-confirm").value) {
    error.textContent = "两次输入的密码不一致。";
    return;
  }

  setButtonLoading(button, true, isLogin ? "正在登录…" : "正在创建…");
  try {
    await api.post(`/api/auth/${mode}`, { username, password });
    showToast(isLogin ? "登录成功" : "账号创建成功", "success");
    window.location.assign(authRedirectTarget());
  } catch (requestError) {
    error.textContent = requestError.message;
  } finally {
    setButtonLoading(button, false);
  }
}

async function submitGuestLogin() {
  const button = byId("guest-submit");
  const error = byId("guest-error");
  error.textContent = "";
  setButtonLoading(button, true, "正在创建游客空间…");
  try {
    await api.post("/api/auth/guest", {});
    showToast("已进入独立游客空间", "success");
    window.location.assign(authRedirectTarget());
  } catch (requestError) {
    error.textContent = requestError.message;
  } finally {
    setButtonLoading(button, false);
  }
}

export function initAuth() {
  byId("login-tab").addEventListener("click", () => selectAuthView("login"));
  byId("register-tab").addEventListener("click", () => selectAuthView("register"));
  byId("login-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitAuth(event.currentTarget, "login");
  });
  byId("register-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitAuth(event.currentTarget, "register");
  });
  byId("guest-submit").addEventListener("click", submitGuestLogin);
}
