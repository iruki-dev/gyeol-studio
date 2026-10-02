// Coaching for one take: first "무엇이 달랐다고 느끼셨나요?", then one main point and up to two more (expandable),
// each with its evidence (pitch curves + lyrics), an own-voice demo to compare with the recording, and
// "맞아요 / 아닌 것 같아요 / 모르겠어요".
import { api } from "../api.js";
import { onJobs } from "../jobs.js";
import { h, clear, showError, jobLine, icon, toast } from "../ui.js";
import { PitchChart } from "../chart.js";
import { ABPlayer } from "../audio/abplayer.js";

const RESPONSES = [["agree", "맞아요"], ["disagree", "아닌 것 같아요"], ["unsure", "모르겠어요"]];

export function coachPanel(container, takeId, { onLabel } = {}) {
  let disposed = false;
  let data = null;
  const chosen = new Set();
  const players = [];
  const charts = [];
  let offJobs = null;
  let lastSig = "";
  const demoRefresh = new Map();

  function disposeMedia() {
    players.splice(0).forEach((p) => p.destroy());
    charts.splice(0).forEach((c) => c.destroy());
  }

  async function load() {
    if (disposed) return;
    try { data = await api.get(`/api/takes/${takeId}/feedback`); } catch (e) { clear(container, h("div", { class: "notice err" }, e.message)); return; }
    const sig = JSON.stringify([data.status, data.revealed, data.feedback_id, data.job && [data.job.status, Math.round((data.job.progress || 0) * 40)]]);
    if (sig === lastSig) {
      // only demos changed: refresh those boxes in place so playback elsewhere keeps going
      for (const [key, fn] of demoRefresh) {
        const st = data.demos && data.demos[key] ? data.demos[key].status : null;
        if (st !== fn.status) fn();
      }
      return;
    }
    lastSig = sig;
    draw();
  }

  function draw() {
    disposeMedia();
    demoRefresh.clear();
    if (!data.revealed) return drawQuestion();
    drawFeedback();
  }

  function drawQuestion() {
    const ready = !!data.feedback_id;
    const failed = data.status === "failed";
    const chips = h("div", { class: "chips", role: "group", "aria-label": data.question }, data.options.map((o) => {
      const b = h("button", { class: "chip", "aria-pressed": String(chosen.has(o.id)), onclick: () => {
        if (o.id === "nothing") chosen.clear(); else chosen.delete("nothing");
        chosen.has(o.id) ? chosen.delete(o.id) : chosen.add(o.id);
        chips.querySelectorAll(".chip").forEach((c, i) => c.setAttribute("aria-pressed", String(chosen.has(data.options[i].id))));
        submit.disabled = !chosen.size || !ready;
      } }, o.label);
      return b;
    }));
    const submit = h("button", { class: "btn primary", disabled: !chosen.size || !ready, onclick: reveal }, ready ? "피드백 보기" : "분석이 끝나면 볼 수 있어요");
    const job = data.job && ["queued", "running"].includes(data.job.status) ? data.job : null;
    clear(container, h("div", { class: "card", "data-tour": "feedback" },
      h("h2", {}, data.question),
      h("p", { class: "hint" }, "먼저 스스로 들어 보고 골라 주세요. 귀가 좋아지는 가장 빠른 방법이에요."),
      chips,
      h("div", { class: "row", style: { marginTop: "14px" } }, submit),
      failed ? h("div", { class: "notice err" }, h("span", { class: "ico" }, "!"), h("div", {}, data.error || "분석하지 못했어요.",
        h("div", {}, h("button", { class: "btn small", style: { marginTop: "8px" }, onclick: async () => {
          try { await api.post(`/api/takes/${takeId}/retry`); lastSig = ""; load(); } catch (e) { showError(e); } } }, "다시 분석")))) : null,
      job ? h("div", { style: { marginTop: "14px" } }, jobLine(job, { title: false })) : null));
  }

  async function reveal() {
    try {
      data = await api.post(`/api/takes/${takeId}/self-assessment`, { noticed: [...chosen] });
      lastSig = "";
      draw();
    } catch (e) { showError(e); }
  }

  function itemBlock(item, { main }) {
    const ev = data.evidence;
    const canvas = h("canvas");
    const chartWrap = h("div", { class: "chart-wrap" }, canvas);
    const chart = new PitchChart(canvas, ev, { height: main ? 230 : 190 });
    chart.setSpans(item.spans);
    charts.push(chart);
    const legend = h("div", { class: "legend" }, h("span", {}, h("i", { style: { background: "var(--target)", height: "6px" } }), "목표"),
      h("span", {}, h("i", { style: { background: "var(--user)" } }), "내 노래"),
      item.spans.length ? h("span", {}, h("i", { style: { background: "var(--accent-soft)", height: "10px" } }), "이 부분") : null);
    const respond = h("div", { class: "respond" }, h("span", { class: "q" }, "이 지적이 맞나요?"),
      RESPONSES.map(([id, label]) => h("button", { class: "chip small", "aria-pressed": String(data.responses[item.key] === id), onclick: async (e) => {
        try {
          await api.post(`/api/feedback/${data.feedback_id}/responses`, { item_key: item.key, response: id });
          data.responses[item.key] = id;
          respond.querySelectorAll(".chip").forEach((c, i) => c.setAttribute("aria-pressed", String(RESPONSES[i][0] === id)));
          if (id === "disagree") toast("알려 주셔서 고마워요. 모델을 고치는 데 쓸게요.");
        } catch (err) { showError(err); }
      } }, label)));
    const demoBox = h("div", { class: "ab" });
    drawDemo(demoBox, item, chart);
    const notes = [];
    if (item.tentative) notes.push(h("div", { class: "hint" }, data.strings.tentative));
    if (item.experimental) notes.push(h("div", { class: "badge warn" }, data.strings.experimental));
    const tip = item.practice && item.practice[0];
    return h("div", {},
      h("div", { class: "row" }, h("span", { class: "badge accent" }, item.category_label), notes),
      h("div", { class: main ? "coach-text" : "", style: main ? {} : { fontWeight: 600, margin: "6px 0" } }, item.text),
      h("div", { class: "coach-sub" }, item.consistency_text),
      chartWrap, legend,
      demoBox,
      tip ? h("div", { class: "practice-tip", style: { marginTop: "10px" } }, h("b", {}, `연습: ${tip.title}`), ` (약 ${tip.minutes}분) — ${tip.instructions}`) : null,
      respond);
  }

  function drawDemo(box, item, chart) {
    const d = (data.demos || {})[item.key];
    const refresh = () => drawDemo(box, item, chart);
    refresh.status = d ? d.status : null;
    demoRefresh.set(item.key, refresh);
    if (!d || d.status === "failed") {
      clear(box, d && d.status === "failed" ? h("div", { class: "hint" }, d.error) : null,
        h("button", { class: "btn small", onclick: async () => {
          try { const r = await api.post(`/api/takes/${takeId}/demo`, { item_key: item.key }); data.demos = r.demos; drawDemo(box, item, chart); } catch (e) { showError(e); }
        } }, "내 목소리 시범음 만들기"));
      return;
    }
    if (d.status !== "ready") {
      clear(box, h("div", { class: "row" }, h("span", { class: "spinner" }), h("span", { class: "hint" }, "내 목소리로 시범음을 만드는 중…")));
      return;
    }
    const files = d.files;
    const sources = [{ id: "take", label: "내 녹음", url: `/api/takes/${takeId}/audio`, offset: data.evidence.take_offset_s || 0 },
      { id: "demo", label: "시범음", url: `/api/files/${files.step_1}` }];
    const last = Object.keys(files).filter((k) => k.startsWith("step_")).sort().pop();
    if (last && last !== "step_1") sources.push({ id: "toward", label: "목표 쪽으로 더", url: `/api/files/${files[last]}` });
    const seg = h("div", { class: "seg", role: "group", "aria-label": "들을 소리" });
    const playBtn = h("button", { class: "btn primary small" }, icon("play"), "듣기");
    const alt = h("input", { type: "checkbox" });
    const player = new ABPlayer(sources, {
      duration: data.evidence.duration_s,
      onTime: (t) => chart.setPlayhead(t),
      onState: (p) => {
        seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.id === p.active)));
        clear(playBtn, icon(p.playing ? "pause" : "play"), p.playing ? "멈추기" : "듣기");
        if (!p.playing) chart.setPlayhead(null);
      },
    });
    players.push(player);
    for (const s of sources) seg.append(h("button", { "data-id": s.id, "aria-pressed": String(s.id === "take"), onclick: () => player.select(s.id) }, s.label));
    let loaded = false;
    playBtn.onclick = async () => {
      try {
        if (!loaded) { playBtn.disabled = true; await player.load(); loaded = true; playBtn.disabled = false; }
        player.playing ? player.pause() : player.play();
      } catch (e) { playBtn.disabled = false; showError(e); }
    };
    alt.addEventListener("change", () => { player.alternate = alt.checked; });
    clear(box, h("div", { class: "row" }, playBtn, seg),
      h("label", { class: "row hint", style: { gap: "6px" } }, alt, "번갈아 듣기 (한 번씩 바꿔 가며 반복)"),
      h("div", { class: "hint" }, "시범음은 AI가 내 녹음을 고쳐서 다시 만든 소리예요. 듣는 중에 버튼을 바꾸면 같은 위치에서 바로 바뀌어요."));
  }

  function drawFeedback() {
    const co = data.coaching;
    const sa = data.self_assessment;
    const parts = [];
    parts.push(h("div", { class: `notice ${sa.match === "matched" ? "ok" : ""}` }, h("span", { class: "ico" }, sa.match === "matched" ? "👏" : "💬"), sa.message));
    if (co.notes && co.notes.length) parts.push(h("div", { class: "hint" }, co.notes.map((n) => h("div", {}, `· ${n}`))));
    if (co.primary) {
      parts.push(h("div", { class: "card coach-main" }, h("div", { class: "label" }, data.strings.primary), itemBlock(co.primary, { main: true })));
      if (co.secondary.length) {
        parts.push(h("h3", { style: { marginTop: "16px" } }, `${data.strings.secondary} (${co.secondary.length})`));
        for (const it of co.secondary) {
          const det = h("details", { class: "coach-item" }, h("summary", {}, h("span", { class: "badge" }, it.category_label), it.text));
          let filled = false;
          det.addEventListener("toggle", () => { if (det.open && !filled) { filled = true; det.append(h("div", {}, itemBlock(it, { main: false }))); } });
          parts.push(det);
        }
      }
    } else {
      const canvas = h("canvas");
      const chart = new PitchChart(canvas, data.evidence, { height: 200 });
      charts.push(chart);
      parts.push(h("div", { class: "card" }, h("p", { class: "coach-text" }, co.none_text), h("div", { class: "chart-wrap" }, canvas)));
    }
    if (co.hidden_count) parts.push(h("p", { class: "hint" }, `확실하지 않거나 아주 작은 차이 ${co.hidden_count}개는 보여 드리지 않았어요.`));
    for (const n of co.health || []) parts.push(h("div", { class: "notice warn" }, h("span", { class: "ico" }, n.kind === "rest" ? "☕" : "🎚"), n.text));
    if (co.thresholds && co.thresholds.synthetic) parts.push(h("p", { class: "hint" }, "ⓘ ", data.strings.thresholds_synthetic));
    parts.push(h("p", { class: "hint" }, co.referral));
    if (onLabel) parts.push(h("div", { class: "row" }, h("button", { class: "btn small", onclick: () => onLabel(takeId) }, "이 녹음에 라벨 붙이기")));
    clear(container, h("div", { class: "stack" }, parts));
  }

  load();
  offJobs = onJobs((jobs) => {
    if (jobs.some((j) => j.owner_id && j.owner_id.startsWith(takeId))) load();
    else if (data && !data.feedback_id) load();
  });
  return () => { disposed = true; offJobs && offJobs(); disposeMedia(); };
}
