// Song library: upload a song (separated into vocal + accompaniment in the background), see progress, open a song.
import { api, uploadWithProgress } from "../api.js";
import { onJobs, pollNow } from "../jobs.js";
import { go } from "../router.js";
import { h, clear, modal, jobLine, showError, toast, icon, fmtTime } from "../ui.js";

const STATUS = {
  queued: ["준비 중", ""], separating: ["보컬 분리 중", "accent"], ready: ["준비됨", "ok"], failed: ["실패", "err"],
  waiting_weights: ["모델을 기다리는 중", "warn"], cancelled: ["취소됨", "warn"],
};

export function uploadDialog() {
  const file = h("input", { type: "file", accept: "audio/*,.mp3,.wav,.flac,.ogg,.m4a", hidden: true });
  const fileLabel = h("div", {}, h("b", {}, "음원 파일을 여기에 끌어 놓거나 눌러서 고르세요"), h("div", { class: "hint" }, "MP3, WAV, FLAC, OGG · 15분 이하"));
  const drop = h("div", { class: "drop", tabindex: "0", role: "button", onclick: () => file.click(),
    onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") file.click(); } }, fileLabel);
  const title = h("input", { type: "text", maxlength: 120, placeholder: "예: 너의 의미" });
  const artist = h("input", { type: "text", maxlength: 120, placeholder: "예: 아이유" });
  const key = h("input", { type: "text", maxlength: 20, placeholder: "예: C, A♭m" });
  const vocalOnly = h("input", { type: "checkbox" });
  const prog = h("div", { class: "progress", hidden: true }, h("i", { style: { width: "0%" } }));
  const ok = h("button", { class: "btn primary", type: "submit" }, "올리기");
  let chosen = null;
  const pick = (f) => {
    if (!f) return;
    chosen = f;
    clear(fileLabel, h("b", {}, f.name), h("div", { class: "hint" }, `${(f.size / 1e6).toFixed(1)}MB · 다른 파일을 고르려면 누르세요`));
    if (!title.value) title.value = f.name.replace(/\.[^.]+$/, "").slice(0, 120);
  };
  file.addEventListener("change", () => pick(file.files[0]));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); pick(e.dataTransfer.files[0]); });
  const form = h("form", {
    onsubmit: async (e) => {
      e.preventDefault();
      if (!chosen) { toast("음원 파일을 골라 주세요.", { error: true }); return; }
      ok.disabled = true;
      prog.hidden = false;
      const fd = new FormData();
      fd.append("file", chosen);
      fd.append("title", title.value.trim());
      fd.append("artist", artist.value.trim());
      fd.append("song_key", key.value.trim());
      fd.append("vocal_only", vocalOnly.checked ? "true" : "false");
      try {
        const s = await uploadWithProgress("/api/songs", fd, (f) => { prog.firstChild.style.width = `${Math.round(f * 100)}%`; });
        m.close();
        toast("곡을 추가했어요. 보컬 분리가 끝나기 전에도 소절을 만들 수 있어요.");
        pollNow();
        go(`#/song/${s.id}`);
      } catch (err) { showError(err); ok.disabled = false; prog.hidden = true; }
    },
  },
  h("h2", {}, "곡 추가"),
  drop, file,
  h("div", { style: { height: "14px" } }),
  h("label", { class: "field" }, h("span", {}, "제목"), title),
  h("div", { class: "row" },
    h("label", { class: "field", style: { flex: "2 1 200px" } }, h("span", {}, "가수"), artist),
    h("label", { class: "field", style: { flex: "1 1 120px" } }, h("span", {}, "키"), key, h("small", { class: "muted" }, "곡의 조(으뜸음). 몰라도 돼요."))),
  h("details", { class: "adv" }, h("summary", {}, "고급"),
    h("label", { class: "check", style: { marginTop: "10px" } }, vocalOnly, h("div", {}, h("b", {}, "목소리만 있는 파일이에요"),
      h("small", {}, "반주 없이 노래만 녹음된 파일(아카펠라, 가이드 보컬)이면 고르세요. 보컬 분리를 건너뛰어요.")))),
  prog,
  h("div", { class: "modal-actions" }, h("button", { class: "btn", type: "button", onclick: () => m.close() }, "취소"), ok));
  const m = modal(form);
}

function songCard(s) {
  const [label, tone] = STATUS[s.status] || [s.status, ""];
  const job = s.job && ["queued", "running"].includes(s.job.status) ? s.job : null;
  return h("a", { class: "card song-card", href: `#/song/${s.id}` },
    h("div", { class: "row between" }, h("span", { class: "title" }, s.title), h("span", { class: `badge ${tone}` }, label)),
    h("div", { class: "sub" }, [s.artist, s.song_key ? `키 ${s.song_key}` : "", fmtTime(s.duration_s)].filter(Boolean).join(" · ")),
    job ? jobLine(job, { title: false }) : null,
    s.status === "failed" ? h("div", { class: "hint" }, s.error) : null,
    s.status === "waiting_weights" ? h("div", { class: "hint" }, "보컬 분리 모델을 받으면 자동으로 시작해요.") : null,
    h("div", { class: "hint" }, s.n_phrases ? `소절 ${s.n_phrases}개` : "아직 소절이 없어요"));
}

export async function render(view) {
  const list = h("div", { class: "grid" });
  const addBtn = h("button", { class: "btn primary", onclick: uploadDialog, "data-tour": "add-song" }, icon("plus"), "곡 추가");
  clear(view, h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "곡 보관함"), h("p", {}, "연습할 곡을 올리고, 따라 부를 소절을 골라요.")), addBtn), list);
  let last = "";
  async function load() {
    const { songs } = await api.get("/api/songs");
    const sig = JSON.stringify(songs.map((s) => [s.id, s.status, s.n_phrases, s.job && [s.job.status, Math.round((s.job.progress || 0) * 50)]]));
    if (sig === last) return;
    last = sig;
    if (!songs.length) {
      clear(list, h("div", { class: "card empty", style: { gridColumn: "1/-1" } }, h("h2", {}, "아직 곡이 없어요"),
        h("p", {}, "연습하고 싶은 곡의 음원 파일을 올려 주세요. 앱이 가수 목소리와 반주를 나눠 줘요."),
        h("button", { class: "btn primary", onclick: uploadDialog }, icon("plus"), "첫 곡 추가하기")));
      return;
    }
    clear(list, songs.map(songCard));
  }
  await load();
  const off = onJobs(() => load().catch(() => {}));
  return off;
}
