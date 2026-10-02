// First-run preparation: download the vocal-separation model (gyeol fetch) with progress.
import { api } from "../api.js";
import { onJobs, pollNow } from "../jobs.js";
import { go } from "../router.js";
import { h, clear, jobLine, showError } from "../ui.js";

export async function render(view) {
  const box = h("div", { class: "card", style: { maxWidth: "640px" } });
  clear(view, h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "처음 한 번 준비가 필요해요"),
    h("p", {}, "곡에서 가수 목소리와 반주를 나누는 모델(약 640MB)을 받아요."))), box);
  let started = false;

  async function draw(jobs) {
    const st = await api.get("/api/status");
    const w = st.weights[0];
    const job = jobs.find((j) => j.kind === "fetch_weights" && ["queued", "running"].includes(j.status)) || st.fetch_job;
    clear(box);
    if (w.present) {
      box.append(h("div", { class: "notice ok" }, h("span", { class: "ico" }, "✓"), h("div", {}, h("b", {}, "준비가 끝났어요."), " 이제 곡을 추가할 수 있어요.")),
        h("button", { class: "btn primary big", onclick: async () => { await api.post("/api/setup/seen"); go("#/"); } }, "곡 보관함으로"));
      return;
    }
    box.append(h("dl", { class: "kv" }, h("dt", {}, "모델"), h("dd", {}, w.label), h("dt", {}, "크기"), h("dd", {}, "약 640MB"),
      h("dt", {}, "라이선스"), h("dd", {}, w.license), h("dt", {}, "출처"), h("dd", { class: "hint" }, w.source)));
    if (job && ["queued", "running"].includes(job.status)) {
      box.append(h("div", { style: { marginTop: "16px" } }, jobLine(job, { title: false })),
        h("p", { class: "hint" }, "받는 동안 다른 화면을 써도 돼요. 앱을 닫으면 다음에 열 때 처음부터 다시 받아요."));
    } else {
      if (job && job.status === "failed") box.append(h("div", { class: "notice err" }, h("span", { class: "ico" }, "!"), job.error));
      box.append(h("div", { class: "row", style: { marginTop: "16px" } },
        h("button", { class: "btn primary big", onclick: start }, job && job.status === "failed" ? "다시 받기" : "받기 시작"),
        h("button", { class: "btn ghost", onclick: async () => { await api.post("/api/setup/seen"); go("#/"); } }, "나중에 하기")),
      h("p", { class: "hint" }, "나중에 하면 '목소리만 있는 파일'로만 곡을 추가할 수 있어요. 설정 → 모델에서 언제든 받을 수 있어요."));
    }
  }

  async function start() {
    try { await api.post("/api/weights/fetch"); started = true; pollNow(); } catch (e) { showError(e); }
  }

  const off = onJobs((jobs) => draw(jobs).catch(showError));
  if (!started) {
    const st = await api.get("/api/status");
    if (!st.weights_ready && !(st.fetch_job && ["queued", "running"].includes(st.fetch_job.status))) start();
  }
  return off;
}
