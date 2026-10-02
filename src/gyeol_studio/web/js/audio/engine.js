// Web Audio: one AudioContext, decoded buffers, the microphone (AudioWorklet recorder), clicks and WAV encoding.

let ctx = null;
const buffers = new Map();
let mic = null;

export function audioCtx() {
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: "interactive" });
  return ctx;
}

export async function resume() {
  const c = audioCtx();
  if (c.state !== "running") await c.resume();
  return c;
}

export async function loadBuffer(url, { cache = true } = {}) {
  if (cache && buffers.has(url)) return buffers.get(url);
  const res = await fetch(url);
  if (!res.ok) throw new Error("소리 파일을 불러오지 못했어요. 화면을 새로 고쳐 주세요.");
  const data = await res.arrayBuffer();
  const buf = await new Promise((ok, bad) => audioCtx().decodeAudioData(data, ok, bad));
  if (cache) buffers.set(url, buf);
  return buf;
}

export function forget(url) { buffers.delete(url); }

export function micUnavailableReason() {
  if (!window.isSecureContext) {
    return "휴대폰에서는 https 주소로 접속해야 마이크를 쓸 수 있어요. PC 화면의 '휴대폰 연결'에서 QR 코드로 접속해 주세요.";
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return "이 브라우저는 마이크 녹음을 지원하지 않아요. 크롬, 사파리, 엣지 최신 버전을 써 주세요.";
  if (!audioCtx().audioWorklet) return "이 브라우저는 녹음 기능(AudioWorklet)을 지원하지 않아요. 크롬, 사파리, 엣지 최신 버전을 써 주세요.";
  return null;
}

// Opens the microphone once; returns { node, stream, settings, onLevel(fn) }.
export async function openMic() {
  if (mic && mic.stream.active) return mic;
  const why = micUnavailableReason();
  if (why) throw new Error(why);
  const c = await resume();
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 },
    });
  } catch (e) {
    if (e.name === "NotAllowedError") throw new Error("마이크 권한이 꺼져 있어요. 주소창 옆 자물쇠(또는 설정)에서 마이크를 허용한 뒤 다시 눌러 주세요.");
    if (e.name === "NotFoundError") throw new Error("마이크를 찾지 못했어요. 마이크(또는 마이크 달린 이어폰)를 연결해 주세요.");
    throw new Error("마이크를 열지 못했어요. 다른 앱이 마이크를 쓰고 있는지 확인해 주세요.");
  }
  await c.audioWorklet.addModule("/static/js/audio/recorder-worklet.js");
  const source = c.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(c, "gyeol-recorder", { numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1, channelCountMode: "explicit" });
  const mute = c.createGain();
  mute.gain.value = 0;
  source.connect(node).connect(mute).connect(c.destination); // pulled by the graph, outputs silence
  const levelFns = new Set();
  let collector = null;
  node.port.onmessage = (e) => {
    const m = e.data;
    if (m.type === "level") levelFns.forEach((f) => f(m));
    else if (m.type === "chunk" && collector) collector(m);
  };
  const track = stream.getAudioTracks()[0];
  mic = {
    stream, node, source,
    settings: track ? track.getSettings() : {},
    label: track ? track.label : "",
    onLevel(fn) { levelFns.add(fn); return () => levelFns.delete(fn); },
    // record from context time t0 to t1 (seconds); resolves { samples, sampleRate, startTime }
    record(t0, t1) {
      return new Promise((resolve) => {
        const sr = c.sampleRate;
        const parts = [];
        let first = null;
        collector = (m) => {
          if (m.firstFrame !== null && first === null) first = m.firstFrame;
          parts.push(m.samples);
          if (m.final) {
            collector = null;
            const n = parts.reduce((a, p) => a + p.length, 0);
            const out = new Float32Array(n);
            let o = 0;
            for (const p of parts) { out.set(p, o); o += p.length; }
            resolve({ samples: out, sampleRate: sr, startTime: first !== null ? first / sr : t0 });
          }
        };
        node.port.postMessage({ cmd: "start", frame: Math.round(t0 * sr), stopFrame: t1 ? Math.round(t1 * sr) : 0 });
      });
    },
    stop() { node.port.postMessage({ cmd: "stop" }); },
  };
  return mic;
}

export function inputLatency() {
  const s = mic && mic.settings;
  return s && typeof s.latency === "number" && s.latency > 0 && s.latency < 0.5 ? s.latency : 0.01;
}

export function outputLatency() {
  const c = audioCtx();
  const v = (typeof c.outputLatency === "number" && c.outputLatency > 0 ? c.outputLatency : 0) || c.baseLatency || 0.02;
  return Math.min(v, 1.0);
}

// A short click (count-in, calibration) scheduled at context time t.
export function click(t, { freq = 1500, gain = 0.5, dur = 0.03, dest } = {}) {
  const c = audioCtx();
  const o = c.createOscillator();
  const g = c.createGain();
  o.frequency.value = freq;
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(gain, t + 0.002);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(g).connect(dest || c.destination);
  o.start(t);
  o.stop(t + dur + 0.02);
}

// A broadband burst (sharp onset) for loopback calibration.
export function burst(t, { gain = 0.8, dur = 0.012 } = {}) {
  const c = audioCtx();
  const n = Math.round(dur * c.sampleRate);
  const b = c.createBuffer(1, n, c.sampleRate);
  const d = b.getChannelData(0);
  for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / n);
  const s = c.createBufferSource();
  const g = c.createGain();
  g.gain.value = gain;
  s.buffer = b;
  s.connect(g).connect(c.destination);
  s.start(t);
}

// A sine tone (start check: "sing this note").
export function tone(t, freq, dur, { gain = 0.25 } = {}) {
  const c = audioCtx();
  const o = c.createOscillator();
  const o2 = c.createOscillator();
  const g = c.createGain();
  o.type = "triangle";
  o.frequency.value = freq;
  o2.frequency.value = freq * 2;
  const g2 = c.createGain();
  g2.gain.value = 0.15;
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(gain, t + 0.03);
  g.gain.setValueAtTime(gain, t + dur - 0.08);
  g.gain.linearRampToValueAtTime(0, t + dur);
  o.connect(g);
  o2.connect(g2).connect(g);
  g.connect(c.destination);
  o.start(t); o2.start(t);
  o.stop(t + dur + 0.05); o2.stop(t + dur + 0.05);
}

export function encodeWav(samples, sampleRate) {
  const n = samples.length;
  const buf = new ArrayBuffer(44 + n * 2);
  const v = new DataView(buf);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); w(8, "WAVE"); w(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) { const s = Math.max(-1, Math.min(1, samples[i])); v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true); }
  return new Blob([buf], { type: "audio/wav" });
}

// Context time ↔ performance.now() through the output timestamp (what is audible when).
export function ctxTimeOfPerf(perfMs) {
  const c = audioCtx();
  if (c.getOutputTimestamp) {
    const ts = c.getOutputTimestamp();
    if (ts && ts.performanceTime) return ts.contextTime + (perfMs - ts.performanceTime) / 1000;
  }
  return c.currentTime - outputLatency() + (perfMs - performance.now()) / 1000;
}
