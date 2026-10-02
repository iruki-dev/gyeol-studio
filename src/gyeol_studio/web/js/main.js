import { api } from "./api.js";
import { store } from "./store.js";
import { route, render, go } from "./router.js";
import { startJobs } from "./jobs.js";
import { h, clear, initials, showError } from "./ui.js";
import { userSwitcher } from "./views/welcome.js";

route("library", () => import("./views/library.js"));
route("song", () => import("./views/song.js"));
route("phrase", () => import("./views/practice.js"));
route("take", () => import("./views/practice.js"));
route("welcome", () => import("./views/welcome.js"));
route("setup", () => import("./views/setup.js"));
route("settings", () => import("./views/settings.js"));
route("connect", () => import("./views/connect.js"));
route("check", () => import("./views/check.js"));
route("history", () => import("./views/history.js"));
route("data", () => import("./views/data.js"));
route("training", () => import("./views/training.js"));

export const app = { status: null, user: null };

export async function refreshUser() {
  const id = store.userId();
  app.user = null;
  if (id) {
    try { app.user = await api.get(`/api/users/${id}`); } catch { store.setUser(null); }
  }
  const btn = document.getElementById("user-btn");
  if (app.user) clear(btn, h("span", { class: "avatar" }, initials(app.user.name)), h("span", { class: "name" }, app.user.name));
  else clear(btn, h("span", { class: "avatar" }, "?"), h("span", { class: "name" }, "사용자 선택"));
  return app.user;
}

async function boot() {
  document.getElementById("user-btn").addEventListener("click", () => userSwitcher());
  try {
    app.status = await api.get("/api/status");
  } catch (e) {
    showError(e);
  }
  await refreshUser();
  startJobs();
  const hash = location.hash.replace(/^#\/?/, "");
  if (!app.user && !hash.startsWith("connect")) {
    go("#/welcome");
  } else if (app.status && !app.status.weights_ready && !app.status.setup_seen && !hash) {
    go("#/setup");
  } else {
    render();
  }
}

store.on((k) => { if (k === "user") refreshUser(); });
boot();
