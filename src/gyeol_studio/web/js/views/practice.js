// Practice one phrase: listen, sing along (count-in, accompaniment + guide vocal at your own volumes), repeat;
// every take shows its waveform, can be replayed, and opens its coaching.
import { api, uploadWithProgress } from "../api.js";
import { store } from "../store.js";
import { onJobs, pollNow } from "../jobs.js";
import { h, clear, showError, toast, icon, fmtDate, modal, jobLine, confirmDialog } from "../ui.js";
import { audioCtx, resume, loadBuffer, openMic, click, encodeWav, micUnavailableReason } from "../audio/engine.js";
import { calibrate } from "../audio/calibrate.js";
import { playUrl, stopSingle } from "../audio/abplayer.js";
import { drawMiniWave, peaksOf } from "../waveform.js";
import { coachPanel } from "./coachpanel.js";

const LABEL_KO = { chest: "흉성", mixed: "믹스", falsetto: "가성", breathy: "숨섞임", pressed_belt: "압착·벨팅", pharyngeal_twang: "트왱", fry: "프라이",
  rough: "거침", none: "맑은 소리" };
const labelText = (l) => [l.register, ...(l.qualities || [])].filter(Boolean).map((x) => LABEL_KO[x] || x).join("·");
const ROUTES = [["wired", "유선 이어폰"], ["bluetooth", "블루투스"], ["speaker", "스피커"]];

export async function render(view, params) {
  const route = location.hash.split("/")[1];
  let phraseId = params[0];
  let selected = null;
  if (route === "take") {
    const t = await api.get(`/api/takes/${params[0]}`);
    phraseId = t.phrase_id;
    selected = t.id;
  }
  const [phrase, settings] = await Promise.all([api.get(`/api/phrases/${phraseId}`), api.get("/api/settings")]);
  const adv = settings.advanced;
  const dur = phrase.end_s - phrase.start_s;
  const sliceStart = phrase.slice_start_s ?? Math.max(0, phrase.start_s - 6);
  let disposed = false;
  let panelOff = null;
  let state = "idle";
  const vol = { backing: store.get("vol_backing", 0.8), guide: store.get("vol_guide", 0.5) };
  const gains = {};
  let playing = [];
  let again = store.get("again", false);
  const localPeaks = new Map();

  // ---------- header
  const head = h("div", { class: "page-head" },
    h("div", {}, h("a", { href: `#/song/${phrase.song_id}`, class: "btn ghost small" }, icon("back"), phrase.song.title),
      h("h1", {}, phrase.lyrics || phrase.name), h("p", {}, `${phrase.name} · ${dur.toFixed(1)}초`)));

  // ---------- recorder card
  const lyricNow = h("div", { class: "lyric-now", "aria-live": "polite" }, phrase.lyrics || " ");
  const countdown = h("div", { class: "countdown", "aria-live": "assertive" });
  const meter = h("div", { class: "meter", title: "마이크 소리 크기" }, h("i"));
  const recBtn = h("button", { class: "rec-btn", "data-tour": "record", onclick: () => (state === "idle" ? startTake() : stopTake()) }, "녹음");
  const previewBtn = h("button", { class: "btn", onclick: preview }, icon("play"), "미리 듣기");
  const routeSeg = h("div", { class: "seg", role: "group", "aria-label": "듣는 장치" });
  const latInfo = h("span", { class: "hint" });
  const cond = store.conditions();
  for (const [id, label] of ROUTES) {
    routeSeg.append(h("button", { "aria-pressed": String(cond.earphone === id), onclick: () => {
      const c = store.conditions();
      c.earphone = id;
      store.setConditions(c);
      routeSeg.querySelectorAll("button").forEach((b, i) => b.setAttribute("aria-pressed", String(ROUTES[i][0] === id)));
      drawLatency();
      drawConditions();
      if (id === "speaker") toast("스피커로 반주를 틀면 마이크에 반주가 섞여요. 가능하면 이어폰을 써 주세요.");
    } }, label));
  }
  function drawLatency() {
    const r = store.conditions().earphone;
    const l = store.latency(r);
    clear(latInfo, l ? `지연 ${l.ms}ms (${{ tap: "탭", loopback: "마이크", default: "기본값" }[l.method] || l.method}) ` : "지연을 아직 맞추지 않았어요 ",
      h("button", { class: "btn small ghost", onclick: async () => { await calibrate(r); drawLatency(); } }, l ? "다시 맞추기" : "맞추기"));
  }
  const slider = (key, label, help) => {
    const out = h("output", {}, `${Math.round(vol[key] * 100)}`);
    const inp = h("input", { type: "range", min: 0, max: 1, step: 0.05, value: vol[key], "aria-label": label, oninput: () => {
      vol[key] = Number(inp.value);
      out.textContent = `${Math.round(vol[key] * 100)}`;
      store.set(`vol_${key}`, vol[key]);
      if (gains[key]) gains[key].gain.setTargetAtTime(vol[key], audioCtx().currentTime, 0.02);
    } });
    return [h("label", { style: { fontWeight: 600 } }, label, h("div", { class: "hint", style: { fontWeight: 400 } }, help)), inp, out];
  };
  const againBox = h("input", { type: "checkbox", checked: again, onchange: () => { again = againBox.checked; store.set("again", again); } });
  const condBtn = h("button", { class: "btn small ghost", onclick: conditionsDialog, "data-tour": "conditions" }, "녹음 조건");
  const condInfo = h("div", { class: "hint", style: { marginBottom: "10px" } });
  function drawConditions() {
    const c = store.conditions();
    const parts = [c.device, c.place, c.backing === "off" ? "반주 없이" : "반주 틀고"].filter(Boolean);
    clear(condInfo, `녹음 조건: ${parts.join(" · ")} `, !c.device || !c.place ? h("button", { class: "btn small ghost", onclick: conditionsDialog }, "기기·장소 적기") : null);
  }
  drawConditions();
  // ---------- technique recording mode: the same phrase twice, without and with a technique, saved as a labelled pair
  const tech = { on: false, contrast: null, role: "off", pair: null };
  let techniques = [];
  api.get("/api/techniques").then((r) => { techniques = r.techniques; drawTech(); }).catch(() => {});
  const modeSeg = h("div", { class: "seg", role: "group", "aria-label": "녹음 방식", "data-tour": "technique" },
    h("button", { "aria-pressed": "true", onclick: () => setMode(false) }, "연습"),
    h("button", { "aria-pressed": "false", onclick: () => setMode(true) }, "기술 녹음"));
  const techBox = h("div", { hidden: true, style: { textAlign: "left", margin: "4px 0 12px" } });
  function setMode(on) {
    tech.on = on;
    modeSeg.querySelectorAll("button").forEach((b, i) => b.setAttribute("aria-pressed", String(i === (on ? 1 : 0))));
    techBox.hidden = !on;
    drawTech();
  }
  const recCard = h("div", { class: "card recorder" },
    h("div", { class: "row between", style: { marginBottom: "10px" } }, h("h2", { style: { margin: 0 } }, "따라 부르기"), condBtn),
    h("div", { class: "row", style: { justifyContent: "center", marginBottom: "8px" } }, modeSeg),
    techBox,
    h("div", { class: "row", style: { justifyContent: "center", marginBottom: "6px" } }, h("span", { class: "hint" }, "듣는 장치"), routeSeg),
    h("div", { style: { marginBottom: "4px" } }, latInfo),
    condInfo,
    h("div", { class: "sliders" }, slider("backing", "반주", "노래를 뺀 음악"), slider("guide", "가이드 보컬", "원곡 가수의 목소리")),
    countdown, lyricNow,
    h("div", { style: { margin: "8px 0 16px" } }, recBtn),
    meter,
    h("div", { class: "row", style: { justifyContent: "center", marginTop: "12px" } }, previewBtn,
      h("label", { class: "row hint", style: { gap: "6px" } }, againBox, "끝나면 바로 한 번 더")),
    h("p", { class: "hint" }, `시작하면 ${adv.count_in_beats}번 딸깍 소리 뒤에 소절이 시작돼요. 이어폰을 끼고 반주에 맞춰 부르세요.`));

  function drawTech() {
    if (!tech.on) return;
    const t = techniques.find((x) => x.id === tech.contrast);
    clear(techBox,
      h("p", { class: "hint", style: { margin: "0 0 8px" } }, "같은 소절을 두 번 불러요. 데이터에 짝으로 저장되고 라벨이 자동으로 붙어요. 모델이 소리의 차이를 배우는 데 써요."),
      h("div", { class: "chips" }, techniques.map((x) => h("button", { class: "chip small", "aria-pressed": String(x.id === tech.contrast),
        onclick: () => { tech.contrast = x.id; tech.role = "off"; tech.pair = null; drawTech(); } }, x.label))),
      t ? h("ol", { style: { margin: "10px 0 0", paddingLeft: "1.3em" } }, t.steps.map((st) => h("li", {
        style: { fontWeight: st.role === tech.role ? 700 : 400, color: st.role === tech.role ? "var(--ink)" : "var(--muted)" } },
      `${st.label}: ${st.how}`, st.role === "off" && tech.role === "on" ? " ✓" : ""))) : h("p", { class: "hint" }, "어떤 차이를 녹음할지 골라 주세요."));
  }

  // ---------- does the phrase fit my range? (start check → gyeol.coach.health.check_phrase)
  const rangeBox = h("div");
  api.get(`/api/phrases/${phraseId}/range-check`).then((rc) => {
    if (!rc.available) {
      if (rc.reason === "no_range") clear(rangeBox, h("div", { class: "notice" }, h("span", { class: "ico" }, "🎚"),
        h("div", {}, "시작 검사를 하면 이 소절이 내 음역에 맞는지, 키를 얼마나 옮기면 좋을지 알려 드려요. ", h("a", { href: "#/check" }, "시작 검사 하기"))));
      return;
    }
    const ok = rc.status === "comfortable";
    clear(rangeBox, h("div", { class: `notice ${ok ? "ok" : "warn"}` }, h("span", { class: "ico" }, ok ? "✓" : "🎚"), h("div", {}, rc.texts.map((t) => h("div", {}, t)))));
  }).catch(() => {});

  // ---------- takes + coaching
  const takeList = h("div", { class: "take-list" });
  const panel = h("div", {}, h("div", { class: "card empty" }, h("p", {}, "녹음하면 여기에 피드백이 나와요.")));
  clear(view, head, rangeBox, h("div", { class: "two-col" },
    h("div", { class: "stack" }, recCard, h("div", { class: "card" }, h("h2", {}, "내 녹음"), takeList)),
    h("div", {}, panel)));
  drawLatency();

  // ---------- audio
  const urls = { guide: `/api/phrases/${phraseId}/audio/guide`, backing: `/api/phrases/${phraseId}/audio/backing` };
  const bufs = {};
  const loading = Promise.all(Object.entries(urls).map(async ([k, u]) => { bufs[k] = await loadBuffer(u); })).catch((e) => showError(e));

  function schedulePlayback(t0, preroll) {
    const c = audioCtx();
    const songStart = phrase.start_s - preroll;
    const off = songStart - sliceStart;
    playing = [];
    for (const k of ["backing", "guide"]) {
      const g = c.createGain();
      g.gain.value = vol[k];
      g.connect(c.destination);
      gains[k] = g;
      const s = c.createBufferSource();
      s.buffer = bufs[k];
      s.connect(g);
      const delay = Math.max(0, -off);
      s.start(t0 + delay, Math.max(0, off), preroll + dur + adv.tail_s - delay);
      playing.push(s);
    }
  }
  function stopPlayback() {
    for (const s of playing) { try { s.stop(); } catch { /* ended */ } }
    playing = [];
  }

  let lyricTimer = 0;
  function runLyrics(t0, preroll) {
    const syl = (phrase.target && phrase.target.syllables) || [];
    const c = audioCtx();
    cancelAnimationFrame(lyricTimer);
    const beat = preroll / Math.max(1, adv.count_in_beats);
    const step = () => {
      const t = c.currentTime - t0;
      if (t < preroll) {
        const left = Math.ceil((preroll - t) / beat);
        countdown.textContent = left > adv.count_in_beats ? "" : String(left);
      } else if (t < preroll + dur) {
        countdown.textContent = "";
        const p = t - preroll;
        if (syl.length) {
          clear(lyricNow, syl.map((s) => h("span", { style: { color: p >= s.start && p < s.end ? "var(--accent)" : p >= s.end ? "var(--ink)" : "var(--muted)" } }, s.text, " ")));
        }
      } else {
        countdown.textContent = "";
      }
      if (t < preroll + dur + adv.tail_s && state !== "idle") lyricTimer = requestAnimationFrame(step);
    };
    lyricTimer = requestAnimationFrame(step);
  }

  async function preview() {
    if (state === "preview") { stopPlayback(); state = "idle"; clear(previewBtn, icon("play"), "미리 듣기"); return; }
    if (state !== "idle") return;
    try {
      const c = await resume();
      await loading;
      state = "preview";
      clear(previewBtn, icon("stop"), "멈추기");
      const preroll = Math.min(adv.preroll_s, 2);
      const t0 = c.currentTime + 0.1;
      schedulePlayback(t0, preroll);
      runLyrics(t0, preroll);
      setTimeout(() => { if (state === "preview") { state = "idle"; clear(previewBtn, icon("play"), "미리 듣기"); clear(lyricNow, phrase.lyrics || " "); } },
        (preroll + dur + adv.tail_s + 0.2) * 1000);
    } catch (e) { showError(e); state = "idle"; }
  }

  async function ensureReady() {
    const why = micUnavailableReason();
    if (why) throw new Error(why);
    if (!store.get("headphone_seen")) {
      await headphoneGuide();
      store.set("headphone_seen", true);
    }
    if (!store.latency(store.conditions().earphone)) {
      await calibrate(store.conditions().earphone);
      drawLatency();
    }
  }

  function headphoneGuide() {
    return new Promise((resolve) => {
      const m = modal([h("div", { style: { textAlign: "center", fontSize: "48px" } }, "🎧"), h("h2", {}, "이어폰을 연결해 주세요"),
        h("p", {}, "반주를 스피커로 틀면 마이크에 반주가 함께 녹음돼서 피드백이 부정확해져요. 유선 이어폰이 가장 좋아요."),
        h("p", { class: "hint" }, "블루투스 이어폰은 소리가 늦게 들려서, 다음 화면에서 지연을 한 번 맞춰요."),
        h("div", { class: "modal-actions" }, h("button", { class: "btn primary", onclick: () => m.close() }, "연결했어요"))], { onClose: resolve });
    });
  }

  let rec = null;
  async function startTake() {
    if (tech.on && !tech.contrast) { toast("기술 녹음에서 녹음할 차이를 먼저 골라 주세요.", { error: true }); return; }
    try {
      await ensureReady();
      const m = await openMic();
      watchLevel(m);
      await loading;
      if (!bufs.guide) throw new Error("소절 소리를 불러오지 못했어요. 화면을 새로 고쳐 주세요.");
      const c = await resume();
      state = "countin";
      recBtn.classList.add("recording");
      recBtn.textContent = "멈추기";
      previewBtn.disabled = true;
      const preroll = adv.preroll_s;
      const t0 = c.currentTime + 0.25;
      const beat = preroll / Math.max(1, adv.count_in_beats);
      for (let i = 0; i < adv.count_in_beats; i++) click(t0 + preroll - (adv.count_in_beats - i) * beat, { freq: i === 0 ? 1600 : 1200, gain: 0.35 });
      schedulePlayback(t0, preroll);
      runLyrics(t0, preroll);
      const lat = store.latency(store.conditions().earphone) || { ms: 80, method: "default" };
      const total = preroll + dur + adv.tail_s;
      rec = { t0, preroll, lat, promise: m.record(t0, t0 + total) };
      setTimeout(() => { if (state === "countin") state = "recording"; }, preroll * 1000);
      const result = await rec.promise;
      await finishTake(result);
    } catch (e) {
      showError(e);
      resetRecorder();
    }
  }

  function stopTake() {
    if (!rec) return;
    stopPlayback();
    openMic().then((m) => m.stop());
  }

  function resetRecorder() {
    state = "idle";
    stopPlayback();
    cancelAnimationFrame(lyricTimer);
    countdown.textContent = "";
    clear(lyricNow, phrase.lyrics || " ");
    recBtn.classList.remove("recording");
    recBtn.textContent = "녹음";
    recBtn.disabled = false;
    previewBtn.disabled = false;
    rec = null;
  }

  async function finishTake({ samples, sampleRate, startTime }) {
    const { t0, preroll, lat } = rec;
    stopPlayback();
    state = "uploading";
    recBtn.classList.remove("recording");
    recBtn.textContent = "올리는 중";
    recBtn.disabled = true;
    // where the phrase starts in this recording: lead-in + your latency (+ any gap before the first recorded frame)
    const offset = preroll + lat.ms / 1000 - (startTime - t0);
    if (samples.length / sampleRate < offset + dur * 0.7) {
      toast("소절이 끝나기 전에 멈췄어요. 끝까지 불러 주세요.", { error: true });
      resetRecorder();
      return;
    }
    const fd = new FormData();
    fd.append("file", encodeWav(samples, sampleRate), "take.wav");
    const meta = { phrase_offset_s: offset, latency_ms: lat.ms, latency_method: lat.method, conditions: store.conditions() };
    if (tech.on && tech.contrast) {
      if (!tech.pair) tech.pair = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now() + Math.random())).replace(/-/g, "").slice(0, 16);
      const t = techniques.find((x) => x.id === tech.contrast);
      Object.assign(meta, { kind: "technique", pair_id: tech.pair, pair_role: tech.role, technique: { contrast: tech.contrast, label: t ? t.label : tech.contrast } });
    }
    fd.append("meta", JSON.stringify(meta));
    try {
      const t = await uploadWithProgress(`/api/phrases/${phraseId}/takes`, fd);
      if (meta.kind === "technique") {
        if (tech.role === "off") { tech.role = "on"; toast("첫 번째를 저장했어요. 이제 두 번째 방식으로 불러 주세요."); }
        else { tech.role = "off"; tech.pair = null; toast("짝 녹음을 저장했어요. 라벨이 자동으로 붙었어요."); }
        drawTech();
      }
      const a = Math.max(0, Math.round(offset * sampleRate));
      localPeaks.set(t.id, peaksOf(samples.subarray(a, a + Math.round(dur * sampleRate)), 300));
      pollNow();
      resetRecorder();
      select(t.id);
      await loadTakes();
      if (window.matchMedia("(max-width: 980px)").matches) panel.scrollIntoView({ behavior: "smooth", block: "start" });
      if (again && !disposed) setTimeout(() => { if (state === "idle" && !disposed) startTake(); }, 1500);
    } catch (e) { showError(e); resetRecorder(); }
  }

  // ---------- conditions (kept for the next recording too)
  function conditionsDialog() {
    const c = store.conditions();
    const device = h("input", { type: "text", value: c.device, maxlength: 40, placeholder: "예: 갤럭시 S24, 맥북 내장 마이크" });
    const place = h("input", { type: "text", value: c.place, maxlength: 40, placeholder: "예: 집 방, 연습실" });
    const backing = h("div", { class: "seg" });
    let b = c.backing;
    for (const [id, label] of [["on", "반주 틀고"], ["off", "반주 없이"]]) {
      backing.append(h("button", { "aria-pressed": String(b === id), onclick: () => { b = id; backing.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x.textContent === label))); } }, label));
    }
    const m = modal([h("h2", {}, "녹음 조건"), h("p", { class: "hint" }, "한 번 고르면 다음 녹음에도 그대로 써요. 데이터를 분석할 때 도움이 돼요."),
      h("label", { class: "field" }, h("span", {}, "기기"), device),
      h("div", { class: "field" }, h("span", { style: { fontWeight: 600, display: "block", marginBottom: "6px" } }, "반주"), backing),
      h("label", { class: "field" }, h("span", {}, "장소"), place),
      h("p", { class: "hint" }, "이어폰 종류는 녹음 화면 위쪽에서 고를 수 있어요."),
      h("div", { class: "modal-actions" }, h("button", { class: "btn primary", onclick: () => {
        store.setConditions({ ...store.conditions(), device: device.value.trim(), place: place.value.trim(), backing: b });
        if (b === "off") vol.backing = 0;
        m.close(); drawConditions(); toast("녹음 조건을 저장했어요.");
      } }, "저장"))]);
  }

  // ---------- takes
  let takes = [];
  let lastSig = "";
  function select(id) {
    selected = id;
    takeList.querySelectorAll(".take").forEach((el) => el.classList.toggle("selected", el.dataset.id === id));
    panelOff && panelOff();
    panelOff = coachPanel(panel, id, { onLabel: (tid) => import("./data.js").then((m) => m.labelDialog(tid)) });
    if (history.replaceState) history.replaceState(null, "", `#/take/${id}`);
  }

  function takeRow(t, n) {
    const canvas = h("canvas");
    const playBtn = h("button", { class: "play-btn", "aria-label": `${n}번째 녹음 듣기`, html: '<svg viewBox="0 0 24 24"><path d="M7 4.5v15l13-7.5z" fill="currentColor"/></svg>',
      onclick: async (e) => { e.stopPropagation(); try { await playUrl(`/api/takes/${t.id}/audio`); } catch (err) { showError(err); } } });
    const job = t.job && ["queued", "running"].includes(t.job.status) ? t.job : null;
    let status;
    const techBadge = t.kind === "technique" && t.labels ? h("span", { class: "badge accent" }, `기술: ${labelText(t.labels)}`) : null;
    if (t.status === "ready") status = t.feedback && t.feedback.revealed ? h("span", { class: "hint" }, t.feedback.primary || "짚을 차이 없음") : h("span", { class: "badge accent" }, "피드백 확인 전");
    else if (t.status === "failed") status = h("span", { class: "badge err" }, "분석 실패");
    else status = job ? jobLine(job, { title: false }) : h("span", { class: "badge" }, "분석 대기");
    const row = h("div", { class: "take" + (t.id === selected ? " selected" : ""), "data-id": t.id, tabindex: "0", role: "button",
      onclick: () => select(t.id), onkeydown: (e) => { if (e.key === "Enter") select(t.id); } },
    h("span", { class: "num", title: t.kind === "technique" ? "기술 녹음" : "" }, n),
    h("div", { style: { minWidth: 0 } }, canvas, h("div", { class: "row between" }, h("small", { class: "muted" }, fmtDate(t.created_at), " ", techBadge), status)),
    h("div", { class: "row" }, playBtn, h("button", { class: "icon-btn", title: "지우기", "aria-label": "녹음 지우기", html: '<svg viewBox="0 0 24 24" width="20"><path d="M5 7h14M10 7V4.5h4V7M7 7l1 13h8l1-13" stroke="currentColor" stroke-width="1.8" fill="none"/></svg>',
      onclick: async (e) => {
        e.stopPropagation();
        if (!(await confirmDialog("이 녹음을 지울까요?", "녹음과 분석 결과, 피드백 응답, 라벨이 함께 지워져요.", { ok: "지우기", danger: true }))) return;
        try { await api.del(`/api/takes/${t.id}`); if (selected === t.id) { selected = null; clear(panel); } loadTakes(); } catch (err) { showError(err); }
      } })));
    requestAnimationFrame(async () => {
      let pk = localPeaks.get(t.id);
      if (!pk) { try { pk = (await api.get(`/api/takes/${t.id}/peaks?n=300`)).peaks; localPeaks.set(t.id, pk); } catch { pk = []; } }
      drawMiniWave(canvas, pk);
    });
    return row;
  }

  async function loadTakes() {
    if (disposed) return;
    ({ takes } = await api.get(`/api/phrases/${phraseId}/takes`));
    const sig = JSON.stringify(takes.map((t) => [t.id, t.status, t.feedback && t.feedback.revealed, t.job && [t.job.status, Math.round((t.job.progress || 0) * 20)]]));
    if (sig === lastSig) return;
    lastSig = sig;
    clear(takeList, takes.length ? takes.map((t, i) => takeRow(t, takes.length - i)) : h("p", { class: "hint" }, "아직 녹음이 없어요. 위의 녹음 버튼을 눌러 시작하세요."));
    if (!selected && takes.length) select(takes[0].id);
  }

  // the level meter starts once the microphone is open (opening it needs a tap first on most browsers)
  let offLevel = null;
  function watchLevel(m) {
    if (offLevel) return;
    offLevel = m.onLevel((l) => { meter.firstChild.style.width = `${Math.min(100, Math.sqrt(l.rms) * 260)}%`; });
  }
  await loadTakes();
  if (selected) select(selected);
  const offJobs = onJobs(() => loadTakes().catch(() => {}));
  return () => {
    disposed = true;
    offJobs();
    offLevel && offLevel();
    panelOff && panelOff();
    stopPlayback();
    stopSingle();
    cancelAnimationFrame(lyricTimer);
    if (rec) openMic().then((m) => m.stop());
  };
}

