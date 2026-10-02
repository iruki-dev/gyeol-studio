// One song: waveform, drag to choose a phrase, type its lyrics, save; list of phrases to practise.
import { api } from "../api.js";
import { onJobs } from "../jobs.js";
import { go } from "../router.js";
import { h, clear, showError, toast, icon, fmtTime, jobLine, confirmDialog, modal } from "../ui.js";
import { Waveform } from "../waveform.js";

const PHRASE_STATUS = { waiting: ["보컬 분리를 기다리는 중", "warn"], queued: ["목표 분석 준비 중", ""], analyzing: ["목표 분석 중", "accent"],
  ready: ["연습할 수 있어요", "ok"], failed: ["분석 실패", "err"], cancelled: ["취소됨", "warn"] };
const SONG_STATUS = { queued: "보컬 분리 준비 중", separating: "보컬과 반주를 나누는 중", ready: "보컬 분리 완료", failed: "보컬 분리 실패",
  waiting_weights: "보컬 분리 모델을 기다리는 중", cancelled: "보컬 분리 취소됨" };

export async function render(view, [songId]) {
  let song = await api.get(`/api/songs/${songId}`);
  const peaks = await api.get(`/api/songs/${songId}/peaks`);
  const audioEl = h("audio", { src: `/api/songs/${songId}/audio?stem=mix`, preload: "auto" });
  let stopAt = null;
  let raf = 0;

  // ----- header & separation status
  const statusBox = h("div");
  const head = h("div", { class: "page-head" },
    h("div", {}, h("a", { href: "#/", class: "btn ghost small" }, icon("back"), "곡 보관함"), h("h1", {}, song.title),
      h("p", {}, [song.artist, song.song_key ? `키 ${song.song_key}` : "", fmtTime(song.duration_s)].filter(Boolean).join(" · "))),
    h("div", { class: "row" },
      h("button", { class: "btn small", onclick: editSong }, "곡 정보 고치기"),
      h("button", { class: "btn small danger", onclick: removeSong }, icon("trash"), "곡 지우기")));

  // ----- waveform & selection form
  const waveBox = h("div", { class: "wave-wrap" });
  const wf = new Waveform(waveBox, {
    peaks: peaks.peaks, duration: peaks.duration_s, height: 150,
    onSelect: (s) => { setSel(s.start, s.end); },
    onSeek: (t) => { audioEl.currentTime = t; wf.setPlayhead(t); },
  });
  const zoomSeg = h("div", { class: "seg", role: "group", "aria-label": "확대" });
  const zooms = [["전체", 0], ["30초", 30], ["10초", 10]];
  let zoom = song.duration_s > 60 ? 30 : 0;
  const scroll = h("input", { type: "range", min: 0, max: 1000, value: 0, "aria-label": "보이는 구간 옮기기" });
  function applyZoom() {
    zoomSeg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.z) === zoom)));
    const span = zoom || song.duration_s;
    scroll.hidden = !zoom || span >= song.duration_s;
    const t0 = (Number(scroll.value) / 1000) * Math.max(0, song.duration_s - span);
    wf.setView(t0, t0 + span);
  }
  for (const [label, z] of zooms) zoomSeg.append(h("button", { type: "button", "data-z": z, onclick: () => { zoom = z; centerOn(cur.start ?? 0); } }, label));
  scroll.addEventListener("input", applyZoom);
  function centerOn(t) {
    const span = zoom || song.duration_s;
    const t0 = Math.max(0, Math.min(song.duration_s - span, t - span / 3));
    scroll.value = String(song.duration_s > span ? (t0 / (song.duration_s - span)) * 1000 : 0);
    applyZoom();
  }

  const cur = { start: null, end: null };
  const startIn = h("input", { type: "number", step: "0.05", min: 0, "aria-label": "시작(초)" });
  const endIn = h("input", { type: "number", step: "0.05", min: 0, "aria-label": "끝(초)" });
  const lyrics = h("input", { type: "text", maxlength: 300, placeholder: "예: 사랑해요 그대" });
  const name = h("input", { type: "text", maxlength: 60, placeholder: "예: 후렴 첫 줄" });
  const lenInfo = h("small", { class: "muted" });
  function setSel(s, e) {
    cur.start = Math.max(0, Math.round(s * 20) / 20);
    cur.end = Math.min(song.duration_s, Math.round(e * 20) / 20);
    startIn.value = cur.start.toFixed(2);
    endIn.value = cur.end.toFixed(2);
    wf.setSelection({ start: cur.start, end: cur.end });
    const len = cur.end - cur.start;
    lenInfo.textContent = `길이 ${len.toFixed(1)}초` + (len > 30 ? " — 30초 이하로 줄여 주세요" : len < 0.5 ? " — 너무 짧아요" : "");
  }
  startIn.addEventListener("change", () => setSel(Number(startIn.value), cur.end ?? Number(startIn.value) + 4));
  endIn.addEventListener("change", () => setSel(cur.start ?? Math.max(0, Number(endIn.value) - 4), Number(endIn.value)));
  const nudge = (which, d) => () => which === "s" ? setSel((cur.start ?? 0) + d, cur.end ?? (cur.start ?? 0) + 4) : setSel(cur.start ?? 0, (cur.end ?? 4) + d);

  function playRange(a, b) {
    audioEl.currentTime = a;
    stopAt = b;
    audioEl.play().catch(showError);
  }
  function tick() {
    wf.setPlayhead(audioEl.currentTime);
    if (stopAt !== null && audioEl.currentTime >= stopAt) { audioEl.pause(); stopAt = null; }
    raf = requestAnimationFrame(tick);
  }
  raf = requestAnimationFrame(tick);
  const playBtn = h("button", { class: "btn", type: "button", onclick: () => {
    if (!audioEl.paused) { audioEl.pause(); return; }
    if (cur.start !== null) playRange(cur.start, cur.end); else audioEl.play();
  } }, icon("play"), "들어 보기");
  audioEl.addEventListener("play", () => clear(playBtn, icon("pause"), "멈추기"));
  audioEl.addEventListener("pause", () => clear(playBtn, icon("play"), "들어 보기"));

  const saveBtn = h("button", { class: "btn primary", type: "submit", "data-tour": "save-phrase" }, "소절 저장");
  const form = h("form", { class: "card", onsubmit: async (e) => {
    e.preventDefault();
    if (cur.start === null || cur.end === null) { toast("파형에서 끌어서 구간을 먼저 골라 주세요.", { error: true }); return; }
    saveBtn.disabled = true;
    try {
      const p = await api.post(`/api/songs/${songId}/phrases`, { start_s: cur.start, end_s: cur.end, lyrics: lyrics.value, name: name.value });
      toast(song.status === "ready" ? "소절을 저장했어요. 목표 분석이 끝나면 연습할 수 있어요." : "소절을 저장했어요. 보컬 분리가 끝나면 목표 분석을 시작해요.");
      lyrics.value = ""; name.value = "";
      cur.start = cur.end = null; startIn.value = endIn.value = ""; lenInfo.textContent = "";
      wf.setSelection(null);
      await reload();
      highlight(p.id);
    } catch (err) { showError(err); }
    saveBtn.disabled = false;
  } },
  h("h2", {}, "소절 만들기"),
  h("p", { class: "hint" }, "파형에서 부르고 싶은 부분을 끌어서 고르세요. 가장자리를 끌면 길이를 고칠 수 있어요. 한 번 누르면 그 위치부터 들을 수 있어요."),
  h("div", { class: "row between", style: { marginBottom: "8px" } }, zoomSeg, playBtn),
  waveBox, scroll,
  h("div", { class: "row", style: { marginTop: "12px" } },
    h("label", { class: "field" }, h("span", {}, "시작"), h("div", { class: "timefield" },
      h("button", { type: "button", class: "btn small", onclick: nudge("s", -0.1), "aria-label": "시작 0.1초 앞으로" }, "−"), startIn,
      h("button", { type: "button", class: "btn small", onclick: nudge("s", 0.1), "aria-label": "시작 0.1초 뒤로" }, "+"))),
    h("label", { class: "field" }, h("span", {}, "끝"), h("div", { class: "timefield" },
      h("button", { type: "button", class: "btn small", onclick: nudge("e", -0.1), "aria-label": "끝 0.1초 앞으로" }, "−"), endIn,
      h("button", { type: "button", class: "btn small", onclick: nudge("e", 0.1), "aria-label": "끝 0.1초 뒤로" }, "+"))),
    lenInfo),
  h("label", { class: "field" }, h("span", {}, "가사"), lyrics, h("small", { class: "muted" }, "이 구간에서 부르는 가사를 적어 주세요. 음마다 글자를 붙여서 피드백에 '사'가 낮아요처럼 보여줘요.")),
  h("details", { class: "adv" }, h("summary", {}, "고급"), h("label", { class: "field", style: { marginTop: "10px" } }, h("span", {}, "소절 이름"), name,
    h("small", { class: "muted" }, "비워 두면 '1번째 소절'처럼 붙여요."))),
  h("div", { class: "row", style: { marginTop: "8px" } }, saveBtn));

  const listBox = h("div", { class: "phrase-list" });
  clear(view, audioEl, head, statusBox, h("div", { class: "two-col" }, form, h("div", { class: "card" }, h("h2", {}, "소절"), listBox)));
  applyZoom();

  function phraseItem(p) {
    const [label, tone] = PHRASE_STATUS[p.status] || [p.status, ""];
    const job = p.job && ["queued", "running"].includes(p.job.status) ? p.job : null;
    return h("div", { class: "phrase-item", id: `ph-${p.id}` },
      h("div", { style: { minWidth: 0, flex: "1" } },
        h("div", { class: "lyr" }, p.lyrics || p.name),
        h("div", { class: "hint" }, `${p.name} · ${fmtTime(p.start_s)}–${fmtTime(p.end_s)} · `, h("span", { class: `badge ${tone}` }, label),
          p.n_takes ? ` · 녹음 ${p.n_takes}개` : ""),
        job ? jobLine(job, { title: false }) : null,
        p.status === "failed" ? h("div", { class: "hint" }, p.error, " ", h("button", { class: "btn small", onclick: async () => {
          try { await api.post(`/api/phrases/${p.id}/retry`); reload(); } catch (e) { showError(e); } } }, "다시 분석")) : null),
      h("div", { class: "row" },
        h("button", { class: "play-btn", title: "들어 보기", "aria-label": "들어 보기", onclick: () => { centerOn(p.start_s); playRange(p.start_s, p.end_s); }, html: '<svg viewBox="0 0 24 24"><path d="M7 4.5v15l13-7.5z" fill="currentColor"/></svg>' }),
        h("button", { class: "btn small", onclick: () => editPhrase(p) }, "고치기"),
        h("a", { class: "btn small primary", href: `#/phrase/${p.id}`, "aria-disabled": p.status !== "ready" ? "true" : null,
          onclick: (e) => { if (p.status !== "ready") { e.preventDefault(); toast("목표 분석이 끝나면 연습할 수 있어요."); } } }, "연습하기")));
  }

  function highlight(id) {
    const el = document.getElementById(`ph-${id}`);
    if (el) { el.classList.add("selected"); el.scrollIntoView({ block: "nearest", behavior: "smooth" }); setTimeout(() => el.classList.remove("selected"), 2500); }
  }

  let lastSig = "";
  async function reload() {
    song = await api.get(`/api/songs/${songId}`);
    const sig = JSON.stringify([song.status, song.job && [song.job.status, Math.round((song.job.progress || 0) * 50)],
      song.phrases.map((p) => [p.id, p.status, p.lyrics, p.n_takes, p.job && p.job.status])]);
    if (sig === lastSig) return;
    lastSig = sig;
    const job = song.job && ["queued", "running"].includes(song.job.status) ? song.job : null;
    clear(statusBox);
    if (song.status !== "ready") {
      statusBox.append(h("div", { class: "card flat", style: { marginBottom: "14px" } },
        h("div", { class: "row between" }, h("b", {}, SONG_STATUS[song.status] || song.status),
          song.status === "failed" || song.status === "cancelled" ? h("button", { class: "btn small", onclick: async () => {
            try { await api.post(`/api/songs/${songId}/retry`); reload(); } catch (e) { showError(e); } } }, icon("refresh"), "다시 시도") : null,
          song.status === "waiting_weights" ? h("a", { class: "btn small", href: "#/setup" }, "모델 받기") : null),
        job ? jobLine(job, { title: false }) : null,
        song.status === "failed" ? h("p", { class: "hint" }, song.error) : null,
        h("p", { class: "hint" }, "보컬 분리(가수 목소리와 반주를 나누는 일)는 곡 길이에 따라 몇 분에서 수십 분 걸려요. 그동안 소절을 미리 만들어 둘 수 있어요.")));
    }
    wf.setRegions(song.phrases.map((p) => ({ start: p.start_s, end: p.end_s, label: p.lyrics || p.name })));
    clear(listBox, song.phrases.length ? song.phrases.map(phraseItem) :
      h("div", { class: "empty" }, h("p", {}, "아직 소절이 없어요. 왼쪽 파형에서 구간을 골라 저장해 보세요.")));
  }

  async function editPhrase(p) {
    const ly = h("input", { type: "text", value: p.lyrics, maxlength: 300 });
    const nm = h("input", { type: "text", value: p.name, maxlength: 60 });
    const m = modal([h("h2", {}, "소절 고치기"),
      h("label", { class: "field" }, h("span", {}, "가사"), ly, h("small", { class: "muted" }, "가사를 바꾸면 목표 분석을 다시 해요.")),
      h("label", { class: "field" }, h("span", {}, "이름"), nm),
      p.n_takes ? h("p", { class: "hint" }, "녹음이 있는 소절은 구간을 바꿀 수 없어요. 구간을 바꾸려면 새 소절을 만들어 주세요.") : null,
      h("div", { class: "modal-actions" },
        h("button", { class: "btn danger", onclick: async () => {
          const ok = await confirmDialog("소절을 지울까요?", p.n_takes ? `이 소절의 녹음 ${p.n_takes}개도 함께 지워져요.` : "되돌릴 수 없어요.", { ok: "지우기", danger: true });
          if (!ok) return;
          try { await api.del(`/api/phrases/${p.id}`); m.close(); reload(); } catch (e) { showError(e); }
        } }, "지우기"),
        h("button", { class: "btn", onclick: () => m.close() }, "취소"),
        h("button", { class: "btn primary", onclick: async () => {
          try { await api.patch(`/api/phrases/${p.id}`, { lyrics: ly.value, name: nm.value }); m.close(); reload(); } catch (e) { showError(e); }
        } }, "저장"))]);
  }

  async function editSong() {
    const t = h("input", { type: "text", value: song.title, maxlength: 120 });
    const a = h("input", { type: "text", value: song.artist, maxlength: 120 });
    const k = h("input", { type: "text", value: song.song_key, maxlength: 20 });
    const m = modal([h("h2", {}, "곡 정보"), h("label", { class: "field" }, h("span", {}, "제목"), t), h("label", { class: "field" }, h("span", {}, "가수"), a),
      h("label", { class: "field" }, h("span", {}, "키"), k),
      h("div", { class: "modal-actions" }, h("button", { class: "btn", onclick: () => m.close() }, "취소"),
        h("button", { class: "btn primary", onclick: async () => {
          try { await api.patch(`/api/songs/${songId}`, { title: t.value, artist: a.value, song_key: k.value }); m.close(); render(view, [songId]); } catch (e) { showError(e); }
        } }, "저장"))]);
  }

  async function removeSong() {
    const ok = await confirmDialog("곡을 지울까요?", "이 곡의 소절과 모든 사람의 녹음이 함께 지워져요. 되돌릴 수 없어요.", { ok: "지우기", danger: true });
    if (!ok) return;
    try { await api.del(`/api/songs/${songId}`); toast("곡을 지웠어요."); go("#/"); } catch (e) { showError(e); }
  }

  await reload();
  const off = onJobs(() => reload().catch(() => {}));
  return () => { off(); cancelAnimationFrame(raf); audioEl.pause(); wf.destroy(); };
}
