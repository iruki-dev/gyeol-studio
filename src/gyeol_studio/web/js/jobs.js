// Background jobs: polls the server and keeps the top-bar indicator and panel up to date.
// Views subscribe with onJobs(fn) to refresh when a job they care about changes.
import { api } from "./api.js";
import { h, clear, jobLine, toast, fmtEta } from "./ui.js";

let jobs = [];
const subs = new Set();
let timer = null;
const seenDone = new Set();

export function onJobs(fn) {
  subs.add(fn);
  fn(jobs);
  return () => subs.delete(fn);
}

export function currentJobs() {
  return jobs;
}

async function poll() {
  try {
    const r = await api.get("/api/jobs?mine=true");
    const prev = new Map(jobs.map((j) => [j.id, j]));
    jobs = r.jobs;
    for (const j of jobs) {
      const p = prev.get(j.id);
      if (p && p.status !== j.status && !seenDone.has(j.id)) {
        if (j.status === "failed") { toast(`${j.title}: ${j.error}`, { error: true, detail: j.error_detail || "" }); seenDone.add(j.id); }
        else if (j.status === "done" && /보컬 분리|모델 받기|학습/.test(j.title)) { toast(`${j.title} — 끝났어요`); seenDone.add(j.id); }
      }
    }
    renderIndicator();
    subs.forEach((f) => { try { f(jobs); } catch (e) { console.error(e); } });
  } catch (e) {
    /* offline: the next poll retries */
  }
  const active = jobs.some((j) => j.status === "queued" || j.status === "running");
  timer = setTimeout(poll, active ? 1200 : 4000);
}

export function pollNow() {
  clearTimeout(timer);
  poll();
}

function renderIndicator() {
  const btn = document.getElementById("jobs-btn");
  const active = jobs.filter((j) => j.status === "running" || j.status === "queued");
  btn.hidden = active.length === 0;
  if (!active.length) { document.getElementById("jobs-panel").hidden = true; return; }
  const run = active.find((j) => j.status === "running") || active[0];
  const pct = Math.round((run.progress || 0) * 100);
  clear(btn, h("span", { class: "spinner" }), `작업 ${active.length}개 · ${pct}%`);
  btn.title = `${run.title} — ${run.message} ${fmtEta(run.eta_s)}`;
  renderPanel();
}

function renderPanel() {
  const panel = document.getElementById("jobs-panel");
  if (panel.hidden) return;
  const list = jobs.filter((j) => ["queued", "running", "paused"].includes(j.status));
  clear(panel, h("h3", {}, "진행 중인 작업"), h("p", { class: "hint" }, "앱을 닫았다 열어도 이어서 진행돼요."),
    list.length ? list.map((j) => h("div", { class: "job" }, jobLine(j),
      j.status !== "paused" ? h("button", { class: "btn small ghost", onclick: async () => { await api.post(`/api/jobs/${j.id}/cancel`); pollNow(); } }, "취소") : null))
      : h("p", {}, "진행 중인 작업이 없어요."));
}

export function startJobs() {
  const btn = document.getElementById("jobs-btn");
  const panel = document.getElementById("jobs-panel");
  btn.addEventListener("click", (e) => { e.stopPropagation(); panel.hidden = !panel.hidden; renderPanel(); });
  document.addEventListener("click", (e) => { if (!panel.hidden && !panel.contains(e.target)) panel.hidden = true; });
  poll();
}
