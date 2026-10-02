// Start check (시작 검사): ① range (glide + comfortable notes), ② singing back notes, intervals and a short melody,
// ③ hearing which of two notes is higher.  Scored on the PC with gyeol.coach.onboarding; the result is plain Korean.
import { api, uploadWithProgress } from "../api.js";
import { onJobs } from "../jobs.js";
import { h, clear, showError, toast, jobLine, fmtDate } from "../ui.js";
import { resume, openMic, tone, encodeWav, micUnavailableReason } from "../audio/engine.js";
import { noteNameKo } from "../chart.js";

const hz = (cents) => 440 * 2 ** (cents / 1200);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const shuffle = (a) => { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };

function rangeBar(vr) {
  // a keyboard-like strip from C2 to C6 with the whole range and the comfortable zone
  const lo = -3300, hi = 300; // C2 … C5+ (cents re A4)
  const x = (c) => `${((Math.min(hi, Math.max(lo, c)) - lo) / (hi - lo)) * 100}%`;
  const w = (a, b) => `${((Math.min(hi, b) - Math.max(lo, a)) / (hi - lo)) * 100}%`;
  const ticks = [];
  for (let c = -3300; c <= 300; c += 1200) {
    const edge = c === lo ? "translateX(0)" : c === hi ? "translateX(-100%)" : "translateX(-50%)"; // keep end labels inside
    ticks.push(h("span", { style: { position: "absolute", left: x(c), top: "34px", fontSize: ".75rem", color: "var(--muted)", transform: edge, whiteSpace: "nowrap" } }, noteNameKo(c)));
  }
  return h("div", { style: { position: "relative", height: "54px", margin: "10px 0 6px" }, role: "img",
    "aria-label": `편한 음역 ${noteNameKo(vr.tess_low_cents)}~${noteNameKo(vr.tess_high_cents)}, 전체 ${noteNameKo(vr.low_cents)}~${noteNameKo(vr.high_cents)}` },
  h("div", { style: { position: "absolute", left: 0, right: 0, top: "10px", height: "16px", borderRadius: "8px", background: "var(--surface-2)" } }),
  h("div", { style: { position: "absolute", left: x(vr.low_cents), width: w(vr.low_cents, vr.high_cents), top: "10px", height: "16px", borderRadius: "8px", background: "var(--accent-soft)" }, title: "낼 수 있는 음역" }),
  h("div", { style: { position: "absolute", left: x(vr.tess_low_cents), width: w(vr.tess_low_cents, vr.tess_high_cents), top: "10px", height: "16px", borderRadius: "8px", background: "var(--accent)" }, title: "편한 음역" }),
  ticks);
}

function resultView(check, onAgain) {
  const p = check.profile || {};
  const vr = p.voice_range;
  return h("div", { class: "stack" },
    h("div", { class: "card" }, h("div", { class: "row between" }, h("h2", { style: { margin: 0 } }, "검사 결과"), h("span", { class: "hint" }, fmtDate(check.created_at))),
      vr ? rangeBar(vr) : null,
      vr ? h("div", { class: "legend" }, h("span", {}, h("i", { style: { background: "var(--accent)", height: "10px" } }), "편한 음역"),
        h("span", {}, h("i", { style: { background: "var(--accent-soft)", height: "10px" } }), "낼 수 있는 음역")) : null,
      h("dl", { class: "kv", style: { marginTop: "12px" } }, (check.summary || []).flatMap((s) => [h("dt", {}, s.title), h("dd", {}, s.text)]))),
    h("div", { class: "notice" }, h("span", { class: "ico" }, "🎚"), "이제 소절을 연습할 때 내 음역에서 벗어나면 키를 얼마나 옮기면 좋을지 알려 드려요."),
    h("p", { class: "hint" }, "이 결과는 진단이 아니에요. 그날 목 상태에 따라 달라질 수 있어요."),
    h("button", { class: "btn", onclick: onAgain }, "다시 검사하기"));
}

export async function render(view) {
  const box = h("div", { style: { maxWidth: "760px" } });
  clear(view, h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "시작 검사"),
    h("p", {}, "내 음역과 음 따라 부르기, 음 구별 듣기를 5분쯤 살펴봐요. 결과에 맞춰 연습과 키를 추천해 드려요."))), box);
  let offJobs = null;

  async function showLatest() {
    const { check } = await api.get("/api/checks/latest");
    if (check && check.status === "done") { clear(box, resultView(check, start)); return; }
    if (check && check.status !== "failed" && check.job && ["queued", "running"].includes(check.job.status)) { waitResult(check.id); return; }
    clear(box, h("div", { class: "card" },
      h("h2", {}, "이렇게 진행해요"),
      h("ol", {}, h("li", {}, h("b", {}, "음역 — "), "낮은 음에서 높은 음으로 '아~' 미끄러지듯 부르고, 편한 높이로 '도레미파솔파미레도'를 불러요."),
        h("li", {}, h("b", {}, "따라 부르기 — "), "들려주는 음과 짧은 가락을 듣고 같은 높이로 따라 불러요. (10번)"),
        h("li", {}, h("b", {}, "구별 듣기 — "), "두 음 중 두 번째가 높은지 낮은지 골라요. (16번)")),
      h("p", { class: "hint" }, "조용한 곳에서, 이어폰을 끼고 하면 좋아요. 중간에 멈추면 처음부터 다시 해요."),
      check && check.status === "failed" ? h("div", { class: "notice err" }, "지난 검사 결과를 계산하지 못했어요. 다시 해 주세요.") : null,
      h("button", { class: "btn primary big", onclick: start }, "시작하기")));
  }

  function waitResult(cid) {
    const line = h("div");
    clear(box, h("div", { class: "card" }, h("h2", {}, "결과를 계산하고 있어요"), line, h("p", { class: "hint" }, "녹음마다 음 높이를 분석하고 있어요. 1분쯤 걸려요.")));
    offJobs && offJobs();
    offJobs = onJobs(async () => {
      const c = await api.get(`/api/checks/${cid}`);
      if (c.status === "done") { offJobs(); offJobs = null; clear(box, resultView(c, start)); return; }
      if (c.job && c.job.status === "failed") { offJobs(); offJobs = null; clear(box, h("div", { class: "notice err" }, c.job.error), h("button", { class: "btn", onclick: start }, "다시 검사하기")); return; }
      if (c.job) clear(line, jobLine(c.job, { title: false }));
    });
  }

  async function start() {
    const why = micUnavailableReason();
    if (why) { showError(new Error(why)); return; }
    let check;
    try { check = await api.post("/api/checks"); await openMic(); } catch (e) { showError(e); return; }
    const steps = h("div", { class: "steps" }, [0, 1, 2].map(() => h("i")));
    const stage = h("div");
    clear(box, h("div", { class: "card" }, steps, stage));
    const setStep = (k) => steps.querySelectorAll("i").forEach((el, i) => el.classList.toggle("on", i <= k));

    // records `sec` seconds starting `delay` seconds from now; uploads; returns the server's quick check
    async function recordTrial(task, targets, sec, { delay = 0.1, before } = {}) {
      const c = await resume();
      const m = await openMic();
      const t0 = c.currentTime + delay;
      if (before) before(t0);
      const r = await m.record(t0, t0 + sec);
      const fd = new FormData();
      fd.append("file", encodeWav(r.samples, r.sampleRate), "trial.wav");
      fd.append("meta", JSON.stringify({ task, targets }));
      return uploadWithProgress(`/api/checks/${check.id}/recordings`, fd);
    }

    function prompt(title, text, button) {
      return new Promise((resolve) => {
        clear(stage, h("h2", {}, title), h("p", {}, text), h("button", { class: "btn primary big", onclick: () => resolve() }, button));
      });
    }

    async function countdownRecord(label, sec, task, targets, opts) {
      const meter = h("div", { class: "progress" }, h("i", { style: { width: "0%", transition: `width ${sec}s linear` } }));
      clear(stage, h("h2", {}, label), h("p", { class: "countdown" }, "지금!"), meter);
      requestAnimationFrame(() => requestAnimationFrame(() => { meter.firstChild.style.width = "100%"; }));
      return recordTrial(task, targets, sec, opts);
    }

    try {
      // ① range
      setStep(0);
      await prompt("① 음역 — 미끄러지듯 올라가기", "낮은 음에서 시작해서 '아~' 하고 미끄러지듯 가장 높은 음까지 올라가 보세요. 무리하지 말고 편하게요. (6초)", "녹음 시작");
      await countdownRecord("낮은 음 → 높은 음", 6, "glide", []);
      await prompt("① 음역 — 미끄러지듯 내려가기", "이번엔 높은 음에서 시작해서 가장 낮은 음까지 내려와 보세요. (6초)", "녹음 시작");
      await countdownRecord("높은 음 → 낮은 음", 6, "glide", []);
      let center = null;
      for (let tries = 0; tries < 2 && center === null; tries++) {
        await prompt("① 음역 — 편한 높이로", "말하듯 편한 높이로 '도레미파솔파미레도'를 천천히 불러 보세요. (8초)", tries ? "다시 녹음" : "녹음 시작");
        const r = await countdownRecord("편한 높이로 도레미파솔파미레도", 8, "comfortable", []);
        center = r.median_cents;
        if (center === null) toast("노래하는 목소리를 찾지 못했어요. 마이크 가까이에서 조금 더 크게 불러 주세요.", { error: true });
      }
      if (center === null) center = -900; // C4 when nothing usable was sung
      const c0 = Math.round(center / 100) * 100;

      // ② singing back
      setStep(1);
      const match = [c0, c0 + 400, c0 - 300, c0, c0 + 400, c0 - 300];
      await prompt("② 따라 부르기", "음이 하나 나와요. 다 듣고 '지금!'이 보이면 같은 높이로 '아~' 해 주세요. 남자·여자 목소리 차이로 한 옥타브 달라도 괜찮아요.", "시작");
      for (let i = 0; i < match.length; i++) {
        clear(stage, h("h2", {}, `음 따라 부르기 ${i + 1}/${match.length}`), h("p", { class: "countdown" }, "♪ 듣기"));
        await recordTrial("match", [match[i]], 3.0, { delay: 1.6, before: (t0) => tone(t0 - 1.5, hz(match[i]), 1.2) });
      }
      const intervals = [[c0, c0 + 400], [c0 + 200, c0 - 100], [c0 - 300, c0 + 400]];
      await prompt("② 두 음 따라 부르기", "이번엔 음이 두 개 나와요. 들은 순서대로 '아~ 아~' 하고 두 음을 불러 주세요.", "시작");
      for (let i = 0; i < intervals.length; i++) {
        clear(stage, h("h2", {}, `두 음 따라 부르기 ${i + 1}/${intervals.length}`), h("p", { class: "countdown" }, "♪ 듣기"));
        const [a, b] = intervals[i];
        await recordTrial("interval", [a, b], 3.6, { delay: 2.0, before: (t0) => { tone(t0 - 1.9, hz(a), 0.75); tone(t0 - 1.05, hz(b), 0.75); } });
      }
      const mel = [c0 - 200, c0, c0 + 200, c0, c0 - 200];
      await prompt("② 짧은 가락", "'도레미레도' 같은 짧은 가락이 나와요. 다 듣고 '라라라라라'로 따라 불러 주세요.", "시작");
      clear(stage, h("h2", {}, "짧은 가락 따라 부르기"), h("p", { class: "countdown" }, "♪ 듣기"));
      await recordTrial("melody", mel, 4.5, { delay: 3.2, before: (t0) => mel.forEach((c, k) => tone(t0 - 3.1 + k * 0.55, hz(c), 0.5)) });

      // ③ hearing
      setStep(2);
      await prompt("③ 구별 듣기", "음 두 개가 차례로 나와요. 두 번째 음이 첫 번째보다 높았는지 낮았는지 골라 주세요. 아주 작은 차이도 있으니 헷갈리면 느낌대로 골라도 돼요.", "시작");
      const deltas = shuffle([100, 50, 25, 12].flatMap((d) => [d, d, d, d]));
      const answers = [];
      for (let i = 0; i < deltas.length; i++) {
        const base = c0 + Math.round((Math.random() * 4 - 2)) * 100;
        const up = Math.random() < 0.5;
        const second = base + (up ? deltas[i] : -deltas[i]);
        const play = async () => { const c = await resume(); const t = c.currentTime + 0.1; tone(t, hz(base), 0.5); tone(t + 0.8, hz(second), 0.5); };
        const correct = await new Promise((resolve) => {
          clear(stage, h("h2", {}, `구별 듣기 ${i + 1}/${deltas.length}`), h("p", { class: "hint" }, "두 번째 음이…"),
            h("div", { class: "row" }, h("button", { class: "btn big", onclick: () => resolve(up) }, "▲ 높았어요"), h("button", { class: "btn big", onclick: () => resolve(!up) }, "▼ 낮았어요"),
              h("button", { class: "btn ghost", onclick: play }, "다시 듣기")));
          play();
        });
        answers.push({ delta: deltas[i], correct });
        await sleep(250);
      }
      const r = await api.post(`/api/checks/${check.id}/finish`, { discrimination: answers });
      waitResult(r.id);
    } catch (e) {
      showError(e);
      clear(stage, h("p", {}, "검사를 마치지 못했어요."), h("button", { class: "btn", onclick: start }, "처음부터 다시"));
    }
  }

  await showLatest();
  return () => { offJobs && offJobs(); };
}
