// A/B player: several renderings of the same phrase played in sync; switching changes only which one you hear,
// at the same position.  "번갈아 듣기" switches automatically at every loop.
import { audioCtx, resume, loadBuffer } from "./engine.js";

export class ABPlayer {
  // sources: [{ id, label, url, offset }] — offset (s) into that buffer for position 0
  constructor(sources, { duration, onTime, onState } = {}) {
    this.sources = sources;
    this.duration = duration;
    this.onTime = onTime;
    this.onState = onState;
    this.active = sources[0].id;
    this.alternate = false;
    this.nodes = [];
    this.playing = false;
    this.pos = 0;
    this._raf = 0;
  }

  async load() {
    await Promise.all(this.sources.map(async (s) => { s.buffer = await loadBuffer(s.url, { cache: false }); }));
    if (!this.duration) this.duration = Math.min(...this.sources.map((s) => s.buffer.duration - (s.offset || 0)));
  }

  select(id) {
    this.active = id;
    for (const n of this.nodes) n.gain.gain.setTargetAtTime(n.id === id ? 1 : 0, audioCtx().currentTime, 0.008);
    this.onState && this.onState(this);
  }

  async play(from = this.pos) {
    const c = await resume();
    this.stopNodes();
    const t = c.currentTime + 0.05;
    this.startAt = t - from;
    for (const s of this.sources) {
      const src = c.createBufferSource();
      const gain = c.createGain();
      src.buffer = s.buffer;
      gain.gain.value = s.id === this.active ? 1 : 0;
      src.connect(gain).connect(c.destination);
      src.start(t, Math.max(0, (s.offset || 0) + from), Math.max(0.05, this.duration - from));
      this.nodes.push({ id: s.id, src, gain });
    }
    this.playing = true;
    this.onState && this.onState(this);
    const tick = () => {
      if (!this.playing) return;
      this.pos = audioCtx().currentTime - this.startAt;
      if (this.pos >= this.duration) {
        // loop; in alternate mode switch to the next source each time round
        if (this.alternate) {
          const i = this.sources.findIndex((s) => s.id === this.active);
          this.active = this.sources[(i + 1) % this.sources.length].id;
        }
        this.play(0);
        return;
      }
      this.onTime && this.onTime(this.pos);
      this._raf = requestAnimationFrame(tick);
    };
    this._raf = requestAnimationFrame(tick);
  }

  pause() {
    if (this.playing) this.pos = Math.min(this.duration, audioCtx().currentTime - this.startAt);
    this.stopNodes();
    this.playing = false;
    this.onState && this.onState(this);
  }

  stopNodes() {
    cancelAnimationFrame(this._raf);
    for (const n of this.nodes) { try { n.src.stop(); } catch { /* already stopped */ } n.src.disconnect(); }
    this.nodes = [];
  }

  destroy() { this.pause(); }
}

// Simple one-buffer player for a take or a demo file.
let single = null;
export async function playUrl(url, { onEnd } = {}) {
  const c = await resume();
  stopSingle();
  const buf = await loadBuffer(url, { cache: false });
  const s = c.createBufferSource();
  s.buffer = buf;
  s.connect(c.destination);
  s.onended = () => { if (single === s) { single = null; onEnd && onEnd(); } };
  s.start();
  single = s;
  return () => stopSingle();
}
export function stopSingle() {
  if (single) { const s = single; single = null; try { s.stop(); } catch { /* noop */ } }
}
