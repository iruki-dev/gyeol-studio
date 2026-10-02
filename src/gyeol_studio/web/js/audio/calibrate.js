// Latency calibration — how late your voice lands in the recording compared with the accompaniment you heard.
//  * tap:      tap along with clicks; latency = tap delay + output latency + input latency (browser-reported);
//  * loopback: hold the earphone to the microphone; latency = measured round trip (most accurate).
// gyeol refines the remaining offset against the guide vocal during analysis, so a few tens of ms off is fine.
import { h, clear, modal, toast } from "../ui.js";
import { store } from "../store.js";
import { audioCtx, resume, click, burst, openMic, inputLatency, outputLatency, ctxTimeOfPerf } from "./engine.js";

const ROUTE_LABEL = { wired: "유선 이어폰", bluetooth: "블루투스 이어폰", speaker: "스피커" };

function median(a) { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.floor(s.length / 2)] : NaN; }
function mad(a) { const m = median(a); return median(a.map((x) => Math.abs(x - m))); }

async function runTap(stage, onDone) {
  const c = await resume();
  const N = 12, gap = 0.6, lead = 2;
  const t0 = c.currentTime + 0.8;
  const times = Array.from({ length: N }, (_, i) => t0 + i * gap);
  const taps = [];
  const pad = h("button", { class: "btn primary big", style: { width: "100%", minHeight: "120px", fontSize: "1.3rem", touchAction: "manipulation" } }, "딸깍에 맞춰 누르기");
  const count = h("p", { class: "hint" }, `처음 ${lead}번은 듣기만 하고, 그다음부터 딸깍 소리에 맞춰 누르세요. (키보드 스페이스바도 돼요)`);
  const onTap = (e) => { e.preventDefault(); taps.push(ctxTimeOfPerf(e.timeStamp || performance.now())); pad.style.transform = "scale(.98)"; setTimeout(() => (pad.style.transform = ""), 80); };
  const onKey = (e) => { if (e.code === "Space") onTap(e); };
  pad.addEventListener("pointerdown", onTap);
  document.addEventListener("keydown", onKey);
  clear(stage, count, pad);
  times.forEach((t, i) => click(t, { freq: i < lead ? 1000 : 1500 }));
  await new Promise((r) => setTimeout(r, (times[N - 1] - c.currentTime + 0.7) * 1000));
  document.removeEventListener("keydown", onKey);
  const delays = [];
  for (const t of times.slice(lead)) {
    const near = taps.filter((x) => Math.abs(x - t) < gap / 2);
    if (near.length) delays.push(near.reduce((a, b) => (Math.abs(a - t) < Math.abs(b - t) ? a : b)) - t);
  }
  if (delays.length < 6) return onDone(null, "누른 횟수가 모자랐어요. 딸깍 소리에 맞춰 끝까지 눌러 주세요.");
  if (mad(delays) > 0.06) return onDone(null, "누른 박자가 일정하지 않았어요. 한 번 더 천천히 해 볼까요?");
  await openMic().catch(() => null); // input latency is reported by the open microphone, when the browser knows it
  const L = median(delays) + outputLatency() + inputLatency();
  onDone(Math.max(0, L), null);
}

async function runLoopback(stage, onDone) {
  let m;
  try { m = await openMic(); } catch (e) { return onDone(null, e.message); }
  const c = audioCtx();
  const N = 6, gap = 0.5;
  const t0 = c.currentTime + 0.6;
  clear(stage, h("p", {}, "탁탁 소리가 6번 나요. 이어폰을 마이크에 댄 채로 조용히 기다려 주세요…"), h("div", { class: "spinner", style: { margin: "10px auto" } }));
  const rec = m.record(t0 - 0.1, t0 + N * gap + 0.8);
  for (let i = 0; i < N; i++) burst(t0 + i * gap);
  const { samples, sampleRate, startTime } = await rec;
  // envelope → first threshold crossing after each burst
  const win = Math.round(sampleRate * 0.001);
  const env = new Float32Array(samples.length);
  let acc = 0;
  for (let i = 0; i < samples.length; i++) { acc += Math.abs(samples[i]); if (i >= win) acc -= Math.abs(samples[i - win]); env[i] = acc / win; }
  const floor = median(Array.from(env.subarray(0, Math.round(0.09 * sampleRate))));
  let peak = 0;
  for (const v of env) if (v > peak) peak = v;
  if (peak < floor * 8 || peak < 0.003) return onDone(null, "탁탁 소리가 마이크에 거의 들어오지 않았어요. 이어폰을 마이크에 더 가까이 대고 소리를 조금 키워 주세요.");
  const thr = floor + 0.3 * (peak - floor);
  const lags = [];
  for (let k = 0; k < N; k++) {
    const t = t0 + k * gap;
    const a = Math.max(0, Math.round((t - startTime) * sampleRate)), b = Math.min(env.length, a + Math.round(0.45 * sampleRate));
    for (let i = a; i < b; i++) if (env[i] > thr) { lags.push(startTime + i / sampleRate - t); break; }
  }
  if (lags.length < 4 || mad(lags) > 0.015) return onDone(null, "소리를 또렷하게 듣지 못했어요. 주변을 조용히 하고 다시 해 주세요.");
  onDone(Math.max(0, median(lags)), null);
}

// Opens the calibration dialog; resolves with { ms, method } (saved for the route) or null.
export function calibrate(route) {
  return new Promise((resolve) => {
    const stage = h("div", { style: { minHeight: "150px" } });
    let result = null;
    const finish = (method) => (L, err) => {
      if (err) {
        clear(stage, h("div", { class: "notice err" }, h("span", { class: "ico" }, "!"), err), choose());
        return;
      }
      result = { ms: Math.round(L * 1000), method, at: Date.now() };
      store.setLatency(route, result);
      clear(stage, h("div", { class: "notice ok" }, h("span", { class: "ico" }, "✓"),
        h("div", {}, h("b", {}, `지연 ${result.ms}ms로 맞췄어요.`), h("div", { class: "hint" }, "녹음할 때 이만큼 당겨서 반주와 맞춰요."))),
      h("div", { class: "modal-actions" }, h("button", { class: "btn", onclick: () => clear(stage, choose()) }, "다시 하기"),
        h("button", { class: "btn primary", onclick: () => m.close() }, "다 됐어요")));
    };
    const choose = () => h("div", { class: "grid", style: { gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" } },
      h("button", { class: "card", style: { textAlign: "left", cursor: "pointer" }, onclick: () => runTap(stage, finish("tap")) },
        h("b", {}, "탭 따라 치기"), h("p", { class: "hint" }, "딸깍 소리에 맞춰 화면을 눌러요. 쉬워요.")),
      h("button", { class: "card", style: { textAlign: "left", cursor: "pointer" }, onclick: () => runLoopback(stage, finish("loopback")) },
        h("b", {}, "이어폰을 마이크에 대기"), h("p", { class: "hint" }, "이어폰 한쪽을 마이크 가까이 대고 소리를 재요. 더 정확해요.")));
    clear(stage, choose());
    const m = modal([
      h("h2", {}, `소리 지연 맞추기 — ${ROUTE_LABEL[route] || route}`),
      h("p", {}, "이어폰(특히 블루투스)은 소리가 조금 늦게 들려요. 처음 한 번만 맞춰 두면 박자 피드백이 정확해져요."),
      stage,
      h("div", { class: "modal-actions" }, h("button", { class: "btn ghost", onclick: () => {
        result = { ms: route === "bluetooth" ? 250 : 80, method: "default", at: Date.now() };
        store.setLatency(route, result); toast("기본값으로 시작해요. 나중에 녹음 화면에서 다시 맞출 수 있어요."); m.close();
      } }, "건너뛰기 (기본값 사용)")),
    ], { onClose: () => resolve(result) });
  });
}
